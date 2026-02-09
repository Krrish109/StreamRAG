#!/usr/bin/env python3
"""PreToolUse hook: auto-executes StreamRAG queries for Explore/Grep relationship queries.

Triggered on Task (Explore) and Grep. Sends classification request to daemon
for fast in-memory query execution. Falls back to direct logic if daemon is
unavailable.
"""

import json
import os
import sys
import signal

# Timeout safety: 3 seconds max (SIGALRM is Unix-only)
if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(0))
    signal.alarm(3)

# Add plugin root to Python path
PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT")
if PLUGIN_ROOT:
    parent_dir = os.path.dirname(PLUGIN_ROOT)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    if PLUGIN_ROOT not in sys.path:
        sys.path.insert(0, PLUGIN_ROOT)

try:
    from streamrag.storage.memory import load_project_state, load_state
    from streamrag.classify import (
        classify_explore_prompt,
        classify_grep_pattern,
        build_command_str as _build_command_str,
        command_description as _command_description,
    )
except ImportError:
    sys.exit(0)


def _load_graph(input_data):
    project_path = input_data.get("project_path", os.getcwd())
    bridge = load_project_state(project_path)
    if bridge is None:
        bridge = load_state(input_data.get("session_id", "default"))
    if bridge is None or bridge.graph.node_count == 0:
        return None
    return bridge


MAX_OUTPUT_CHARS = 2000


def _execute_command(bridge, command, args):
    scripts_dir = os.path.join(
        os.environ.get("CLAUDE_PLUGIN_ROOT",
                       os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
    )
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from io import StringIO
    import contextlib

    try:
        if 'query_graph' in sys.modules:
            qg = sys.modules['query_graph']
        else:
            import query_graph as qg

        cmd_fn = qg.COMMANDS.get(command)
        if cmd_fn is None:
            return None

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_fn(bridge, args)

        output = buf.getvalue().strip()
        if not output:
            return None
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
        return output
    except Exception:
        return None


def _fallback_handle_task(input_data):
    """Original logic for Task/Explore classification."""
    tool_input = input_data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "")
    if subagent_type.lower() != "explore":
        return None

    prompt = tool_input.get("prompt", "")
    description = tool_input.get("description", "")
    if not prompt and not description:
        return None

    result = classify_explore_prompt(prompt) if prompt else None
    if result is None and description:
        result = classify_explore_prompt(description)
    if result is None:
        return None

    command, args = result
    bridge = _load_graph(input_data)
    if bridge is None:
        return None

    output = _execute_command(bridge, command, args)
    if output:
        return {"systemMessage": f"[StreamRAG] Graph context:\n{output}"}

    cmd_str = _build_command_str(command, args)
    return {
        "systemMessage": f"[StreamRAG] This query can be answered from the code graph.\nRun: {cmd_str}",
    }


def _fallback_handle_grep(input_data):
    """Original logic for Grep classification."""
    tool_input = input_data.get("tool_input", {})
    pattern = tool_input.get("pattern", "")
    if not pattern:
        return None

    result = classify_grep_pattern(pattern)
    if result is None:
        return None

    command, name = result
    bridge = _load_graph(input_data)
    if bridge is None:
        return None

    output = _execute_command(bridge, command, [name])
    if output:
        return {"systemMessage": f"[StreamRAG] Graph context:\n{output}"}

    cmd_str = _build_command_str(command, [name])
    return {"systemMessage": f"[StreamRAG Hint] Looking for {_command_description(command)} `{name}`? Try:\n  {cmd_str}"}


def main():
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name not in ("Task", "Grep"):
        sys.exit(0)

    # Fast path: daemon
    project_path = input_data.get("project_path", os.getcwd())
    try:
        from streamrag.daemon_client import ensure_daemon, send_request
        if ensure_daemon(project_path):
            response = send_request(project_path, {
                "cmd": "classify_query",
                "tool_name": tool_name,
                "tool_input": input_data.get("tool_input", {}),
                "project_path": project_path,
                "session_id": input_data.get("session_id", "default"),
            }, timeout=2.5)
            if response is not None:
                if response:  # Non-empty response
                    print(json.dumps(response), file=sys.stdout)
                sys.exit(0)
    except Exception:
        pass

    # Fallback: direct processing
    result = None
    if tool_name == "Task":
        result = _fallback_handle_task(input_data)
    elif tool_name == "Grep":
        result = _fallback_handle_grep(input_data)

    if result:
        print(json.dumps(result), file=sys.stdout)

    sys.exit(0)


if __name__ == "__main__":
    main()
