#!/usr/bin/env python3
"""UserPromptSubmit hook: injects graph-aware planning context before Claude plans.

When the user asks a code relationship question (e.g., "what breaks if I refactor X?"),
this hook provides relevant graph context BEFORE Claude starts exploring, so it can
go straight to the right files instead of grepping blindly.
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
    from streamrag.storage.memory import load_project_state, load_state
    from streamrag.classify import classify_explore_prompt
except ImportError:
    sys.exit(0)


MAX_OUTPUT_CHARS = 500


def _load_graph(input_data):
    project_path = input_data.get("project_path", os.getcwd())
    bridge = load_project_state(project_path)
    if bridge is None:
        bridge = load_state(input_data.get("session_id", "default"))
    if bridge is None or bridge.graph.node_count == 0:
        return None
    return bridge


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


def _scan_for_entities(bridge, prompt):
    """Scan user prompt for entity/file names mentioned in the graph."""
    words = set()
    # Split on whitespace and common punctuation
    import re
    tokens = re.split(r'[\s,;:?!`\'"()\[\]{}]+', prompt)
    for token in tokens:
        token = token.strip('./')
        if len(token) >= 2:
            words.add(token)

    matches = []

    # Check for entity name matches
    for word in words:
        node = bridge.graph.get_node_by_name(word)
        if node:
            # Get callers
            incoming = bridge.graph.get_incoming_edges(node.id)
            cross_callers = []
            for e in incoming:
                src = bridge.graph.get_node(e.source_id)
                if src and src.file_path != node.file_path:
                    cross_callers.append(f"{os.path.basename(src.file_path)}:{src.name}")

            # Get affected files
            affected = bridge.get_affected_files(node.file_path, node.name)

            info = f"{node.name} ({node.type}, {os.path.basename(node.file_path)} L{node.line_start}-{node.line_end})"
            if cross_callers:
                info += f" -- called by: {', '.join(cross_callers[:3])}"
            if affected:
                aff_names = sorted(set(os.path.basename(f) for f in affected))[:4]
                info += f" -- affects: {', '.join(aff_names)}"
            matches.append(info)

    # Check for file path matches
    tracked_files = set()
    for node in bridge.graph.get_all_nodes():
        tracked_files.add(node.file_path)

    for word in words:
        for fp in tracked_files:
            if word in fp and word not in [m.split(' ')[0] for m in matches]:
                affected = set()
                for node in bridge.graph.get_nodes_by_file(fp):
                    for f in bridge.get_affected_files(fp, node.name):
                        affected.add(f)
                if affected:
                    aff_names = sorted(set(os.path.basename(f) for f in affected))[:4]
                    matches.append(f"{fp} -- affects: {', '.join(aff_names)}")
                else:
                    matches.append(fp)
                break  # One match per word

    return matches[:5]  # Max 5 entity matches


def _fallback_handle(input_data):
    """Direct graph processing (no daemon)."""
    user_prompt = input_data.get("user_prompt", "")
    if not user_prompt or len(user_prompt) < 5:
        return None

    bridge = _load_graph(input_data)
    if bridge is None:
        return None

    # Try classifying as a relationship query
    result = classify_explore_prompt(user_prompt)
    if result is not None:
        command, args = result
        output = _execute_command(bridge, command, args)
        if output:
            return {"systemMessage": f"[StreamRAG] Relevant graph context:\n{output}"}

    # Scan for entity/file mentions
    matches = _scan_for_entities(bridge, user_prompt)
    if matches:
        lines = ["[StreamRAG] Relevant graph context:"]
        for m in matches:
            lines.append(f"  {m}")
        return {"systemMessage": "\n".join(lines)}

    return None


def main():
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    hook_event = input_data.get("hook_event_name", "")
    if hook_event != "UserPromptSubmit":
        sys.exit(0)

    user_prompt = input_data.get("user_prompt", "")
    if not user_prompt or len(user_prompt) < 5:
        sys.exit(0)

    # Fast path: daemon
    project_path = input_data.get("project_path", os.getcwd())
    try:
        from streamrag.daemon_client import ensure_daemon, send_request
        if ensure_daemon(project_path):
            response = send_request(project_path, {
                "cmd": "classify_user_prompt",
                "user_prompt": user_prompt,
                "project_path": project_path,
                "session_id": input_data.get("session_id", "default"),
            }, timeout=1.5)
            if response is not None:
                if response:  # Non-empty response
                    print(json.dumps(response), file=sys.stdout)
                sys.exit(0)
    except Exception:
        pass

    # Fallback: direct processing
    result = _fallback_handle(input_data)
    if result:
        print(json.dumps(result), file=sys.stdout)

    sys.exit(0)


if __name__ == "__main__":
    main()
