#!/usr/bin/env python3
"""Stop hook: injects graph summary for context preservation.

On session stop, gets compact summary from daemon (or falls back to direct
graph loading) and sends shutdown to daemon.
"""

import json
import os
import sys

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT")
if PLUGIN_ROOT:
    parent_dir = os.path.dirname(PLUGIN_ROOT)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    if PLUGIN_ROOT not in sys.path:
        sys.path.insert(0, PLUGIN_ROOT)

try:
    from streamrag.storage.memory import load_state, load_project_state
except ImportError:
    sys.exit(0)


def _fallback_compact_summary(input_data):
    """Original logic: load graph from disk and build summary."""
    session_id = input_data.get("session_id", "default")
    project_path = input_data.get("project_path", os.getcwd())

    bridge = load_project_state(project_path)
    if bridge is None:
        bridge = load_state(session_id)
    if bridge is None or bridge.graph.node_count == 0:
        return None

    files = set()
    all_nodes = bridge.graph.get_all_nodes()
    for node in all_nodes:
        files.add(node.file_path)

    entity_counts = {}
    for node in all_nodes:
        entity_counts[node.type] = entity_counts.get(node.type, 0) + 1

    lines = [
        f"StreamRAG Code Graph: {bridge.graph.node_count} entities, "
        f"{bridge.graph.edge_count} edges across {len(files)} files.",
    ]
    for etype, count in sorted(entity_counts.items()):
        lines.append(f"  {etype}: {count}")

    cross_file_edges = []
    for edge in bridge.graph.get_all_edges():
        src = bridge.graph.get_node(edge.source_id)
        tgt = bridge.graph.get_node(edge.target_id)
        if src and tgt and src.file_path != tgt.file_path:
            cross_file_edges.append(
                f"{src.file_path}:{src.name} -> {tgt.file_path}:{tgt.name}"
            )

    if cross_file_edges:
        lines.append(f"Cross-file deps ({len(cross_file_edges)}):")
        for dep in cross_file_edges[:10]:
            lines.append(f"  {dep}")

    return {"systemMessage": "\n".join(lines)}


def main():
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    project_path = input_data.get("project_path", os.getcwd())

    # Fast path: daemon
    try:
        from streamrag.daemon_client import send_request, _is_daemon_alive
        if _is_daemon_alive(project_path):
            response = send_request(project_path, {
                "cmd": "get_compact_summary",
                "session_id": input_data.get("session_id", "default"),
                "project_path": project_path,
            }, timeout=8.0)
            if response and response.get("systemMessage"):
                print(json.dumps(response), file=sys.stdout)
                # Shutdown daemon since session is ending
                send_request(project_path, {"cmd": "shutdown"}, timeout=5.0)
                sys.exit(0)

            # Shutdown daemon even if summary was empty
            send_request(project_path, {"cmd": "shutdown"}, timeout=5.0)
    except Exception:
        pass

    # Fallback: direct graph loading
    result = _fallback_compact_summary(input_data)
    if result:
        print(json.dumps(result), file=sys.stdout)

    sys.exit(0)


if __name__ == "__main__":
    main()
