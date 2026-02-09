"""LiquidGraph: In-memory code graph with indexed lookups."""

import copy
import hashlib
import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from streamrag.models import FRAMEWORK_DEAD_CODE_PATTERNS, GraphEdge, GraphNode, _is_test_file


class LiquidGraph:
    """In-memory graph with 5 indexes for fast lookups.

    Indexes maintained on every add/remove:
        _nodes: id -> GraphNode (primary store)
        _nodes_by_file: file_path -> {node_ids}
        _nodes_by_type: entity_type -> {node_ids}
        _nodes_by_name: name -> {node_ids}
        _outgoing_edges: source_id -> [edges]
        _incoming_edges: target_id -> [edges]
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, GraphNode] = {}
        self._nodes_by_file: Dict[str, Set[str]] = defaultdict(set)
        self._nodes_by_type: Dict[str, Set[str]] = defaultdict(set)
        self._nodes_by_name: Dict[str, Set[str]] = defaultdict(set)
        self._outgoing_edges: Dict[str, List[GraphEdge]] = defaultdict(list)
        self._incoming_edges: Dict[str, List[GraphEdge]] = defaultdict(list)

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph, updating all indexes."""
        self._nodes[node.id] = node
        self._nodes_by_file[node.file_path].add(node.id)
        self._nodes_by_type[node.type].add(node.id)
        self._nodes_by_name[node.name].add(node.id)

    def remove_node(self, node_id: str) -> Optional[GraphNode]:
        """Remove a node and cascade-remove all its edges."""
        node = self._nodes.pop(node_id, None)
        if node is None:
            return None

        # Remove from secondary indexes
        file_set = self._nodes_by_file.get(node.file_path)
        if file_set:
            file_set.discard(node_id)
            if not file_set:
                del self._nodes_by_file[node.file_path]

        type_set = self._nodes_by_type.get(node.type)
        if type_set:
            type_set.discard(node_id)
            if not type_set:
                del self._nodes_by_type[node.type]

        name_set = self._nodes_by_name.get(node.name)
        if name_set:
            name_set.discard(node_id)
            if not name_set:
                del self._nodes_by_name[node.name]

        # Cascade-remove edges involving this node
        # Remove outgoing edges and their incoming references
        outgoing = self._outgoing_edges.pop(node_id, [])
        for edge in outgoing:
            incoming = self._incoming_edges.get(edge.target_id)
            if incoming:
                self._incoming_edges[edge.target_id] = [
                    e for e in incoming if e.source_id != node_id
                ]
                if not self._incoming_edges[edge.target_id]:
                    del self._incoming_edges[edge.target_id]

        # Remove incoming edges and their outgoing references
        incoming = self._incoming_edges.pop(node_id, [])
        for edge in incoming:
            outgoing_list = self._outgoing_edges.get(edge.source_id)
            if outgoing_list:
                self._outgoing_edges[edge.source_id] = [
                    e for e in outgoing_list if e.target_id != node_id
                ]
                if not self._outgoing_edges[edge.source_id]:
                    del self._outgoing_edges[edge.source_id]

        return node

    def add_edge(self, edge: GraphEdge) -> None:
        """Add a directed edge to the graph."""
        self._outgoing_edges[edge.source_id].append(edge)
        self._incoming_edges[edge.target_id].append(edge)

    def remove_edge(self, source_id: str, target_id: str, edge_type: str) -> Optional[GraphEdge]:
        """Remove a specific edge."""
        removed = None
        outgoing = self._outgoing_edges.get(source_id, [])
        for i, edge in enumerate(outgoing):
            if edge.target_id == target_id and edge.edge_type == edge_type:
                removed = outgoing.pop(i)
                break
        if not outgoing and source_id in self._outgoing_edges:
            del self._outgoing_edges[source_id]

        incoming = self._incoming_edges.get(target_id, [])
        for i, edge in enumerate(incoming):
            if edge.source_id == source_id and edge.edge_type == edge_type:
                incoming.pop(i)
                break
        if not incoming and target_id in self._incoming_edges:
            del self._incoming_edges[target_id]

        return removed

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    def get_node_by_name(self, name: str) -> Optional[GraphNode]:
        """Get the first node matching a name."""
        node_ids = self._nodes_by_name.get(name)
        if node_ids:
            first_id = next(iter(node_ids))
            return self._nodes.get(first_id)
        return None

    def get_nodes_by_file(self, file_path: str) -> List[GraphNode]:
        """Get all nodes in a file."""
        node_ids = self._nodes_by_file.get(file_path, set())
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]

    def get_all_nodes(self) -> List[GraphNode]:
        """Get all nodes in the graph."""
        return list(self._nodes.values())

    def get_all_edges(self) -> List[GraphEdge]:
        """Get all edges in the graph."""
        edges = []
        for edge_list in self._outgoing_edges.values():
            edges.extend(edge_list)
        return edges

    def get_outgoing_edges(self, node_id: str) -> List[GraphEdge]:
        """Get all edges originating from a node."""
        return list(self._outgoing_edges.get(node_id, []))

    def get_incoming_edges(self, node_id: str) -> List[GraphEdge]:
        """Get all edges pointing to a node."""
        return list(self._incoming_edges.get(node_id, []))

    def query(
        self,
        file_path: Optional[str] = None,
        entity_type: Optional[str] = None,
        name: Optional[str] = None,
    ) -> List[GraphNode]:
        """Query nodes by intersecting index sets with AND logic.

        No args = return everything.
        """
        result_ids: Optional[Set[str]] = None

        if file_path is not None:
            ids = self._nodes_by_file.get(file_path, set())
            result_ids = set(ids) if result_ids is None else result_ids & ids

        if entity_type is not None:
            ids = self._nodes_by_type.get(entity_type, set())
            result_ids = set(ids) if result_ids is None else result_ids & ids

        if name is not None:
            ids = self._nodes_by_name.get(name, set())
            result_ids = set(ids) if result_ids is None else result_ids & ids

        if result_ids is None:
            # No filters: return everything
            return list(self._nodes.values())

        return [self._nodes[nid] for nid in result_ids if nid in self._nodes]

    def query_regex(
        self,
        name_pattern: str,
        file_path: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> List[GraphNode]:
        """Query nodes where name matches a regex pattern.

        Supports patterns like 'test_.*', '.*Handler', 'get_.*'.
        Other filters (file_path, entity_type) are AND-combined.
        """
        compiled = re.compile(name_pattern)
        candidates = self.query(file_path=file_path, entity_type=entity_type)
        return [n for n in candidates if compiled.search(n.name)]

    def traverse(
        self,
        start_node_id: str,
        edge_types: Optional[List[str]] = None,
        direction: str = "outgoing",
        max_depth: int = 3,
    ) -> List[Tuple[GraphNode, int]]:
        """BFS traversal from a starting node, following specific edge types.

        Args:
            start_node_id: ID of the starting node.
            edge_types: Filter to only these edge types. None = all.
            direction: "outgoing", "incoming", or "both".
            max_depth: Maximum traversal depth.

        Returns list of (node, depth) tuples, excluding the start node.
        """
        visited: Set[str] = {start_node_id}
        result: List[Tuple[GraphNode, int]] = []
        queue: deque = deque([(start_node_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            edges: List[GraphEdge] = []
            if direction in ("outgoing", "both"):
                edges.extend(self.get_outgoing_edges(current_id))
            if direction in ("incoming", "both"):
                edges.extend(self.get_incoming_edges(current_id))

            for edge in edges:
                if edge_types and edge.edge_type not in edge_types:
                    continue
                next_id = edge.target_id if edge.source_id == current_id else edge.source_id
                if next_id not in visited:
                    visited.add(next_id)
                    node = self.get_node(next_id)
                    if node:
                        result.append((node, depth + 1))
                        queue.append((next_id, depth + 1))

        return result

    def find_dead_code(
        self,
        entry_point_names: Optional[Set[str]] = None,
        entry_point_types: Optional[Set[str]] = None,
        exclude_tests: bool = True,
        exclude_framework: bool = True,
    ) -> List[GraphNode]:
        """Find potentially dead code: nodes with no incoming edges.

        Args:
            entry_point_names: Names to exclude (e.g., {"main", "__module__"}).
            entry_point_types: Types to exclude (e.g., {"import", "module_code"}).
            exclude_tests: Skip nodes in test files.
            exclude_framework: Skip nodes matching framework patterns (test_, visit_, etc.).

        Returns nodes that have zero incoming edges and are not entry points.
        """
        entry_names = entry_point_names or {"main", "__main__", "__module__"}
        entry_types = entry_point_types or {"import", "module_code", "variable"}

        dead: List[GraphNode] = []
        for node in self._nodes.values():
            if node.name in entry_names or node.type in entry_types:
                continue
            # Exclude dunder methods — called implicitly (constructors, operators)
            bare = node.name.rsplit(".", 1)[-1] if "." in node.name else node.name
            if bare.startswith("__") and bare.endswith("__"):
                continue
            if exclude_tests and _is_test_file(node.file_path):
                continue
            if exclude_framework and any(bare.startswith(p) for p in FRAMEWORK_DEAD_CODE_PATTERNS):
                continue
            # Skip @property methods — accessed as attributes, not tracked as calls
            decorators = node.properties.get("decorators", [])
            if "property" in decorators:
                continue
            incoming = self._incoming_edges.get(node.id, [])
            if not incoming:
                if "." in node.name and self._is_polymorphic_override(node):
                    continue
                if self._is_nested_in_override(node):
                    continue
                dead.append(node)
        return dead

    def _is_polymorphic_override(self, node: GraphNode) -> bool:
        """Check if a method overrides a parent class method that is called polymorphically.

        Returns True if:
        - The parent class has the same method AND that method has incoming edges (called polymorphically)
        - OR the parent method is decorated with @abstractmethod
        """
        parts = node.name.rsplit(".", 1)
        if len(parts) != 2:
            return False
        class_name, method_name = parts

        # Find the class node (prefer same file as the method)
        class_node_ids = self._nodes_by_name.get(class_name, set())
        class_node = None
        for nid in class_node_ids:
            n = self._nodes.get(nid)
            if n and n.type == "class":
                if n.file_path == node.file_path:
                    class_node = n
                    break
                if class_node is None:
                    class_node = n  # fallback to any class with this name
        if class_node is None:
            return False

        # BFS up inheritance chain via "inherits" edges (max 5 levels)
        visited: Set[str] = {class_node.id}
        queue: deque = deque([(class_node.id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= 5:
                continue
            for edge in self._outgoing_edges.get(current_id, []):
                if edge.edge_type != "inherits":
                    continue
                parent_id = edge.target_id
                if parent_id in visited:
                    continue
                visited.add(parent_id)

                parent_node = self._nodes.get(parent_id)
                if parent_node is None:
                    continue

                # Look for ParentClass.method_name in the graph
                parent_method_name = f"{parent_node.name}.{method_name}"
                parent_method_ids = self._nodes_by_name.get(parent_method_name, set())
                for pm_id in parent_method_ids:
                    pm = self._nodes.get(pm_id)
                    if pm is None:
                        continue
                    # Check if parent method is abstract
                    decorators = pm.properties.get("decorators", [])
                    if "abstractmethod" in decorators:
                        return True
                    # Check if parent method has incoming edges (called polymorphically)
                    if self._incoming_edges.get(pm_id):
                        return True

                queue.append((parent_id, depth + 1))

        return False

    def _is_nested_in_override(self, node: GraphNode) -> bool:
        """Check if a node is a nested function inside a method that is not dead.

        Returns True if:
        - The node name has 2+ dots (nested function pattern like Class.method.helper)
        - The parent method exists and either has incoming edges or is a polymorphic override
        """
        dot_count = node.name.count(".")
        if dot_count < 2:
            return False
        # Strip last component to get parent method name
        parent_name = node.name.rsplit(".", 1)[0]
        parent_ids = self._nodes_by_name.get(parent_name, set())
        for pid in parent_ids:
            parent = self._nodes.get(pid)
            if parent is None:
                continue
            # Parent has incoming edges — not dead
            if self._incoming_edges.get(pid):
                return True
            # Parent is a polymorphic override
            if "." in parent.name and self._is_polymorphic_override(parent):
                return True
        return False

    def is_reachable(
        self,
        source_id: str,
        target_id: str,
        edge_types: Optional[List[str]] = None,
        max_depth: int = 10,
    ) -> bool:
        """Check if target is reachable from source via directed edges."""
        if source_id == target_id:
            return True

        visited: Set[str] = {source_id}
        queue: deque = deque([(source_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self.get_outgoing_edges(current_id):
                if edge_types and edge.edge_type not in edge_types:
                    continue
                if edge.target_id == target_id:
                    return True
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    queue.append((edge.target_id, depth + 1))

        return False

    def find_path(
        self,
        source_id: str,
        target_id: str,
        edge_types: Optional[List[str]] = None,
        max_depth: int = 10,
    ) -> Optional[List[str]]:
        """Find shortest path from source to target. Returns list of node IDs, or None."""
        if source_id == target_id:
            return [source_id]

        visited: Set[str] = {source_id}
        parent: Dict[str, str] = {}
        queue: deque = deque([(source_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self.get_outgoing_edges(current_id):
                if edge_types and edge.edge_type not in edge_types:
                    continue
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    parent[edge.target_id] = current_id
                    if edge.target_id == target_id:
                        path = [target_id]
                        cur = target_id
                        while cur in parent:
                            cur = parent[cur]
                            path.append(cur)
                        return list(reversed(path))
                    queue.append((edge.target_id, depth + 1))

        return None

    def find_cycles(self, exclude_tests: bool = True) -> List[List[str]]:
        """Find circular file-level dependencies using DFS.

        Args:
            exclude_tests: Skip edges involving test files.

        Returns list of cycles, each cycle is a list of file paths.
        """
        # Build file-level adjacency
        file_adj: Dict[str, Set[str]] = defaultdict(set)
        for edge_list in self._outgoing_edges.values():
            for edge in edge_list:
                src = self._nodes.get(edge.source_id)
                tgt = self._nodes.get(edge.target_id)
                if src and tgt and src.file_path != tgt.file_path:
                    if exclude_tests and (_is_test_file(src.file_path) or _is_test_file(tgt.file_path)):
                        continue
                    file_adj[src.file_path].add(tgt.file_path)

        # Iterative DFS-based cycle detection (avoids recursion limit on large projects)
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = defaultdict(int)
        path: List[str] = []
        cycles: List[List[str]] = []

        all_files: Set[str] = set()
        for node in self._nodes.values():
            if exclude_tests and _is_test_file(node.file_path):
                continue
            all_files.add(node.file_path)

        for start in sorted(all_files):
            if color[start] != WHITE:
                continue
            stack = [(start, iter(sorted(file_adj.get(start, set()))))]
            color[start] = GRAY
            path.append(start)

            while stack:
                current, neighbors = stack[-1]
                advanced = False
                for neighbor in neighbors:
                    if color[neighbor] == GRAY:
                        idx = path.index(neighbor)
                        cycles.append(path[idx:] + [neighbor])
                    elif color[neighbor] == WHITE:
                        color[neighbor] = GRAY
                        path.append(neighbor)
                        stack.append((neighbor, iter(sorted(file_adj.get(neighbor, set())))))
                        advanced = True
                        break
                if not advanced:
                    path.pop()
                    color[current] = BLACK
                    stack.pop()

        # Normalize, deduplicate, and filter superset cycles
        seen: Set[Tuple[str, ...]] = set()
        unique: List[Tuple[str, ...]] = []
        for cycle in cycles:
            # Remove trailing duplicate (A->B->A => [A, B])
            core = cycle[:-1]
            # Rotate to start with lexicographically smallest file
            if core:
                min_idx = core.index(min(core))
                core = core[min_idx:] + core[:min_idx]
            canonical = tuple(core)
            if canonical not in seen:
                seen.add(canonical)
                unique.append(canonical)

        # Filter supersets: drop any cycle whose node set is a strict superset
        # of another cycle's node set
        node_sets = [frozenset(c) for c in unique]
        minimal: List[List[str]] = []
        for i, cycle in enumerate(unique):
            is_superset = False
            for j, other in enumerate(unique):
                if i != j and node_sets[i] > node_sets[j]:
                    is_superset = True
                    break
            if not is_superset:
                # Re-add trailing node to match existing output format
                minimal.append(list(cycle) + [cycle[0]])

        return minimal

    def compute_hash(self) -> str:
        """Compute a deterministic hash of the entire graph.

        Sorts all nodes as "{id}:{type}:{name}" and edges as
        "{source}->{target}:{type}", joins with "|", SHA256[:16].
        """
        node_strs = sorted(
            f"{n.id}:{n.type}:{n.name}" for n in self._nodes.values()
        )
        edge_strs = []
        for edges in self._outgoing_edges.values():
            for e in edges:
                edge_strs.append(f"{e.source_id}->{e.target_id}:{e.edge_type}")
        edge_strs.sort()

        combined = "|".join(node_strs + edge_strs)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def snapshot(self) -> "LiquidGraph":
        """Deep copy the entire graph into a new LiquidGraph instance."""
        new_graph = LiquidGraph()
        new_graph._nodes = {k: copy.deepcopy(v) for k, v in self._nodes.items()}
        new_graph._nodes_by_file = defaultdict(
            set, {k: set(v) for k, v in self._nodes_by_file.items()}
        )
        new_graph._nodes_by_type = defaultdict(
            set, {k: set(v) for k, v in self._nodes_by_type.items()}
        )
        new_graph._nodes_by_name = defaultdict(
            set, {k: set(v) for k, v in self._nodes_by_name.items()}
        )
        new_graph._outgoing_edges = defaultdict(
            list, {k: copy.deepcopy(v) for k, v in self._outgoing_edges.items()}
        )
        new_graph._incoming_edges = defaultdict(
            list, {k: copy.deepcopy(v) for k, v in self._incoming_edges.items()}
        )
        return new_graph

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(edges) for edges in self._outgoing_edges.values())

    def __repr__(self) -> str:
        return f"LiquidGraph(nodes={self.node_count}, edges={self.edge_count})"
