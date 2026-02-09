"""Tests for auto-initialization functionality."""

import os
import tempfile

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange
from streamrag.daemon import StreamRAGDaemon


def test_auto_init_populates_graph():
    """Auto-init from a directory with .py files populates the graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some .py files
        with open(os.path.join(tmpdir, "a.py"), "w") as f:
            f.write("def hello():\n    pass\n")
        with open(os.path.join(tmpdir, "b.py"), "w") as f:
            f.write("def world():\n    pass\n")
        # Create a non-py file (should be ignored)
        with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
            f.write("Not a python file")

        daemon = StreamRAGDaemon(tmpdir)
        daemon.bridge = DeltaGraphBridge()
        daemon._maybe_auto_init()

        assert daemon.bridge.graph.node_count >= 2


def test_auto_init_is_idempotent():
    """Auto-init skips files already tracked in the graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "a.py"), "w") as f:
            f.write("def hello():\n    pass\n")
        with open(os.path.join(tmpdir, "b.py"), "w") as f:
            f.write("def world():\n    pass\n")

        daemon = StreamRAGDaemon(tmpdir)
        daemon.bridge = DeltaGraphBridge()
        daemon._maybe_auto_init()
        count_after_first = daemon.bridge.graph.node_count

        # Second call should not add anything new (flag is set)
        daemon._maybe_auto_init()
        assert daemon.bridge.graph.node_count == count_after_first


def test_auto_init_respects_max_files():
    """Auto-init stops after max_files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(10):
            with open(os.path.join(tmpdir, f"file_{i}.py"), "w") as f:
                f.write(f"def func_{i}():\n    pass\n")

        daemon = StreamRAGDaemon(tmpdir)
        daemon.bridge = DeltaGraphBridge()
        daemon._maybe_auto_init(max_files=3)

        # Should have processed at most 3 files
        files_tracked = len(daemon.bridge._tracked_files)
        assert files_tracked <= 3
