"""DeltaGraphBridge: Main pipeline for incremental graph updates."""

import hashlib
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple

from streamrag.extractor import ASTExtractor, extract
from streamrag.graph import LiquidGraph
from streamrag.models import (
    ASTEntity, BUILTINS, COMMON_ATTR_METHODS, SUPPORTED_EXTENSIONS,
    CodeChange, GraphEdge, GraphNode, GraphOperation,
    _is_test_file,
)


MAX_FILE_CONTENTS = 500  # Max files to cache full content for


def _path_similarity(file_a: str, file_b: str) -> int:
    """Score how similar two file paths are by shared directory prefix."""
    parts_a = file_a.split("/")
    parts_b = file_b.split("/")
    shared = 0
    for a, b in zip(parts_a, parts_b):
        if a == b:
            shared += 1
        else:
            break
    return shared


def _generate_node_id(file_path: str, entity_type: str, name: str) -> str:
    """Deterministic node ID: SHA256("{file_path}:{entity_type}:{name}")[:16]."""
    raw = f"{file_path}:{entity_type}:{name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class DeltaGraphBridge:
    """Orchestrates incremental graph updates from code changes.

    Pipeline: semantic gate -> delta computation -> removals (first!) ->
    additions -> modifications -> two-pass edge resolution -> cache updates.
    """

    def __init__(self, graph: Optional[LiquidGraph] = None,
                 extractor_registry: Optional["ExtractorRegistry"] = None,
                 versioned: bool = False) -> None:
        self.graph = graph or LiquidGraph()
        self._file_contents: Dict[str, str] = {}
        self._tracked_files: Set[str] = set()
        self._dependency_index: Dict[str, Set[str]] = defaultdict(set)
        self._module_file_index: Dict[str, str] = {}  # "api.auth.service" → "api/auth/service.py"
        self._module_file_collisions: Set[str] = set()  # short names with ambiguous mappings
        self._last_confidence: str = "none"
        self._resolution_stats: Dict[str, int] = {
            "total_attempted": 0,
            "resolved": 0,
            "ambiguous": 0,
            "to_test_file": 0,
            "external_skipped": 0,
        }
        self._registry = extractor_registry

        # V2 components (opt-in)
        self._op_log: List = []  # List of V2 GraphOp objects
        self._last_batch = None  # Optional OperationBatch from last process_change
        self._op_log_mark: int = 0  # Track batch boundaries in _op_log

        # VersionedGraph: tracks per-file versions and operation history
        self._versioned = None
        if versioned:
            from streamrag.v2.versioned_graph import VersionedGraph
            self._versioned = VersionedGraph(self.graph)

        # HierarchicalGraph + BoundedPropagator (set externally after init)
        self._hierarchical = None
        self._propagator = None
        self._propagating: bool = False  # recursion guard for propagation
        # SemanticPath cache: file_path -> List[SemanticPath]
        self._semantic_paths: Dict[str, list] = {}

    @property
    def version(self) -> int:
        """Current graph version (0 if versioning disabled)."""
        return self._versioned.version if self._versioned else 0

    @property
    def _extractor_registry(self):
        if self._registry is None:
            from streamrag.languages.registry import create_default_registry
            self._registry = create_default_registry()
        return self._registry

    def _extract(self, source: str, file_path: str = "",
                  shadow_fallback: bool = False) -> List[ASTEntity]:
        """Extract entities using the appropriate language extractor.

        For Python files, falls back to ShadowAST when the primary extractor
        returns empty on non-empty source (broken/incomplete code).
        Shadow fallback is opt-in to preserve is_semantic_change() behavior.
        """
        if file_path:
            ext = self._extractor_registry.get_extractor(file_path)
            if ext is not None:
                result = ext.extract(source, file_path)
                if not result and shadow_fallback and source.strip() and file_path.endswith((".py", ".pyi")):
                    return self._shadow_extract(source)
                # Dual extraction: SemanticPaths for Python files
                if file_path.endswith((".py", ".pyi")) and result:
                    try:
                        from streamrag.v2.semantic_path import ScopeAwareExtractor
                        sem_ext = ScopeAwareExtractor(file_path)
                        self._semantic_paths[file_path] = sem_ext.extract(source, file_path)
                    except (ImportError, Exception):
                        pass
                return result
        # Fallback to original Python extractor
        result = extract(source)
        if not result and shadow_fallback and source.strip():
            return self._shadow_extract(source)
        return result

    def _shadow_extract(self, source: str) -> List[ASTEntity]:
        """Fallback extraction using ShadowAST for broken Python code."""
        try:
            from streamrag.v2.shadow_ast import ShadowAST
            regions = ShadowAST().parse(source)
            entities = []
            for region in regions:
                for entity in region.entities:
                    # Tag shadow-extracted entities for auto-replacement on next successful parse
                    if not entity.signature_hash.startswith("shadow:"):
                        entity.signature_hash = f"shadow:{entity.signature_hash}"
                    entities.append(entity)
            return entities
        except Exception:
            return []

    def is_semantic_change(self, old_content: str, new_content: str,
                           file_path: str = "") -> bool:
        """Check if two versions differ semantically (not just whitespace/comments).

        If new content has a syntax error, this is NOT a semantic change
        (we don't create ghost nodes from broken code).
        """
        old_entities = self._extract(old_content, file_path)
        new_entities = self._extract(new_content, file_path)

        # If new content fails to parse (SyntaxError), treat as non-semantic
        if new_content.strip() and not new_entities and old_entities:
            return False

        old_sigs = {(e.name, e.signature_hash) for e in old_entities}
        new_sigs = {(e.name, e.signature_hash) for e in new_entities}
        return old_sigs != new_sigs

    def compute_delta(
        self, file_path: str, old_content: str, new_content: str
    ) -> Tuple[List[ASTEntity], List[ASTEntity], List[ASTEntity]]:
        """Compute (added, removed, modified) entities between two file versions.

        Includes rename detection via entity_type + position_overlap + structure_hash.
        """
        old_entities = self._extract(old_content, file_path)
        new_entities = self._extract(new_content, file_path, shadow_fallback=True)

        old_map: Dict[str, ASTEntity] = {e.name: e for e in old_entities}
        new_map: Dict[str, ASTEntity] = {e.name: e for e in new_entities}

        old_names = set(old_map.keys())
        new_names = set(new_map.keys())

        potentially_removed = old_names - new_names
        potentially_added = new_names - old_names

        # Rename detection
        renamed: List[ASTEntity] = []
        matched_added: Set[str] = set()

        for old_name in list(potentially_removed):
            old_entity = old_map[old_name]
            for new_name in list(potentially_added - matched_added):
                new_entity = new_map[new_name]
                if (
                    old_entity.entity_type == new_entity.entity_type
                    and self._positions_overlap(old_entity, new_entity)
                    and old_entity.structure_hash == new_entity.structure_hash
                ):
                    # It's a rename
                    new_entity.old_name = old_name
                    renamed.append(new_entity)
                    matched_added.add(new_name)
                    potentially_removed.discard(old_name)
                    break

        potentially_added -= matched_added

        # Actual results
        added = [new_map[n] for n in potentially_added]
        removed = [old_map[n] for n in potentially_removed]

        # Modification detection
        modified: List[ASTEntity] = []
        common_names = old_names & new_names
        for name in common_names:
            if old_map[name].signature_hash != new_map[name].signature_hash:
                modified.append(new_map[name])

        # Renames are appended to modified
        modified.extend(renamed)

        return added, removed, modified

    def process_change(self, change: CodeChange) -> List[GraphOperation]:
        """Main pipeline: process a code change and return graph operations.

        1. Semantic gate
        2. Compute delta
        3. Process removals (first!)
        4. Process additions
        5. Process modifications (handles renames)
        6. Two-pass edge resolution
        7. Update caches
        """
        file_path = change.file_path
        old_content = change.old_content
        new_content = change.new_content

        # 1. SEMANTIC GATE
        if not self.is_semantic_change(old_content, new_content, file_path):
            self._file_contents[file_path] = new_content
            self._tracked_files.add(file_path)
            # Evict cache to prevent unbounded growth from non-semantic changes
            if len(self._file_contents) > MAX_FILE_CONTENTS:
                excess = len(self._file_contents) - MAX_FILE_CONTENTS
                keys_to_remove = list(self._file_contents.keys())[:excess]
                for k in keys_to_remove:
                    del self._file_contents[k]
            return []

        # 2. COMPUTE DELTA
        added, removed, modified = self.compute_delta(file_path, old_content, new_content)

        operations: List[GraphOperation] = []

        # 3. PROCESS REMOVALS (first!)
        for entity in removed:
            node_id = _generate_node_id(file_path, entity.entity_type, entity.name)
            # Capture callers before removal (for proactive breaking-change detection)
            had_callers = []
            for edge in self.graph.get_incoming_edges(node_id):
                src = self.graph.get_node(edge.source_id)
                if src and src.file_path != file_path:
                    had_callers.append(src.name)
            self.graph.remove_node(node_id)
            # V2: Record RemoveNode op
            try:
                from streamrag.v2.operations import RemoveNode as RemoveNodeOp
                self._op_log.append(RemoveNodeOp(node_id=node_id))
            except ImportError:
                pass
            props = {"name": entity.name}
            if had_callers:
                props["had_callers"] = had_callers
            operations.append(GraphOperation(
                op_type="remove_node",
                node_id=node_id,
                node_type=entity.entity_type,
                properties=props,
            ))

        # 4. PROCESS ADDITIONS (imports first so edges exist for call resolution)
        added.sort(key=lambda e: (0 if e.entity_type == "import" else 1, e.name))
        for entity in added:
            node_id = _generate_node_id(file_path, entity.entity_type, entity.name)
            node = GraphNode(
                id=node_id,
                type=entity.entity_type,
                name=entity.name,
                file_path=file_path,
                line_start=entity.line_start,
                line_end=entity.line_end,
                properties={
                    "signature_hash": entity.signature_hash,
                    "calls": entity.calls,
                    "uses": entity.uses,
                    "inherits": entity.inherits,
                    "imports": entity.imports,
                    "type_refs": entity.type_refs,
                    "params": entity.params,
                    "decorators": entity.decorators,
                },
            )
            self.graph.add_node(node)
            # V2: Record AddNode op
            try:
                from streamrag.v2.operations import AddNode as AddNodeOp
                self._op_log.append(AddNodeOp(node=node))
            except ImportError:
                pass

            # First-pass edge creation
            edges = self._create_first_pass_edges(entity, node_id, file_path)

            # Reverse import sweep: link existing import nodes to this new definition
            if entity.entity_type in ("function", "class", "variable"):
                for existing_node in list(self.graph._nodes.values()):
                    if (existing_node.type == "import"
                            and existing_node.name == entity.name
                            and existing_node.file_path != file_path):
                        if not self._edge_exists(existing_node.id, node_id, "imports"):
                            self.graph.add_edge(GraphEdge(
                                source_id=existing_node.id,
                                target_id=node_id,
                                edge_type="imports",
                            ))
            operations.append(GraphOperation(
                op_type="add_node",
                node_id=node_id,
                node_type=entity.entity_type,
                properties=node.properties,
                edges=edges,
            ))

        # 5. PROCESS MODIFICATIONS
        for entity in modified:
            if entity.old_name is not None:
                # Rename: remove old, add new
                old_node_id = _generate_node_id(file_path, entity.entity_type, entity.old_name)
                self.graph.remove_node(old_node_id)

                new_node_id = _generate_node_id(file_path, entity.entity_type, entity.name)
                new_node = GraphNode(
                    id=new_node_id,
                    type=entity.entity_type,
                    name=entity.name,
                    file_path=file_path,
                    line_start=entity.line_start,
                    line_end=entity.line_end,
                    properties={
                        "signature_hash": entity.signature_hash,
                        "calls": entity.calls,
                        "uses": entity.uses,
                        "inherits": entity.inherits,
                        "imports": entity.imports,
                        "type_refs": entity.type_refs,
                        "params": entity.params,
                        "decorators": entity.decorators,
                        "renamed_from": entity.old_name,
                    },
                )
                self.graph.add_node(new_node)
                # V2: Record rename as RemoveNode + AddNode
                try:
                    from streamrag.v2.operations import RemoveNode as RemoveNodeOp, AddNode as AddNodeOp
                    self._op_log.append(RemoveNodeOp(node_id=old_node_id))
                    self._op_log.append(AddNodeOp(node=new_node))
                except ImportError:
                    pass
            else:
                # Body change: update existing node
                node_id = _generate_node_id(file_path, entity.entity_type, entity.name)
                existing = self.graph.get_node(node_id)
                if existing:
                    existing.line_start = entity.line_start
                    existing.line_end = entity.line_end
                    existing.properties["signature_hash"] = entity.signature_hash
                    existing.properties["calls"] = entity.calls
                    existing.properties["uses"] = entity.uses
                    existing.properties["inherits"] = entity.inherits
                    existing.properties["imports"] = entity.imports
                    existing.properties["type_refs"] = entity.type_refs
                    existing.properties["params"] = entity.params
                    existing.properties["decorators"] = entity.decorators
                    # V2: Record UpdateNode op
                    try:
                        from streamrag.v2.operations import UpdateNode as UpdateNodeOp
                        self._op_log.append(UpdateNodeOp(
                            node_id=node_id,
                            updates={"signature_hash": entity.signature_hash},
                        ))
                    except ImportError:
                        pass
                    # Clear stale outgoing edges so re-resolution picks up changes
                    for edge in self.graph.get_outgoing_edges(node_id):
                        if edge.edge_type in ("calls", "inherits", "uses_type", "decorated_by"):
                            self.graph.remove_edge(edge.source_id, edge.target_id, edge.edge_type)
                else:
                    # Node doesn't exist: fall through to add
                    node = GraphNode(
                        id=node_id,
                        type=entity.entity_type,
                        name=entity.name,
                        file_path=file_path,
                        line_start=entity.line_start,
                        line_end=entity.line_end,
                        properties={
                            "signature_hash": entity.signature_hash,
                            "calls": entity.calls,
                            "uses": entity.uses,
                            "inherits": entity.inherits,
                            "imports": entity.imports,
                            "type_refs": entity.type_refs,
                            "params": entity.params,
                            "decorators": entity.decorators,
                        },
                    )
                    self.graph.add_node(node)

            node_id = _generate_node_id(file_path, entity.entity_type, entity.name)
            operations.append(GraphOperation(
                op_type="update_node",
                node_id=node_id,
                node_type=entity.entity_type,
                properties={
                    "signature_hash": entity.signature_hash,
                    "name": entity.name,
                    **({"renamed_from": entity.old_name} if entity.old_name else {}),
                },
            ))

        # 6. TWO-PASS EDGE RESOLUTION
        all_changed = added + modified
        for entity in all_changed:
            source_id = _generate_node_id(file_path, entity.entity_type, entity.name)
            self._resolve_pending_edges(entity, source_id, file_path)

        # 7. UPDATE CACHES
        self._file_contents[file_path] = new_content
        self._tracked_files.add(file_path)
        if len(self._file_contents) > MAX_FILE_CONTENTS:
            # Evict oldest entries (FIFO via dict insertion order, Python 3.7+)
            excess = len(self._file_contents) - MAX_FILE_CONTENTS
            keys_to_remove = list(self._file_contents.keys())[:excess]
            for k in keys_to_remove:
                del self._file_contents[k]
        self._update_dependency_index(file_path)
        self._update_module_file_index(file_path)

        # Wrap V2 ops in OperationBatch for atomic record
        try:
            from streamrag.v2.operations import OperationBatch
            if self._op_log:
                # Create batch from ops accumulated this call
                batch_start = getattr(self, '_op_log_mark', 0)
                new_ops = self._op_log[batch_start:]
                if new_ops:
                    self._last_batch = OperationBatch(list(new_ops))
                self._op_log_mark = len(self._op_log)
        except ImportError:
            pass

        # 8. RECORD IN VERSIONED GRAPH (if enabled)
        if self._versioned:
            for op in operations:
                self._versioned.record_operation(op, file_path=file_path)

        # 9. BOUNDED PROPAGATION (if enabled)
        if self._propagator and not self._propagating:
            self._propagating = True
            try:
                self._propagator.record_edit(file_path)
                result = self._propagator.propagate(
                    file_path,
                    update_fn=self._re_parse_file,
                    graph=self.graph,
                )
                # Extend operations with sync-processed results (informational)
                for fp in result.sync_processed:
                    operations.append(GraphOperation(
                        op_type="update_node",
                        node_id="",
                        node_type="propagation",
                        properties={"file": fp, "phase": "sync"},
                    ))
            finally:
                self._propagating = False

        # 10. TRACK FILE IN HIERARCHICAL GRAPH (if enabled)
        if self._hierarchical:
            self._hierarchical.open_file(file_path)

        return operations

    def _re_parse_file(self, file_path: str) -> List[GraphOperation]:
        """Re-parse a file and update the graph (for propagation)."""
        import os
        try:
            with open(file_path, "r") as f:
                content = f.read()
        except (IOError, OSError):
            return []
        old_content = self._file_contents.get(file_path, "")
        if old_content == content:
            return []
        change = CodeChange(file_path=file_path, old_content=old_content, new_content=content)
        return self.process_change(change)

    def _create_first_pass_edges(
        self, entity: ASTEntity, source_id: str, file_path: str
    ) -> List[Tuple[str, str]]:
        """Create edges during the first pass (within-file lookups)."""
        edges: List[Tuple[str, str]] = []

        for called_name in entity.calls:
            target = self._find_target_node(called_name, file_path, "function")
            confidence = self._last_confidence
            if target is None:
                target = self._find_target_node(called_name, file_path, "class")
                confidence = self._last_confidence
            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "calls"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="calls",
                        properties={"confidence": confidence},
                    ))
                    edges.append((target.id, "calls"))

        for base_name in entity.inherits:
            target = self._find_target_node(base_name, file_path, "class")
            confidence = self._last_confidence
            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "inherits"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="inherits",
                        properties={"confidence": confidence},
                    ))
                    edges.append((target.id, "inherits"))

        # Import edges: link import entities to their definitions
        if entity.entity_type == "import":
            for _module, imported_name in entity.imports:
                if imported_name == "*":
                    star_edges = self._expand_star_import(entity, source_id, file_path, _module)
                    edges.extend(star_edges)
                    continue
                target = self._find_import_target(imported_name, file_path, module=_module)
                if target and target.id != source_id:
                    if not self._edge_exists(source_id, target.id, "imports"):
                        self.graph.add_edge(GraphEdge(
                            source_id=source_id,
                            target_id=target.id,
                            edge_type="imports",
                            properties={"module": _module, "name": imported_name, "confidence": "high"},
                        ))
                        edges.append((target.id, "imports"))

        # Type reference edges: link type annotations to class definitions
        for type_name in entity.type_refs:
            target = self._find_target_node(type_name, file_path, "class")
            confidence = self._last_confidence
            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "uses_type"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="uses_type",
                        properties={"confidence": confidence},
                    ))
                    edges.append((target.id, "uses_type"))

        # Decorator edges: link decorated entities to decorator definitions
        for dec_name in entity.decorators:
            target = self._find_target_node(dec_name, file_path, "function")
            confidence = self._last_confidence
            if target is None:
                target = self._find_target_node(dec_name, file_path, "class")
                confidence = self._last_confidence
            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "decorated_by"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="decorated_by",
                        properties={"confidence": confidence},
                    ))
                    edges.append((target.id, "decorated_by"))

        return edges

    def _resolve_pending_edges(
        self, entity: ASTEntity, source_id: str, file_path: str
    ) -> None:
        """Two-pass edge resolution: prefer cross-file matches."""
        # Resolve inherits edges
        for base_name in entity.inherits:
            target = self._find_target_node(base_name, file_path, "class")
            confidence = self._last_confidence
            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "inherits"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="inherits",
                        properties={"confidence": confidence},
                    ))

        # Resolve calls edges (uses import-context-aware _find_target_node)
        for called_name in entity.calls:
            target = self._find_target_node(called_name, file_path, "function")
            confidence = self._last_confidence
            if target is None:
                target = self._find_target_node(called_name, file_path, "class")
                confidence = self._last_confidence

            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "calls"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="calls",
                        properties={"confidence": confidence},
                    ))

        # Resolve import edges
        if entity.entity_type == "import":
            for _module, imported_name in entity.imports:
                if imported_name == "*":
                    self._expand_star_import(entity, source_id, file_path, _module)
                    continue
                target = self._find_import_target(imported_name, file_path, module=_module)
                if target and target.id != source_id:
                    if not self._edge_exists(source_id, target.id, "imports"):
                        self.graph.add_edge(GraphEdge(
                            source_id=source_id,
                            target_id=target.id,
                            edge_type="imports",
                            properties={"module": _module, "name": imported_name, "confidence": "high"},
                        ))

        # Reverse import resolution: if this is a definition, link import nodes to it
        if entity.entity_type in ("function", "class", "variable"):
            for node in list(self.graph._nodes.values()):
                if (node.type == "import"
                        and node.name == entity.name
                        and node.file_path != file_path):
                    if not self._edge_exists(node.id, source_id, "imports"):
                        self.graph.add_edge(GraphEdge(
                            source_id=node.id,
                            target_id=source_id,
                            edge_type="imports",
                            properties={"confidence": "high"},
                        ))

        # Resolve type reference edges
        for type_name in entity.type_refs:
            target = self._find_target_node(type_name, file_path, "class")
            confidence = self._last_confidence
            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "uses_type"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="uses_type",
                        properties={"confidence": confidence},
                    ))

        # Resolve decorator edges
        for dec_name in entity.decorators:
            target = self._find_target_node(dec_name, file_path, "function")
            confidence = self._last_confidence
            if target is None:
                target = self._find_target_node(dec_name, file_path, "class")
                confidence = self._last_confidence
            if target and target.id != source_id:
                if not self._edge_exists(source_id, target.id, "decorated_by"):
                    self.graph.add_edge(GraphEdge(
                        source_id=source_id,
                        target_id=target.id,
                        edge_type="decorated_by",
                        properties={"confidence": confidence},
                    ))

    def _expand_star_import(
        self, entity: ASTEntity, source_id: str, file_path: str, module: str
    ) -> List[Tuple[str, str]]:
        """Expand `from module import *` into individual import edges.

        Looks up the module's file, gets its exports, and creates an import
        edge to each exported definition.
        """
        edges: List[Tuple[str, str]] = []
        target_file = self._module_file_index.get(module)
        if not target_file:
            return edges

        export_names = self.get_module_exports(target_file)
        for name in export_names:
            # Find the definition node in the target file
            for node in self.graph._nodes.values():
                if (node.name == name
                        and node.type in ("function", "class", "variable")
                        and node.file_path == target_file):
                    if not self._edge_exists(source_id, node.id, "imports"):
                        self.graph.add_edge(GraphEdge(
                            source_id=source_id,
                            target_id=node.id,
                            edge_type="imports",
                            properties={
                                "module": module,
                                "name": name,
                                "confidence": "medium",
                                "via_star": True,
                            },
                        ))
                        edges.append((node.id, "imports"))
                    break
        return edges

    def _follow_import_chain(self, import_node: GraphNode, max_hops: int = 5) -> Optional[GraphNode]:
        """Follow a chain of import nodes to find the actual definition.

        Given an import node that re-exports from another module, follow the
        imports chain until we find a function/class/variable definition.
        """
        visited = {import_node.id}
        current = import_node
        for _ in range(max_hops):
            found_next = False
            for edge in self.graph.get_outgoing_edges(current.id):
                if edge.edge_type == "imports":
                    target = self.graph.get_node(edge.target_id)
                    if target is None:
                        continue
                    if target.type in ("function", "class", "variable"):
                        return target  # Found the definition
                    if target.type == "import" and target.id not in visited:
                        visited.add(target.id)
                        current = target
                        found_next = True
                        break
            if not found_next:
                break
        return None

    def _find_import_target(
        self, name: str, current_file: str, module: str = ""
    ) -> Optional[GraphNode]:
        """Find the definition node that an import refers to.

        Uses module path to resolve to the correct file first,
        then falls back to cross-file name matching.
        Follows re-export chains when the immediate target is another import.
        """
        # Strategy 1: Use module path to find the exact target file
        if module:
            target_file = self._module_file_index.get(module)
            if target_file:
                # First try to find a definition node
                for node in self.graph._nodes.values():
                    if (node.name == name
                            and node.type in ("function", "class", "variable")
                            and node.file_path == target_file):
                        return node
                # If no definition, try to find an import node and follow the chain
                for node in self.graph._nodes.values():
                    if (node.name == name
                            and node.type == "import"
                            and node.file_path == target_file):
                        definition = self._follow_import_chain(node)
                        if definition:
                            return definition

        # Strategy 2: Fallback — prefer cross-file, then same-file
        cross_file: Optional[GraphNode] = None
        same_file: Optional[GraphNode] = None

        for node in self.graph._nodes.values():
            if node.name == name and node.type in ("function", "class", "variable"):
                if node.file_path != current_file:
                    if cross_file is None:
                        cross_file = node
                else:
                    same_file = node

        if cross_file or same_file:
            return cross_file or same_file

        # Strategy 3: Follow re-export chains from cross-file import nodes
        for node in self.graph._nodes.values():
            if (node.name == name
                    and node.type == "import"
                    and node.file_path != current_file):
                definition = self._follow_import_chain(node)
                if definition:
                    return definition

        return None

    def _get_imported_file_paths(self, file_path: str) -> Set[str]:
        """Get set of file paths that this file imports from via import edges."""
        result: Set[str] = set()
        nodes = self.graph.get_nodes_by_file(file_path)
        for node in nodes:
            if node.type == "import":
                for edge in self.graph.get_outgoing_edges(node.id):
                    if edge.edge_type == "imports":
                        target = self.graph.get_node(edge.target_id)
                        if target:
                            result.add(target.file_path)
        return result

    def _resolve_receiver_to_file(
        self, receiver: str, current_file: str
    ) -> Optional[str]:
        """Resolve an import receiver name to its source file.

        If current_file has 'import auth_service' or 'from api.auth import auth_service',
        find the file that auth_service comes from.
        """
        # Check import nodes in current file for receiver name
        for node in self.graph.get_nodes_by_file(current_file):
            if node.type == "import" and node.name == receiver:
                # Follow import edge to find target file
                for edge in self.graph.get_outgoing_edges(node.id):
                    if edge.edge_type == "imports":
                        target = self.graph.get_node(edge.target_id)
                        if target:
                            return target.file_path
                # No edge yet — try module index from import metadata
                for module, _name in node.properties.get("imports", []):
                    if module:
                        file_path = self._module_file_index.get(module)
                        if file_path:
                            return file_path
        # Try module-to-file index directly (receiver might be a module name)
        return self._module_file_index.get(receiver)

    def _find_target_node(
        self, name: str, current_file: str, expected_type: str
    ) -> Optional[GraphNode]:
        """Find a target node by name with import-context disambiguation.

        Handles qualified names (e.g., "receiver.method") by resolving the
        receiver to a file first, then looking for the method in that file.

        Priority:
        1. Qualified name resolution (receiver → file → method in file)
        2. Exact match from imported file
        3. Exact match cross-file
        4. Exact match same-file
        5. Suffix match (.name) from imported file
        6. Suffix match cross-file
        7. Suffix match same-file
        8. Fallback get_node_by_name

        Returns None for builtins/common attr methods.
        """
        self._last_confidence = "none"
        self._resolution_stats["total_attempted"] += 1

        if name in BUILTINS:
            self._resolution_stats["external_skipped"] += 1
            return None
        # Note: COMMON_ATTR_METHODS filtering is handled by the extractor.
        # Bare names from ast.Name calls (e.g. run()) are legitimate function
        # calls. Qualified names (Type.method) are precise from type context.

        # Qualified name resolution: "receiver.method" → find method in receiver's file
        if "." in name:
            parts = name.split(".", 1)
            receiver, method = parts[0], parts[1]

            # Class-name qualified: find class node directly, then method in same file
            if receiver and receiver[0].isupper() and receiver not in BUILTINS:
                class_ids = self.graph._nodes_by_name.get(receiver, set())
                for cid in class_ids:
                    cnode = self.graph._nodes.get(cid)
                    if cnode and cnode.type == "class":
                        for node in self.graph._nodes.values():
                            if (node.type == expected_type
                                    and node.file_path == cnode.file_path
                                    and (node.name == name
                                         or node.name == method
                                         or node.name.endswith(f".{method}"))):
                                self._last_confidence = "high"
                                self._resolution_stats["resolved"] += 1
                                if _is_test_file(node.file_path):
                                    self._resolution_stats["to_test_file"] += 1
                                return node

            # Import-based resolution: resolve receiver as module/import
            if receiver not in BUILTINS:
                receiver_file = self._resolve_receiver_to_file(receiver, current_file)
                if receiver_file:
                    for node in self.graph._nodes.values():
                        if (node.type == expected_type
                                and node.file_path == receiver_file
                                and (node.name == method
                                     or node.name == name
                                     or node.name.endswith(f".{method}"))):
                            self._last_confidence = "high"
                            self._resolution_stats["resolved"] += 1
                            if _is_test_file(node.file_path):
                                self._resolution_stats["to_test_file"] += 1
                            return node

        # Enhanced resolution via SemanticPath (if available)
        if self._semantic_paths:
            try:
                from streamrag.v2.semantic_path import resolve_name as sp_resolve
                # Get scope chain for current file
                current_paths = self._semantic_paths.get(current_file, [])
                if current_paths:
                    resolved = sp_resolve(name, (), current_paths)
                    if resolved:
                        # Find the graph node matching the resolved SemanticPath
                        for node in self.graph._nodes.values():
                            if (node.type == expected_type
                                    and node.name == resolved.name
                                    and node.file_path == resolved.file_path):
                                self._last_confidence = "high"
                                self._resolution_stats["resolved"] += 1
                                return node
            except (ImportError, Exception):
                pass

        imported_files = self._get_imported_file_paths(current_file)

        cross_file_imported: Optional[GraphNode] = None
        cross_file_any: Optional[GraphNode] = None
        cross_file_any_score: int = -1
        same_file: Optional[GraphNode] = None

        suffix_cross_imported: Optional[GraphNode] = None
        suffix_cross_any: Optional[GraphNode] = None
        suffix_cross_any_score: int = -1
        suffix_same_file: Optional[GraphNode] = None

        suffix = f".{name}"

        caller_is_test = _is_test_file(current_file)
        candidate_count = 0

        for node in self.graph._nodes.values():
            if node.type != expected_type:
                continue

            # Penalize test-file targets when caller is not a test file
            test_penalty = (not caller_is_test and _is_test_file(node.file_path))

            if node.name == name:
                candidate_count += 1
                if node.file_path == current_file:
                    same_file = node
                elif node.file_path in imported_files:
                    cross_file_imported = node
                else:
                    score = _path_similarity(current_file, node.file_path)
                    if test_penalty:
                        score -= 1000
                    if score > cross_file_any_score:
                        cross_file_any = node
                        cross_file_any_score = score
            elif node.name.endswith(suffix):
                candidate_count += 1
                if node.file_path == current_file:
                    suffix_same_file = node
                elif node.file_path in imported_files:
                    suffix_cross_imported = node
                else:
                    score = _path_similarity(current_file, node.file_path)
                    if test_penalty:
                        score -= 1000
                    if score > suffix_cross_any_score:
                        suffix_cross_any = node
                        suffix_cross_any_score = score

        if candidate_count > 1:
            self._resolution_stats["ambiguous"] += 1

        # Determine result and confidence
        if cross_file_imported:
            result = cross_file_imported
            self._last_confidence = "high"
        elif cross_file_any:
            result = cross_file_any
            self._last_confidence = "medium"
        elif same_file:
            result = same_file
            self._last_confidence = "medium"
        elif suffix_cross_imported:
            result = suffix_cross_imported
            self._last_confidence = "medium"
        elif suffix_cross_any:
            result = suffix_cross_any
            self._last_confidence = "low"
        elif suffix_same_file:
            result = suffix_same_file
            self._last_confidence = "low"
        else:
            result = None

        if result:
            self._resolution_stats["resolved"] += 1
            if _is_test_file(result.file_path):
                self._resolution_stats["to_test_file"] += 1
            return result

        # Inheritance chain traversal: if "ClassName.method", check parent classes
        if "." in name and expected_type == "function":
            inherited = self._find_in_parent_classes(name)
            if inherited:
                self._last_confidence = "low"
                self._resolution_stats["resolved"] += 1
                if _is_test_file(inherited.file_path):
                    self._resolution_stats["to_test_file"] += 1
                return inherited

        # Index-based suffix fallback for bare names (e.g. "process_change" -> "DeltaGraphBridge.process_change")
        if "." not in name and expected_type == "function":
            suffix_target = f".{name}"
            candidates = []
            for indexed_name, nids in self.graph._nodes_by_name.items():
                if indexed_name.endswith(suffix_target):
                    for nid in nids:
                        node = self.graph._nodes.get(nid)
                        if node and node.type == "function":
                            if not (not caller_is_test and _is_test_file(node.file_path)):
                                candidates.append(node)
            if len(candidates) == 1:
                self._last_confidence = "low"
                self._resolution_stats["resolved"] += 1
                if _is_test_file(candidates[0].file_path):
                    self._resolution_stats["to_test_file"] += 1
                return candidates[0]
            elif candidates:
                for c in candidates:
                    if c.file_path in imported_files:
                        self._last_confidence = "low"
                        self._resolution_stats["resolved"] += 1
                        if _is_test_file(c.file_path):
                            self._resolution_stats["to_test_file"] += 1
                        return c
                best = max(candidates, key=lambda c: _path_similarity(current_file, c.file_path))
                self._last_confidence = "low"
                self._resolution_stats["resolved"] += 1
                if _is_test_file(best.file_path):
                    self._resolution_stats["to_test_file"] += 1
                return best

        # Fallback: get_node_by_name, but prefer non-test nodes when caller is source
        node_ids = self.graph._nodes_by_name.get(name)
        if node_ids:
            best = None
            for nid in node_ids:
                node = self.graph._nodes.get(nid)
                if node:
                    if not caller_is_test and _is_test_file(node.file_path):
                        if best is None:
                            best = node  # keep as last resort
                    else:
                        self._last_confidence = "low"
                        self._resolution_stats["resolved"] += 1
                        if _is_test_file(node.file_path):
                            self._resolution_stats["to_test_file"] += 1
                        return node
            if best:
                self._last_confidence = "low"
                self._resolution_stats["resolved"] += 1
                self._resolution_stats["to_test_file"] += 1
            return best
        return None

    def _find_in_parent_classes(self, qualified_name: str) -> Optional[GraphNode]:
        """Walk inheritance chain to find a method defined in a parent class.

        Given "ChildClass.method", find ChildClass, walk up inherits edges,
        and look for "ParentClass.method" in each ancestor.
        """
        class_name, method = qualified_name.rsplit(".", 1)
        # Find the class node
        for node in self.graph._nodes.values():
            if node.type == "class" and node.name == class_name:
                # BFS up inheritance chain (max 5 levels)
                visited = {node.id}
                queue = [node.id]
                for _ in range(5):
                    if not queue:
                        break
                    next_queue = []
                    for nid in queue:
                        for edge in self.graph.get_outgoing_edges(nid):
                            if edge.edge_type == "inherits" and edge.target_id not in visited:
                                visited.add(edge.target_id)
                                parent = self.graph.get_node(edge.target_id)
                                if parent:
                                    next_queue.append(edge.target_id)
                                    # Look for "ParentClass.method"
                                    target_name = f"{parent.name}.{method}"
                                    for fn in self.graph._nodes.values():
                                        if fn.type == "function" and fn.name == target_name:
                                            return fn
                    queue = next_queue
        return None

    def _edge_exists(self, source_id: str, target_id: str, edge_type: str) -> bool:
        """Check if an edge already exists."""
        for edge in self.graph.get_outgoing_edges(source_id):
            if edge.target_id == target_id and edge.edge_type == edge_type:
                return True
        return False

    def _update_dependency_index(self, file_path: str) -> None:
        """Update the dependency index for a file (skips builtins)."""
        nodes = self.graph.get_nodes_by_file(file_path)
        for node in nodes:
            for called_name in node.properties.get("calls", []):
                if called_name not in BUILTINS and called_name not in COMMON_ATTR_METHODS:
                    self._dependency_index[called_name].add(file_path)

    def _update_module_file_index(self, file_path: str) -> None:
        """Register file path as module path with all suffix variants.

        "api/auth/auth_service.py" registers as:
          "auth_service" → file_path
          "auth.auth_service" → file_path
          "api.auth.auth_service" → file_path
        """
        module_path = file_path.replace("/", ".").replace("\\", ".")
        for ext in SUPPORTED_EXTENSIONS:
            if module_path.endswith(ext):
                module_path = module_path[:-len(ext)]
                break
        # Strip leading dots
        module_path = module_path.lstrip(".")
        if not module_path:
            return
        parts = module_path.split(".")
        for i in range(len(parts)):
            suffix = ".".join(parts[i:])
            # Only overwrite if not already set (first file wins for ambiguous suffixes)
            if suffix not in self._module_file_index:
                self._module_file_index[suffix] = file_path
            elif self._module_file_index[suffix] != file_path:
                self._module_file_collisions.add(suffix)

    def get_affected_files(
        self, changed_file: str, changed_entity_name: str,
        max_depth: int = 3,
    ) -> List[str]:
        """Find files affected by a change using BFS.

        Phase 1: Direct dependency index lookup
        Phase 2: Cross-file edges pointing TO entities in the changed file
        Phase 3: Transitive BFS following graph edges (capped at max_depth)
        """
        affected: Set[str] = set()
        queue: deque = deque()

        # Phase 1: Direct dependencies from index
        direct = self._dependency_index.get(changed_entity_name, set())
        for f in direct:
            if f != changed_file:
                affected.add(f)
                queue.append((f, 1))

        # Phase 2: Cross-file edges pointing TO entities in the changed file
        changed_nodes = self.graph.get_nodes_by_file(changed_file)
        for node in changed_nodes:
            for edge in self.graph.get_incoming_edges(node.id):
                source_node = self.graph.get_node(edge.source_id)
                if source_node and source_node.file_path != changed_file:
                    if source_node.file_path not in affected:
                        affected.add(source_node.file_path)
                        queue.append((source_node.file_path, 1))

        # Phase 3: Transitive BFS following INCOMING edges (callers of callers)
        visited: Set[str] = set(affected)
        while queue:
            current_file, depth = queue.popleft()
            if depth >= max_depth:
                continue
            file_nodes = self.graph.get_nodes_by_file(current_file)
            for node in file_nodes:
                for edge in self.graph.get_incoming_edges(node.id):
                    if edge.edge_type in ("calls", "imports", "inherits"):
                        source_node = self.graph.get_node(edge.source_id)
                        if source_node and source_node.file_path != changed_file:
                            if source_node.file_path not in visited:
                                visited.add(source_node.file_path)
                                affected.add(source_node.file_path)
                                queue.append((source_node.file_path, depth + 1))

        return list(affected)

    def remove_file(self, file_path: str) -> List[GraphOperation]:
        """Remove all nodes and edges for a file. Returns list of removal operations."""
        operations: List[GraphOperation] = []
        nodes = self.graph.get_nodes_by_file(file_path)
        for node in list(nodes):
            self.graph.remove_node(node.id)
            operations.append(GraphOperation(
                op_type="remove_node",
                node_id=node.id,
                node_type=node.type,
                properties={"name": node.name},
            ))
        # Clean bridge caches
        self._file_contents.pop(file_path, None)
        self._tracked_files.discard(file_path)
        # Clean dependency index entries referencing this file
        for key in list(self._dependency_index.keys()):
            self._dependency_index[key].discard(file_path)
            if not self._dependency_index[key]:
                del self._dependency_index[key]
        # Clean module_file_index entries pointing to this file
        for key in list(self._module_file_index.keys()):
            if self._module_file_index[key] == file_path:
                del self._module_file_index[key]
                self._module_file_collisions.discard(key)
        return operations

    def get_module_exports(self, file_path: str) -> List[str]:
        """Get module exports: __all__ if defined, else all top-level names."""
        nodes = self.graph.get_nodes_by_file(file_path)
        for node in nodes:
            if node.name == "__all__" and node.type == "variable":
                return list(node.properties.get("uses", []))
        # Fallback: all top-level names (no dot = not nested)
        return [n.name for n in nodes
                if n.type in ("function", "class", "variable")
                and "." not in n.name
                and n.name != "__all__"]

    def check_new_cycles(self, file_path: str) -> List[List[str]]:
        """Check for new circular dependencies involving the changed file."""
        all_cycles = self.graph.find_cycles(exclude_tests=True)
        return [c for c in all_cycles if file_path in c]

    def check_new_dead_code(self, file_path: str) -> List[GraphNode]:
        """Check for dead code in the changed file only."""
        all_dead = self.graph.find_dead_code(exclude_tests=True, exclude_framework=True)
        return [n for n in all_dead if n.file_path == file_path]

    def snapshot(self) -> "DeltaGraphBridge":
        """Deep copy the bridge including graph, caches, and dependency index."""
        new_bridge = DeltaGraphBridge(self.graph.snapshot(),
                                      extractor_registry=self._registry)
        new_bridge._file_contents = dict(self._file_contents)
        new_bridge._tracked_files = set(self._tracked_files)
        new_bridge._dependency_index = defaultdict(
            set, {k: set(v) for k, v in self._dependency_index.items()}
        )
        new_bridge._module_file_index = dict(self._module_file_index)
        new_bridge._module_file_collisions = set(self._module_file_collisions)
        new_bridge._resolution_stats = dict(self._resolution_stats)
        new_bridge._last_confidence = self._last_confidence
        return new_bridge

    @staticmethod
    def _positions_overlap(e1: ASTEntity, e2: ASTEntity) -> bool:
        """Check if two entities overlap in position."""
        if e1.line_start == e2.line_start:
            return True
        return e1.line_start <= e2.line_end and e2.line_start <= e1.line_end
