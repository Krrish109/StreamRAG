#!/usr/bin/env python3
"""Query the StreamRAG code graph.

Usage:
    query_graph.py callers <name>          — Who calls/imports/inherits this?
    query_graph.py callees <name>          — What does this call/import/inherit?
    query_graph.py deps <file>             — Forward file dependencies
    query_graph.py rdeps <file>            — Reverse file dependencies
    query_graph.py file <file>             — All entities + relationships in a file
    query_graph.py entity <name>           — Full detail for an entity
    query_graph.py impact <file> [name]    — Impact analysis (affected files)
    query_graph.py dead                    — Dead code detection
    query_graph.py path <src> <dst>        — Shortest dependency path
    query_graph.py search <regex>          — Regex entity search
    query_graph.py cycles                  — Circular file dependencies
    query_graph.py exports <file>          — Module exports (__all__ or top-level)
    query_graph.py stats                   — Resolution statistics
    query_graph.py ask <question>          — Natural language query
    query_graph.py visualize <file>        — Mermaid/DOT dependency diagram
    query_graph.py summary                 — Architecture overview
"""

import os
import sys

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from streamrag.storage.memory import load_state, load_project_state


def _load_bridge():
    """Load the bridge from project or session state."""
    # Try project-level first (from CWD)
    bridge = load_project_state(os.getcwd())
    if bridge is not None:
        return bridge
    # Fall back to session state
    bridge = load_state("default")
    if bridge is not None:
        return bridge
    print("No StreamRAG graph found. Run init_graph.py or edit a file first.")
    sys.exit(1)


def _resolve_name(bridge, name):
    """Resolve a name to graph nodes using progressive matching.

    1. Exact name match
    2. Suffix match (e.g., "foo" matches "Bar.foo")
    3. Regex fallback
    """
    # 1. Exact match
    nodes = bridge.graph.query(name=name)
    if nodes:
        return nodes

    # 2. Suffix match
    suffix = f".{name}"
    matches = [n for n in bridge.graph._nodes.values() if n.name.endswith(suffix)]
    if matches:
        return matches

    # 3. Regex fallback
    try:
        matches = bridge.graph.query_regex(name)
        if matches:
            return matches
    except Exception:
        pass

    return []


def _format_node(node):
    """Format a node for display."""
    return f"{node.type:10s} {node.name:40s} {node.file_path}:{node.line_start}-{node.line_end}"


def _format_edge(bridge, edge, direction="out", show_confidence=False):
    """Format an edge for display."""
    conf = ""
    if show_confidence:
        c = edge.properties.get("confidence", "")
        if c:
            conf = f" [{c}]"
    if direction == "out":
        target = bridge.graph.get_node(edge.target_id)
        name = target.name if target else edge.target_id
        file_info = f" ({target.file_path}:{target.line_start})" if target else ""
        return f"  --{edge.edge_type}--> {name}{file_info}{conf}"
    else:
        source = bridge.graph.get_node(edge.source_id)
        name = source.name if source else edge.source_id
        file_info = f" ({source.file_path}:{source.line_start})" if source else ""
        return f"  <--{edge.edge_type}-- {name}{file_info}{conf}"


def cmd_callers(bridge, args):
    """Show all incoming edges (who calls/imports/inherits this?)."""
    if not args:
        print("Usage: query_graph.py callers <name>")
        return
    high_only = "--high-confidence" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print("Usage: query_graph.py callers <name>")
        return
    name = args[0]
    nodes = _resolve_name(bridge, name)
    if not nodes:
        print(f"No entity found matching '{name}'")
        return
    for node in nodes:
        print(f"\nCallers of {node.name} ({node.file_path}:{node.line_start}):")
        incoming = bridge.graph.get_incoming_edges(node.id)
        if high_only:
            incoming = [e for e in incoming if e.properties.get("confidence") == "high"]
        if not incoming:
            print("  (none)")
        for edge in incoming:
            print(_format_edge(bridge, edge, "in", show_confidence=True))


def cmd_callees(bridge, args):
    """Show all outgoing edges (what does this call?)."""
    if not args:
        print("Usage: query_graph.py callees <name>")
        return
    high_only = "--high-confidence" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print("Usage: query_graph.py callees <name>")
        return
    name = args[0]
    nodes = _resolve_name(bridge, name)
    if not nodes:
        print(f"No entity found matching '{name}'")
        return
    for node in nodes:
        print(f"\nCallees of {node.name} ({node.file_path}:{node.line_start}):")
        outgoing = bridge.graph.get_outgoing_edges(node.id)
        if high_only:
            outgoing = [e for e in outgoing if e.properties.get("confidence") == "high"]
        if not outgoing:
            print("  (none)")
        for edge in outgoing:
            print(_format_edge(bridge, edge, "out", show_confidence=True))


def cmd_deps(bridge, args):
    """Show forward file dependencies (what files does this file import/call into?)."""
    if not args:
        print("Usage: query_graph.py deps <file>")
        return
    file_path = args[0]
    nodes = bridge.graph.get_nodes_by_file(file_path)
    if not nodes:
        # Try partial match
        for fp in set(n.file_path for n in bridge.graph._nodes.values()):
            if fp.endswith(file_path) or file_path in fp:
                nodes = bridge.graph.get_nodes_by_file(fp)
                file_path = fp
                break
    if not nodes:
        print(f"No entities found in '{args[0]}'")
        return

    deps = set()
    for node in nodes:
        for edge in bridge.graph.get_outgoing_edges(node.id):
            target = bridge.graph.get_node(edge.target_id)
            if target and target.file_path != file_path:
                deps.add((target.file_path, edge.edge_type))

    print(f"\nForward dependencies of {file_path}:")
    if not deps:
        print("  (none)")
    for dep_file, edge_type in sorted(deps):
        print(f"  --> {dep_file} ({edge_type})")


def cmd_rdeps(bridge, args):
    """Show reverse file dependencies (what files depend on this file?)."""
    if not args:
        print("Usage: query_graph.py rdeps <file>")
        return
    file_path = args[0]
    nodes = bridge.graph.get_nodes_by_file(file_path)
    if not nodes:
        for fp in set(n.file_path for n in bridge.graph._nodes.values()):
            if fp.endswith(file_path) or file_path in fp:
                nodes = bridge.graph.get_nodes_by_file(fp)
                file_path = fp
                break
    if not nodes:
        print(f"No entities found in '{args[0]}'")
        return

    rdeps = set()
    for node in nodes:
        for edge in bridge.graph.get_incoming_edges(node.id):
            source = bridge.graph.get_node(edge.source_id)
            if source and source.file_path != file_path:
                rdeps.add((source.file_path, edge.edge_type))

    print(f"\nReverse dependencies of {file_path}:")
    if not rdeps:
        print("  (none)")
    for dep_file, edge_type in sorted(rdeps):
        print(f"  <-- {dep_file} ({edge_type})")


def cmd_file(bridge, args):
    """Show all entities and relationships in a file."""
    if not args:
        print("Usage: query_graph.py file <file>")
        return
    file_path = args[0]
    nodes = bridge.graph.get_nodes_by_file(file_path)
    if not nodes:
        for fp in set(n.file_path for n in bridge.graph._nodes.values()):
            if fp.endswith(file_path) or file_path in fp:
                nodes = bridge.graph.get_nodes_by_file(fp)
                file_path = fp
                break
    if not nodes:
        print(f"No entities found in '{args[0]}'")
        return

    print(f"\nEntities in {file_path} ({len(nodes)}):")
    for node in sorted(nodes, key=lambda n: n.line_start):
        print(f"  {_format_node(node)}")
        for edge in bridge.graph.get_outgoing_edges(node.id):
            print(f"    {_format_edge(bridge, edge, 'out')}")
        for edge in bridge.graph.get_incoming_edges(node.id):
            print(f"    {_format_edge(bridge, edge, 'in')}")


def cmd_entity(bridge, args):
    """Show full detail for an entity."""
    if not args:
        print("Usage: query_graph.py entity <name>")
        return
    name = args[0]
    nodes = _resolve_name(bridge, name)
    if not nodes:
        print(f"No entity found matching '{name}'")
        return

    for node in nodes:
        print(f"\n{'='*60}")
        print(f"Name:      {node.name}")
        print(f"Type:      {node.type}")
        print(f"File:      {node.file_path}")
        print(f"Lines:     {node.line_start}-{node.line_end}")
        print(f"ID:        {node.id}")
        for key, val in node.properties.items():
            if val:
                print(f"  {key}: {val}")

        outgoing = bridge.graph.get_outgoing_edges(node.id)
        if outgoing:
            print(f"\nOutgoing edges ({len(outgoing)}):")
            for edge in outgoing:
                print(_format_edge(bridge, edge, "out"))

        incoming = bridge.graph.get_incoming_edges(node.id)
        if incoming:
            print(f"\nIncoming edges ({len(incoming)}):")
            for edge in incoming:
                print(_format_edge(bridge, edge, "in"))


def cmd_impact(bridge, args):
    """Impact analysis: what files are affected by a change?"""
    if not args:
        print("Usage: query_graph.py impact <file> [name]")
        return
    file_path = args[0]
    entity_name = args[1] if len(args) > 1 else ""

    if not entity_name:
        # Use all entity names in the file
        nodes = bridge.graph.get_nodes_by_file(file_path)
        if not nodes:
            for fp in set(n.file_path for n in bridge.graph._nodes.values()):
                if fp.endswith(file_path) or file_path in fp:
                    nodes = bridge.graph.get_nodes_by_file(fp)
                    file_path = fp
                    break
        all_affected = set()
        for node in nodes:
            affected = bridge.get_affected_files(file_path, node.name)
            all_affected.update(affected)
    else:
        all_affected = set(bridge.get_affected_files(file_path, entity_name))

    print(f"\nFiles affected by changes to {file_path}" +
          (f":{entity_name}" if entity_name else "") + ":")
    if not all_affected:
        print("  (none)")
    for f in sorted(all_affected):
        print(f"  {f}")


def cmd_dead(bridge, args):
    """Dead code detection."""
    show_all = "--all" in args
    dead = bridge.graph.find_dead_code(
        exclude_tests=not show_all,
        exclude_framework=not show_all,
    )
    label = "all" if show_all else "source-only"
    print(f"\nPotentially dead code ({len(dead)} entities, {label}):")
    if not dead:
        print("  (none found)")
    for node in sorted(dead, key=lambda n: (n.file_path, n.line_start)):
        print(f"  {_format_node(node)}")


def cmd_path(bridge, args):
    """Find shortest dependency path between two entities."""
    if len(args) < 2:
        print("Usage: query_graph.py path <source> <target>")
        return
    src_name, dst_name = args[0], args[1]
    src_nodes = _resolve_name(bridge, src_name)
    dst_nodes = _resolve_name(bridge, dst_name)

    if not src_nodes:
        print(f"No entity found matching '{src_name}'")
        return
    if not dst_nodes:
        print(f"No entity found matching '{dst_name}'")
        return

    for src in src_nodes:
        for dst in dst_nodes:
            path = bridge.graph.find_path(src.id, dst.id)
            if path:
                print(f"\nPath from {src.name} to {dst.name}:")
                for i, nid in enumerate(path):
                    node = bridge.graph.get_node(nid)
                    prefix = "  " + ("-> " if i > 0 else "   ")
                    if node:
                        print(f"{prefix}{node.name} ({node.file_path}:{node.line_start})")
                    else:
                        print(f"{prefix}{nid} (unknown)")
                return

    print(f"No path found from '{src_name}' to '{dst_name}'")


def cmd_search(bridge, args):
    """Regex entity search."""
    if not args:
        print("Usage: query_graph.py search <regex>")
        return
    pattern = args[0]
    try:
        matches = bridge.graph.query_regex(pattern)
    except Exception as e:
        print(f"Invalid regex: {e}")
        return

    print(f"\nEntities matching '{pattern}' ({len(matches)}):")
    if not matches:
        print("  (none)")
    for node in sorted(matches, key=lambda n: (n.file_path, n.line_start)):
        print(f"  {_format_node(node)}")


def cmd_cycles(bridge, args):
    """Find circular file dependencies."""
    include_tests = "--include-tests" in args
    cycles = bridge.graph.find_cycles(exclude_tests=not include_tests)
    label = "all" if include_tests else "source-only"
    print(f"\nCircular file dependencies ({len(cycles)}, {label}):")
    if not cycles:
        print("  (none found)")
    for i, cycle in enumerate(cycles, 1):
        print(f"  Cycle {i}: {' -> '.join(cycle)}")


def cmd_exports(bridge, args):
    """Show module exports."""
    if not args:
        print("Usage: query_graph.py exports <file>")
        return
    file_path = args[0]
    # Try partial file match
    matched_path = file_path
    nodes = bridge.graph.get_nodes_by_file(file_path)
    if not nodes:
        for fp in set(n.file_path for n in bridge.graph._nodes.values()):
            if fp.endswith(file_path) or file_path in fp:
                matched_path = fp
                break
    exports = bridge.get_module_exports(matched_path)
    print(f"\nExports of {matched_path}:")
    if not exports:
        print("  (none)")
    for name in sorted(exports):
        print(f"  {name}")


def cmd_stats(bridge, args):
    """Show resolution statistics."""
    stats = getattr(bridge, '_resolution_stats', {})
    total = stats.get("total_attempted", 0)
    resolved = stats.get("resolved", 0)
    ambiguous = stats.get("ambiguous", 0)
    to_test = stats.get("to_test_file", 0)
    external_skipped = stats.get("external_skipped", 0)
    rate = (resolved / total * 100) if total > 0 else 0.0
    effective_total = total - external_skipped
    effective_rate = (resolved / effective_total * 100) if effective_total > 0 else 0.0

    print(f"\nResolution Statistics:")
    print(f"  Total attempted:    {total}")
    print(f"  External skipped:   {external_skipped}")
    print(f"  Resolved:           {resolved} ({rate:.1f}%)")
    print(f"  Effective rate:     {resolved}/{effective_total} ({effective_rate:.1f}%)")
    print(f"  Ambiguous:          {ambiguous}")
    print(f"  Resolved to test:   {to_test}")
    print(f"\n  Graph: {bridge.graph.node_count} nodes, {bridge.graph.edge_count} edges")
    files = set(n.file_path for n in bridge.graph._nodes.values())
    print(f"  Files tracked:      {len(files)}")


def cmd_ask(bridge, args):
    """Natural language query — delegates to smart_query."""
    if not args:
        print("Usage: query_graph.py ask <question>")
        return
    query = " ".join(args)
    from streamrag.smart_query import execute_query
    result = execute_query(bridge, query)
    print(result)


def cmd_visualize(bridge, args):
    """Generate Mermaid or DOT dependency diagram."""
    fmt = "mermaid"
    viz_type = "file"
    depth = 2
    target = None

    # Parse args
    i = 0
    positional = []
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            viz_type = args[i + 1]
            i += 2
        elif args[i] == "--depth" and i + 1 < len(args):
            try:
                depth = int(args[i + 1])
            except ValueError:
                print(f"Error: --depth must be a number, got '{args[i + 1]}'")
                return
            i += 2
        else:
            positional.append(args[i])
            i += 1

    if positional:
        target = positional[0]

    if viz_type == "file":
        _visualize_file_deps(bridge, target, fmt, depth)
    elif viz_type == "entity":
        _visualize_call_graph(bridge, target, fmt, depth)
    elif viz_type == "inheritance":
        _visualize_inheritance(bridge, target, fmt)
    else:
        print(f"Unknown visualization type: {viz_type}. Use: file, entity, inheritance")


def _sanitize_id(name):
    """Make a name safe for Mermaid/DOT node IDs."""
    return name.replace(".", "_").replace("/", "_").replace("-", "_").replace(" ", "_")


def _visualize_file_deps(bridge, target, fmt, depth):
    """File-level dependency graph."""
    # Collect all file-level edges
    file_edges = set()
    files = set()
    for node in bridge.graph._nodes.values():
        files.add(node.file_path)
        for edge in bridge.graph.get_outgoing_edges(node.id):
            tgt = bridge.graph.get_node(edge.target_id)
            if tgt and tgt.file_path != node.file_path:
                file_edges.add((node.file_path, tgt.file_path))

    if target:
        # Filter to files within `depth` hops of target
        matched = None
        for f in files:
            if f == target or f.endswith(target) or target in f:
                matched = f
                break
        if not matched:
            print(f"File '{target}' not found in graph.")
            return
        reachable = _bfs_files(matched, file_edges, depth)
        file_edges = {(s, t) for s, t in file_edges if s in reachable and t in reachable}
        files = reachable

    if fmt == "mermaid":
        print("```mermaid")
        print("graph LR")
        for f in sorted(files):
            sid = _sanitize_id(f)
            base = os.path.basename(f)
            print(f'    {sid}["{base}"]')
        for src, tgt in sorted(file_edges):
            print(f"    {_sanitize_id(src)} --> {_sanitize_id(tgt)}")
        print("```")
    elif fmt == "dot":
        print("digraph file_deps {")
        print("  rankdir=LR;")
        for src, tgt in sorted(file_edges):
            print(f'  "{os.path.basename(src)}" -> "{os.path.basename(tgt)}";')
        print("}")
    else:
        print(f"Unknown format: {fmt}. Use: mermaid, dot")


def _visualize_call_graph(bridge, target, fmt, depth):
    """Entity-level call graph."""
    if not target:
        print("Usage: query_graph.py visualize <entity> --type entity")
        return
    nodes = _resolve_name(bridge, target)
    if not nodes:
        print(f"No entity found matching '{target}'")
        return

    # BFS from entity nodes
    visited = set()
    edges = []
    queue = [(n.id, 0) for n in nodes]
    while queue:
        nid, d = queue.pop(0)
        if nid in visited or d > depth:
            continue
        visited.add(nid)
        for edge in bridge.graph.get_outgoing_edges(nid):
            tgt = bridge.graph.get_node(edge.target_id)
            if tgt:
                edges.append((nid, edge.target_id, edge.edge_type))
                if edge.target_id not in visited:
                    queue.append((edge.target_id, d + 1))

    if fmt == "mermaid":
        print("```mermaid")
        print("graph LR")
        for nid in visited:
            node = bridge.graph.get_node(nid)
            if node:
                sid = _sanitize_id(nid)
                print(f'    {sid}["{node.name}"]')
        for src, tgt, etype in edges:
            src_s = _sanitize_id(src)
            tgt_s = _sanitize_id(tgt)
            print(f"    {src_s} -->|{etype}| {tgt_s}")
        print("```")
    elif fmt == "dot":
        print("digraph call_graph {")
        print("  rankdir=LR;")
        for src, tgt, etype in edges:
            sn = bridge.graph.get_node(src)
            tn = bridge.graph.get_node(tgt)
            sl = sn.name if sn else src
            tl = tn.name if tn else tgt
            print(f'  "{sl}" -> "{tl}" [label="{etype}"];')
        print("}")


def _visualize_inheritance(bridge, target, fmt):
    """Inheritance hierarchy."""
    edges = []
    for node in bridge.graph._nodes.values():
        for edge in bridge.graph.get_outgoing_edges(node.id):
            if edge.edge_type == "inherits":
                tgt = bridge.graph.get_node(edge.target_id)
                if tgt:
                    edges.append((node.name, tgt.name))

    if target:
        # Filter to edges involving target
        edges = [(s, t) for s, t in edges if target in s or target in t]

    if not edges:
        print("No inheritance relationships found.")
        return

    if fmt == "mermaid":
        print("```mermaid")
        print("graph BT")
        for child, parent in sorted(edges):
            print(f'    {_sanitize_id(child)}["{child}"] --> {_sanitize_id(parent)}["{parent}"]')
        print("```")
    elif fmt == "dot":
        print("digraph inheritance {")
        print("  rankdir=BT;")
        for child, parent in sorted(edges):
            print(f'  "{child}" -> "{parent}";')
        print("}")


def _bfs_files(start, file_edges, max_depth):
    """BFS to find files within max_depth hops."""
    # Build adjacency (both directions for reachability)
    adj = {}
    for src, tgt in file_edges:
        adj.setdefault(src, set()).add(tgt)
        adj.setdefault(tgt, set()).add(src)

    visited = {start}
    queue = [(start, 0)]
    while queue:
        f, d = queue.pop(0)
        if d >= max_depth:
            continue
        for neighbor in adj.get(f, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, d + 1))
    return visited


def cmd_summary(bridge, args):
    """Architecture overview: key classes, entry points, hot spots."""
    files = set()
    type_counts = {}
    for node in bridge.graph._nodes.values():
        files.add(node.file_path)
        type_counts[node.type] = type_counts.get(node.type, 0) + 1

    print(f"\nArchitecture Summary")
    print(f"{'='*50}")
    print(f"Entities: {bridge.graph.node_count}  Edges: {bridge.graph.edge_count}  Files: {len(files)}")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")

    # Key classes (by method count)
    class_methods = {}
    for node in bridge.graph._nodes.values():
        if "." in node.name and node.type == "function":
            cls_name = node.name.rsplit(".", 1)[0]
            class_methods[cls_name] = class_methods.get(cls_name, 0) + 1

    if class_methods:
        print(f"\nKey Classes (by method count, top 10):")
        for cls, count in sorted(class_methods.items(), key=lambda x: -x[1])[:10]:
            print(f"  {cls}: {count} methods")

    # Entry points (highest fan-in)
    fan_in = {}
    for node in bridge.graph._nodes.values():
        incoming = bridge.graph.get_incoming_edges(node.id)
        cross_file = [e for e in incoming
                      if bridge.graph.get_node(e.source_id) and
                      bridge.graph.get_node(e.source_id).file_path != node.file_path]
        if cross_file:
            fan_in[node.name] = len(cross_file)

    if fan_in:
        print(f"\nEntry Points (highest cross-file fan-in, top 10):")
        for name, count in sorted(fan_in.items(), key=lambda x: -x[1])[:10]:
            print(f"  {name}: {count} callers")

    # Core utilities (highest fan-out)
    fan_out = {}
    for node in bridge.graph._nodes.values():
        outgoing = bridge.graph.get_outgoing_edges(node.id)
        cross_file = [e for e in outgoing
                      if bridge.graph.get_node(e.target_id) and
                      bridge.graph.get_node(e.target_id).file_path != node.file_path]
        if cross_file:
            fan_out[node.name] = len(cross_file)

    if fan_out:
        print(f"\nCore Utilities (highest cross-file fan-out, top 10):")
        for name, count in sorted(fan_out.items(), key=lambda x: -x[1])[:10]:
            print(f"  {name}: {count} deps")

    # Hot spots (files with most cross-file edges)
    file_cross_edges = {}
    for node in bridge.graph._nodes.values():
        fp = node.file_path
        for edge in bridge.graph.get_outgoing_edges(node.id):
            tgt = bridge.graph.get_node(edge.target_id)
            if tgt and tgt.file_path != fp:
                file_cross_edges[fp] = file_cross_edges.get(fp, 0) + 1
        for edge in bridge.graph.get_incoming_edges(node.id):
            src = bridge.graph.get_node(edge.source_id)
            if src and src.file_path != fp:
                file_cross_edges[fp] = file_cross_edges.get(fp, 0) + 1

    if file_cross_edges:
        print(f"\nHot Spots (most cross-file edges, top 10):")
        for fp, count in sorted(file_cross_edges.items(), key=lambda x: -x[1])[:10]:
            print(f"  {os.path.basename(fp)}: {count} cross-file edges")


def cmd_daemon_start(bridge, args):
    """Start the StreamRAG daemon for the current project."""
    project_path = os.getcwd()
    if args:
        project_path = args[0]

    from streamrag.daemon_client import ensure_daemon, send_request
    if ensure_daemon(project_path):
        resp = send_request(project_path, {"cmd": "ping"}, timeout=2.0)
        if resp and resp.get("alive"):
            print(f"Daemon running: {resp.get('nodes', 0)} nodes, {resp.get('edges', 0)} edges")
        else:
            print("Daemon started (ping failed)")
    else:
        print("Failed to start daemon")


def cmd_daemon_stop(bridge, args):
    """Stop the StreamRAG daemon for the current project."""
    project_path = os.getcwd()
    if args:
        project_path = args[0]

    from streamrag.daemon_client import send_request, _is_daemon_alive
    if not _is_daemon_alive(project_path):
        print("Daemon is not running")
        return
    resp = send_request(project_path, {"cmd": "shutdown"}, timeout=5.0)
    if resp and resp.get("ok"):
        print("Daemon stopped")
    else:
        print("Shutdown sent (no confirmation)")


def cmd_daemon_status(bridge, args):
    """Check if the StreamRAG daemon is running."""
    project_path = os.getcwd()
    if args:
        project_path = args[0]

    from streamrag.daemon import get_socket_path, get_pid_path
    from streamrag.daemon_client import send_request, _is_daemon_alive

    pid_path = get_pid_path(project_path)
    sock_path = get_socket_path(project_path)

    if not _is_daemon_alive(project_path):
        print("Daemon: not running")
        return

    pid = "?"
    try:
        with open(pid_path, "r") as f:
            pid = f.read().strip()
    except Exception:
        pass

    resp = send_request(project_path, {"cmd": "ping"}, timeout=2.0)
    if resp and resp.get("alive"):
        print(f"Daemon: running (pid={pid})")
        print(f"  Socket: {sock_path}")
        print(f"  Graph: {resp.get('nodes', 0)} nodes, {resp.get('edges', 0)} edges")
    else:
        print(f"Daemon: pid={pid} but not responding")


COMMANDS = {
    "callers": cmd_callers,
    "callees": cmd_callees,
    "deps": cmd_deps,
    "rdeps": cmd_rdeps,
    "file": cmd_file,
    "entity": cmd_entity,
    "impact": cmd_impact,
    "dead": cmd_dead,
    "path": cmd_path,
    "search": cmd_search,
    "cycles": cmd_cycles,
    "exports": cmd_exports,
    "stats": cmd_stats,
    "ask": cmd_ask,
    "visualize": cmd_visualize,
    "summary": cmd_summary,
    "daemon-start": cmd_daemon_start,
    "daemon-stop": cmd_daemon_stop,
    "daemon-status": cmd_daemon_status,
}

# Commands that don't need a graph loaded
NO_GRAPH_COMMANDS = {"daemon-start", "daemon-stop", "daemon-status"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Available commands:", ", ".join(sorted(COMMANDS.keys())))
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd in NO_GRAPH_COMMANDS:
        COMMANDS[cmd](None, args)
    else:
        bridge = _load_bridge()
        COMMANDS[cmd](bridge, args)


if __name__ == "__main__":
    main()
