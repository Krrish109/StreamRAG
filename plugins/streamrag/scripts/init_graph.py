#!/usr/bin/env python3
"""Cold-start: initialize a StreamRAG graph from a project directory."""

import os
import sys

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange
from streamrag.storage.memory import save_state, save_project_state
from streamrag.languages.registry import create_default_registry


def init_graph(project_dir: str, session_id: str = "default") -> DeltaGraphBridge:
    """Scan project for source files and build initial graph."""
    bridge = DeltaGraphBridge()
    registry = create_default_registry()
    file_count = 0

    for root, dirs, files in os.walk(project_dir):
        # Skip hidden dirs, build artifacts, package managers
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
            "__pycache__", "node_modules", ".git", "venv", ".venv",
            "target", "out", "bin", "obj", "dist", "build",
        )]

        for fname in files:
            if not registry.can_handle(fname):
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r") as f:
                    content = f.read()
            except (IOError, UnicodeDecodeError):
                continue

            rel_path = os.path.relpath(fpath, project_dir)
            change = CodeChange(file_path=rel_path, old_content="", new_content=content)
            bridge.process_change(change)
            file_count += 1

    save_state(bridge, session_id)
    try:
        save_project_state(bridge, project_dir)
    except Exception:
        pass  # Project-level save is best-effort
    return bridge


def main():
    if len(sys.argv) < 2:
        print("Usage: init_graph.py <project_directory> [session_id]")
        sys.exit(1)

    project_dir = sys.argv[1]
    session_id = sys.argv[2] if len(sys.argv) > 2 else "default"

    if not os.path.isdir(project_dir):
        print(f"Error: {project_dir} is not a directory")
        sys.exit(1)

    bridge = init_graph(project_dir, session_id)
    print(f"StreamRAG graph initialized:")
    print(f"  Nodes: {bridge.graph.node_count}")
    print(f"  Edges: {bridge.graph.edge_count}")
    print(f"  Files: {len(bridge._file_contents)}")
    print(f"  Hash:  {bridge.graph.compute_hash()}")


if __name__ == "__main__":
    main()
