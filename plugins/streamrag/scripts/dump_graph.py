#!/usr/bin/env python3
"""Dump StreamRAG graph status (nodes, edges, files, cross-file deps) to stdout."""

import json
import os
import sys

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from streamrag.storage.memory import load_state, load_project_state, serialize_graph


def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else "default"

    # Try project-level state first (consistent with query_graph.py)
    bridge = load_project_state(os.getcwd())
    if bridge is None:
        bridge = load_state(session_id)
    if bridge is None:
        print("No StreamRAG graph found for this session.")
        print(f"Session ID: {session_id}")
        print("Run init_graph.py first to create one.")
        sys.exit(0)

    # Summary
    files = set()
    entity_counts = {}
    for node in bridge.graph._nodes.values():
        files.add(node.file_path)
        entity_counts[node.type] = entity_counts.get(node.type, 0) + 1

    print(f"StreamRAG Graph (session: {session_id})")
    print(f"  Nodes: {bridge.graph.node_count}")
    print(f"  Edges: {bridge.graph.edge_count}")
    print(f"  Files: {len(files)}")
    print(f"  Hash:  {bridge.graph.compute_hash()}")
    print()

    print("Entity types:")
    for etype, count in sorted(entity_counts.items()):
        print(f"  {etype}: {count}")
    print()

    print("Files:")
    for fp in sorted(files):
        file_nodes = bridge.graph.get_nodes_by_file(fp)
        print(f"  {fp} ({len(file_nodes)} entities)")
    print()

    # Cross-file edges
    cross = []
    for edges in bridge.graph._outgoing_edges.values():
        for edge in edges:
            src = bridge.graph.get_node(edge.source_id)
            tgt = bridge.graph.get_node(edge.target_id)
            if src and tgt and src.file_path != tgt.file_path:
                cross.append(f"  {src.file_path}:{src.name} --{edge.edge_type}--> {tgt.file_path}:{tgt.name}")

    if cross:
        print(f"Cross-file edges ({len(cross)}):")
        for c in cross[:20]:
            print(c)

    # Resolution stats
    if "--stats" in sys.argv:
        print()
        _print_resolution_stats(bridge)

    # Optionally dump full JSON
    if "--json" in sys.argv:
        data = serialize_graph(bridge)
        print(json.dumps(data, indent=2))


def _print_resolution_stats(bridge):
    """Print detailed call resolution statistics."""
    from collections import Counter

    # Collect all AST-extracted calls from node properties
    total_calls = []
    for node in bridge.graph._nodes.values():
        calls = node.properties.get("calls", [])
        total_calls.extend(calls)

    # Collect resolved call edges
    call_edges = []
    same_file_calls = 0
    cross_file_calls = 0
    for edges in bridge.graph._outgoing_edges.values():
        for edge in edges:
            if edge.edge_type == "calls":
                call_edges.append(edge)
                src = bridge.graph.get_node(edge.source_id)
                tgt = bridge.graph.get_node(edge.target_id)
                if src and tgt:
                    if src.file_path == tgt.file_path:
                        same_file_calls += 1
                    else:
                        cross_file_calls += 1

    # Find which calls are resolved (have a matching call edge from their entity)
    resolved_call_names = set()
    for edges in bridge.graph._outgoing_edges.values():
        for edge in edges:
            if edge.edge_type == "calls":
                tgt = bridge.graph.get_node(edge.target_id)
                if tgt:
                    resolved_call_names.add(tgt.name)

    # Count unresolved
    call_counts = Counter(total_calls)
    unresolved_counts = Counter()
    for call_name, count in call_counts.items():
        # A call is "unresolved" if no call edge targets a node with that name
        # (approximate — checks if any edge resolves to that name)
        if call_name not in resolved_call_names:
            # Also check suffix match
            found = False
            for rname in resolved_call_names:
                if rname.endswith(f".{call_name}") or call_name.endswith(f".{rname}"):
                    found = True
                    break
            if not found:
                unresolved_counts[call_name] = count

    total = len(total_calls)
    resolved = len(call_edges)
    unresolved_total = sum(unresolved_counts.values())
    rate = (resolved / total * 100) if total > 0 else 0

    print("Call Resolution Stats")
    print("=" * 50)
    print(f"  AST-extracted calls:  {total}")
    print(f"  Resolved call edges:  {resolved}")
    print(f"  Resolution rate:      {rate:.1f}%")
    print(f"  Same-file calls:      {same_file_calls}")
    print(f"  Cross-file calls:     {cross_file_calls}")
    print()

    if unresolved_counts:
        print(f"Top 20 unresolved call names ({unresolved_total} total):")
        for name, count in unresolved_counts.most_common(20):
            print(f"  {count:4d}x  {name}")
    print()

    # Edge type breakdown
    edge_types = Counter()
    for edges in bridge.graph._outgoing_edges.values():
        for edge in edges:
            edge_types[edge.edge_type] += 1
    print("Edge type breakdown:")
    for etype, count in edge_types.most_common():
        print(f"  {etype}: {count}")


if __name__ == "__main__":
    main()
