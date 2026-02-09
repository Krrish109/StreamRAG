#!/usr/bin/env python3
"""PreToolUse hook: injects StreamRAG context when reading a file.

Triggered on Read. Sends request to daemon for fast in-memory lookup.
Falls back to direct graph loading if daemon is unavailable.
"""

import json
import os
import sys
import signal

# Timeout safety: 2 seconds max (SIGALRM is Unix-only)
if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(0))
    signal.alarm(2)

# Add plugin root to Python path
PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT")
if PLUGIN_ROOT:
    parent_dir = os.path.dirname(PLUGIN_ROOT)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    if PLUGIN_ROOT not in sys.path:
        sys.path.insert(0, PLUGIN_ROOT)

try:
    from streamrag.models import SUPPORTED_EXTENSIONS
except ImportError as e:
    print(json.dumps({
        "systemMessage": f"[StreamRAG] Plugin import failed: {e}. Context injection disabled."
    }), file=sys.stdout)
    sys.exit(0)


def _fallback_read_context(input_data, file_path):
    """Original logic: load graph from disk and build context."""
    from streamrag.storage.memory import load_project_state, load_state

    project_path = input_data.get("project_path", os.getcwd())
    bridge = load_project_state(project_path)
    if bridge is None:
        bridge = load_state(input_data.get("session_id", "default"))
    if bridge is None:
        return {
            "systemMessage": "[StreamRAG] No code graph yet. It will initialize on your first file edit."
        }

    nodes = bridge.graph.get_nodes_by_file(file_path)
    if not nodes:
        for fp in set(n.file_path for n in bridge.graph._nodes.values()):
            if fp.endswith(file_path) or file_path.endswith(fp) or file_path in fp:
                nodes = bridge.graph.get_nodes_by_file(fp)
                file_path = fp
                break

    if not nodes:
        return {}

    if hasattr(bridge, '_hierarchical') and bridge._hierarchical:
        bridge._hierarchical.access_file(file_path)

    budget = int(os.environ.get("STREAMRAG_CONTEXT_BUDGET", "1000"))
    try:
        from streamrag.agent.context_builder import get_context_for_file, format_rich_context
        context = get_context_for_file(bridge, file_path)
        msg = format_rich_context(context, max_chars=budget)
    except Exception:
        basename = os.path.basename(file_path)
        entity_count = len([n for n in nodes if n.type in ("function", "class")])
        msg = f"[StreamRAG] {basename}: {entity_count} entities"

    return {"systemMessage": msg}


def main():
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Read":
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    if not any(file_path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        print(json.dumps({}), file=sys.stdout)
        sys.exit(0)

    # Fast path: daemon
    project_path = input_data.get("project_path", os.getcwd())
    try:
        from streamrag.daemon_client import ensure_daemon, send_request
        if ensure_daemon(project_path):
            response = send_request(project_path, {
                "cmd": "get_read_context",
                "file_path": file_path,
                "project_path": project_path,
                "session_id": input_data.get("session_id", "default"),
            }, timeout=1.5)
            if response is not None:
                print(json.dumps(response), file=sys.stdout)
                sys.exit(0)
    except Exception:
        pass

    # Fallback: direct graph loading
    result = _fallback_read_context(input_data, file_path)
    print(json.dumps(result), file=sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
