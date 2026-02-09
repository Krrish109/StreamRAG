"""Build context from graph state for Claude."""

import os
from typing import Dict, List, Optional

from streamrag.bridge import DeltaGraphBridge
from streamrag.graph import LiquidGraph


def get_context_for_file(bridge: DeltaGraphBridge, file_path: str) -> Dict:
    """Get graph context for a specific file."""
    nodes = bridge.graph.get_nodes_by_file(file_path)
    entities = []
    for node in nodes:
        outgoing = bridge.graph.get_outgoing_edges(node.id)
        incoming = bridge.graph.get_incoming_edges(node.id)

        entities.append({
            "name": node.name,
            "type": node.type,
            "line_start": node.line_start,
            "line_end": node.line_end,
            "lines": f"{node.line_start}-{node.line_end}",
            "params": node.properties.get("params", []),
            "type_refs": node.properties.get("type_refs", []),
            "calls_out": [
                {"target": bridge.graph.get_node(e.target_id).name if bridge.graph.get_node(e.target_id) else e.target_id,
                 "type": e.edge_type,
                 "confidence": e.properties.get("confidence", ""),
                 "target_file": (bridge.graph.get_node(e.target_id).file_path if bridge.graph.get_node(e.target_id) else "")}
                for e in outgoing
            ],
            "called_by": [
                {"source": bridge.graph.get_node(e.source_id).name if bridge.graph.get_node(e.source_id) else e.source_id,
                 "type": e.edge_type,
                 "confidence": e.properties.get("confidence", ""),
                 "source_file": (bridge.graph.get_node(e.source_id).file_path if bridge.graph.get_node(e.source_id) else "")}
                for e in incoming
            ],
        })

    affected = set()
    for node in nodes:
        for name_dep in bridge.get_affected_files(file_path, node.name):
            affected.add(name_dep)

    return {
        "file_path": file_path,
        "entity_count": len(entities),
        "entities": entities,
        "affected_files": list(affected),
    }


def get_entity_signature(node_data: Dict) -> str:
    """Reconstruct a function/class signature from node properties.

    Returns e.g. "def process_change(change) -> List[GraphOperation]  L153-318"
    """
    name = node_data["name"]
    etype = node_data["type"]
    params = node_data.get("params", [])
    type_refs = node_data.get("type_refs", [])
    lines = node_data.get("lines", "")

    if etype == "function":
        param_str = ", ".join(params) if params else ""
        sig = f"def {name}({param_str})"
    elif etype == "class":
        sig = f"class {name}"
    elif etype == "import":
        sig = f"import {name}"
    else:
        sig = name

    if lines:
        sig += f"  L{lines}"
    return sig


def _format_affected_with_grouping(affected: List[str]) -> str:
    """Format affected files, collapsing directories with 3+ files.

    When affected files share a common directory prefix, collapse them:
      llm/providers/ (4 files), server.py, code_fixer.py
    """
    if not affected:
        return ""

    # Group by parent directory
    from collections import defaultdict
    dir_groups: Dict[str, List[str]] = defaultdict(list)
    for f in affected:
        parent = os.path.dirname(f)
        dir_groups[parent].append(f)

    parts = []
    shown_files = set()
    # Sort directories by number of files (largest groups first)
    for parent, files in sorted(dir_groups.items(), key=lambda x: -len(x[1])):
        if len(files) >= 3 and parent:
            # Collapse directory
            dir_display = parent.rstrip("/") + "/"
            parts.append(f"{dir_display} ({len(files)} files)")
            shown_files.update(files)
        else:
            for f in files:
                if f not in shown_files:
                    parts.append(os.path.basename(f))
                    shown_files.add(f)

    if len(parts) <= 5:
        return ", ".join(parts)
    return ", ".join(parts[:4]) + f" +{len(parts)-4} more"


def format_rich_context(context: Dict, max_chars: int = 1000) -> str:
    """Budget-aware multi-line context formatter with cross-file relationships.

    Produces output like:
    [StreamRAG] bridge.py: 8fn 2cls
    Key: class DeltaGraphBridge L15, def process_change L153, def _extract L420
    Called by: process_change <-- daemon.py:handle_process_change, on_file_change.py:handle_change
      _extract <-- process_change (same file)
    Deps: graph.py, extractor.py, models.py
    Affected: daemon.py, on_file_change.py, pre_read_context.py +1 more
    """
    file_path = context["file_path"]
    basename = os.path.basename(file_path)
    entities = context.get("entities", [])
    affected = context.get("affected_files", [])

    # Count by type
    type_counts: Dict[str, int] = {}
    for e in entities:
        t = e["type"]
        if t in ("function", "class"):
            type_counts[t] = type_counts.get(t, 0) + 1

    count_parts = []
    for t in ("function", "class"):
        c = type_counts.get(t, 0)
        if c > 0:
            abbrev = "fn" if t == "function" else "cls"
            count_parts.append(f"{c}{abbrev}")

    # Header line (10% of budget)
    header = f"[StreamRAG] {basename}: {' '.join(count_parts)}" if count_parts else f"[StreamRAG] {basename}"
    lines = [header]
    budget = max_chars - len(header) - 2  # reserve for newlines

    # Key entities (20% of budget): top functions/classes with line numbers
    key_budget = int(budget * 0.2)
    if key_budget > 20:
        # Score entities: classes first, then by cross-file caller count, then line number
        key_entities = []
        for e in entities:
            if e["type"] not in ("function", "class"):
                continue
            cross_caller_count = sum(
                1 for cb in e.get("called_by", [])
                if cb.get("source_file", "") and cb["source_file"] != file_path
            )
            # Classes get priority (sort key: type_priority desc, cross_callers desc, line asc)
            type_priority = 1 if e["type"] == "class" else 0
            key_entities.append((type_priority, cross_caller_count, e))

        key_entities.sort(key=lambda x: (-x[0], -x[1], x[2].get("line_start", 0)))

        if key_entities:
            key_parts = []
            chars_used = 5  # "Key: " prefix
            for _, _, e in key_entities[:5]:
                if e["type"] == "class":
                    part = f"class {e['name']} L{e.get('line_start', '?')}"
                else:
                    part = f"def {e['name']} L{e.get('line_start', '?')}"
                if chars_used + len(part) + 2 <= key_budget:
                    key_parts.append(part)
                    chars_used += len(part) + 2  # ", " separator

            if key_parts:
                key_line = f"Key: {', '.join(key_parts)}"
                lines.append(key_line)
                budget -= len(key_line) + 1

    # Cross-file callers (30% of budget)
    caller_budget = int(budget * 0.35)
    if caller_budget > 20:
        # Collect cross-file callers per entity, sorted by caller count
        entity_callers: List[tuple] = []  # (entity_name, [(source_basename, source_name), ...])
        for e in entities:
            if e["type"] not in ("function", "class"):
                continue
            cross_callers = []
            same_callers = []
            for cb in e.get("called_by", []):
                src_file = cb.get("source_file", "")
                src_name = cb.get("source", "")
                if not src_file or not src_name:
                    continue
                if src_file == file_path:
                    same_callers.append(src_name)
                else:
                    cross_callers.append((os.path.basename(src_file), src_name))
            if cross_callers or same_callers:
                entity_callers.append((e["name"], cross_callers, same_callers))

        # Sort by most cross-file callers first
        entity_callers.sort(key=lambda x: len(x[1]), reverse=True)

        if entity_callers:
            caller_lines = []
            chars_used = 0
            for ename, cross, same in entity_callers[:3]:
                parts_list = []
                for src_base, src_name in cross[:3]:
                    parts_list.append(f"{src_base}:{src_name}")
                if len(cross) > 3:
                    parts_list.append(f"+{len(cross)-3} more")
                for sname in same[:2]:
                    parts_list.append(f"{sname} (same file)")
                if parts_list:
                    line = f"  {ename} <-- {', '.join(parts_list)}"
                    if chars_used + len(line) + 1 <= caller_budget:
                        caller_lines.append(line)
                        chars_used += len(line) + 1

            if caller_lines:
                lines.append("Called by:")
                lines.extend(caller_lines)
                budget -= chars_used + len("Called by:") + 2

    # Dependencies (20% of budget): unique files called out to
    dep_budget = int(max_chars * 0.2)
    if dep_budget > 15 and budget > 15:
        dep_files = set()
        for e in entities:
            for co in e.get("calls_out", []):
                tf = co.get("target_file", "")
                if tf and tf != file_path:
                    dep_files.add(os.path.basename(tf))
        if dep_files:
            sorted_deps = sorted(dep_files)
            if len(sorted_deps) <= 5:
                dep_str = ", ".join(sorted_deps)
            else:
                dep_str = ", ".join(sorted_deps[:4]) + f" +{len(sorted_deps)-4} more"
            dep_line = f"Deps: {dep_str}"
            if len(dep_line) <= dep_budget and len(dep_line) <= budget:
                lines.append(dep_line)
                budget -= len(dep_line) + 1

    # Affected files with module path grouping (20% of budget)
    aff_budget = int(max_chars * 0.2)
    if aff_budget > 15 and budget > 15 and affected:
        aff_str = _format_affected_with_grouping(affected)
        aff_line = f"Affected: {aff_str}"
        if len(aff_line) <= aff_budget and len(aff_line) <= budget:
            lines.append(aff_line)

    return "\n".join(lines)


def format_graph_summary(bridge: DeltaGraphBridge) -> str:
    """Format a human-readable graph summary."""
    lines = [
        f"Code Graph: {bridge.graph.node_count} entities, {bridge.graph.edge_count} edges",
    ]

    files = set()
    type_counts: Dict[str, int] = {}
    for node in bridge.graph._nodes.values():
        files.add(node.file_path)
        type_counts[node.type] = type_counts.get(node.type, 0) + 1

    lines.append(f"Files: {len(files)}")
    for t, c in sorted(type_counts.items()):
        lines.append(f"  {t}: {c}")

    return "\n".join(lines)
