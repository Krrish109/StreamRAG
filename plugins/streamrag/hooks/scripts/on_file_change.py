#!/usr/bin/env python3
"""PostToolUse hook: feeds file edits to DeltaGraphBridge.

Triggered on Edit|Write|MultiEdit. Sends change to daemon for fast in-memory
processing. Falls back to direct graph loading if daemon is unavailable.
"""

import json
import os
import sys

# CRITICAL: Add plugin root to Python path for imports
PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT")
if PLUGIN_ROOT:
    parent_dir = os.path.dirname(PLUGIN_ROOT)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    if PLUGIN_ROOT not in sys.path:
        sys.path.insert(0, PLUGIN_ROOT)

try:
    from streamrag.models import SUPPORTED_EXTENSIONS
    from streamrag.languages.registry import create_default_registry
except ImportError as e:
    error_msg = {"systemMessage": f"StreamRAG import error: {e}"}
    print(json.dumps(error_msg), file=sys.stdout)
    sys.exit(0)


def _fallback_process_change(input_data, file_path, abs_file_path, registry):
    """Original logic: load graph from disk, process change, save."""
    from streamrag.bridge import DeltaGraphBridge
    from streamrag.models import CodeChange
    from streamrag.storage.memory import (
        load_state, save_state,
        load_project_state, save_project_state,
        is_state_stale,
    )

    session_id = input_data.get("session_id", "default")
    project_path = input_data.get("project_path", os.getcwd())

    # Load or create bridge
    bridge = None
    if not is_state_stale(project_path):
        bridge = load_project_state(project_path)
    if bridge is None:
        bridge = load_state(session_id)
    if bridge is None:
        bridge = DeltaGraphBridge()

    # Enable versioned graph
    if bridge._versioned is None:
        try:
            from streamrag.v2.versioned_graph import VersionedGraph
            bridge._versioned = VersionedGraph(bridge.graph)
        except ImportError:
            pass

    # Enable hierarchical graph + propagator
    try:
        from streamrag.v2.hierarchical_graph import HierarchicalGraph
        from streamrag.v2.bounded_propagator import BoundedPropagator
        if bridge._hierarchical is None:
            bridge._hierarchical = HierarchicalGraph(graph=bridge.graph)
        if bridge._propagator is None:
            bridge._propagator = BoundedPropagator(graph=bridge.graph)
    except ImportError:
        pass

    # Auto-init (skip if graph already populated)
    tracked = bridge._tracked_files or set(bridge._file_contents.keys())
    if bridge.graph.node_count == 0 or len(tracked) == 0:
        import time
        _max_files = int(os.environ.get("STREAMRAG_MAX_FILES", "200"))
        _max_files = min(_max_files, 2000)
        if project_path and os.path.isdir(project_path) and len(tracked) < _max_files:
            skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv",
                         ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
                         "target", "out", "bin", "obj"}
            start = time.time()
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip_dirs]
                for fname in files:
                    if not registry.can_handle(fname):
                        continue
                    if len(tracked) >= _max_files:
                        break
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, project_path)
                    if rel in tracked:
                        continue
                    if time.time() - start > 7.0:
                        break
                    try:
                        with open(fpath, "r") as f:
                            content = f.read()
                    except (IOError, UnicodeDecodeError):
                        continue
                    bridge.process_change(CodeChange(file_path=rel, old_content="", new_content=content))
                    tracked.add(rel)
                else:
                    continue
                break

    # Get old content from cache
    old_content = bridge._file_contents.get(file_path, "")

    # Read new content from disk
    try:
        with open(abs_file_path, "r") as f:
            new_content = f.read()
    except (IOError, OSError):
        return {}

    change = CodeChange(file_path=file_path, old_content=old_content, new_content=new_content)
    ops = bridge.process_change(change)

    # Single save (project-level only)
    try:
        save_project_state(bridge, project_path)
    except Exception:
        pass

    if not ops:
        return {}

    # Build minimal summary
    real_ops = [op for op in ops if op.node_type != "propagation"]
    msg = f"StreamRAG: {len(real_ops)} ops"

    breaking = []
    for op in ops:
        if op.op_type == "remove_node" and op.properties.get("had_callers"):
            callers = op.properties["had_callers"]
            breaking.append(f"{op.properties['name']} removed (used by {', '.join(callers[:3])})")
    if breaking:
        msg += " | BREAKING: " + "; ".join(breaking)

    if os.environ.get("STREAMRAG_PROACTIVE", ""):
        import time as _time
        warnings = []
        t0 = _time.time()
        try:
            cycles = bridge.check_new_cycles(file_path)
            if cycles:
                warnings.append(f"Circular dep: {' -> '.join(cycles[0][:4])}")
            if _time.time() - t0 < 3.0:
                dead = bridge.check_new_dead_code(file_path)
                new_adds = {op.properties.get("name") for op in ops if op.op_type == "add_node"}
                new_dead = [n for n in dead if n.name in new_adds]
                if new_dead:
                    warnings.append(f"New unused: {', '.join(n.name for n in new_dead[:3])}")
        except Exception:
            pass
        if warnings:
            msg += " | WARNINGS: " + "; ".join(warnings)

    return {"systemMessage": msg}


def main():
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    if tool_name not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    # Check if supported
    try:
        registry = create_default_registry()
        if not registry.can_handle(file_path):
            sys.exit(0)
    except Exception:
        if not any(file_path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            sys.exit(0)
        registry = None

    # Normalize paths
    project_path = input_data.get("project_path", os.getcwd())
    abs_file_path = file_path
    if os.path.isabs(file_path) and project_path:
        try:
            rel_path = os.path.relpath(file_path, project_path)
            if not rel_path.startswith(".."):
                file_path = rel_path
        except ValueError:
            pass

    # Fast path: daemon
    try:
        from streamrag.daemon_client import ensure_daemon, send_request
        if ensure_daemon(project_path):
            response = send_request(project_path, {
                "cmd": "process_change",
                "file_path": file_path,
                "abs_file_path": abs_file_path,
                "project_path": project_path,
                "session_id": input_data.get("session_id", "default"),
            }, timeout=8.0)
            if response is not None:
                print(json.dumps(response), file=sys.stdout)
                sys.exit(0)
    except Exception:
        pass

    # Fallback: direct processing
    result = _fallback_process_change(input_data, file_path, abs_file_path, registry)
    print(json.dumps(result), file=sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
