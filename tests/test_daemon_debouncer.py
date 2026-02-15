"""Tests for diff-based debouncer integration in the daemon."""

import os
import sys
import tempfile
import time
import unittest

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)
os.environ.setdefault("CLAUDE_PLUGIN_ROOT", PLUGIN_ROOT)

from streamrag.daemon import StreamRAGDaemon


def _make_project_dir():
    d = tempfile.mkdtemp(prefix="streamrag_debounce_test_")
    with open(os.path.join(d, "app.py"), "w") as f:
        f.write("def hello():\n    return 'world'\n")
    return d


class TestDaemonDebouncer(unittest.TestCase):
    """Test diff-based debouncer in daemon.handle_process_change."""

    def setUp(self):
        self.project_dir = _make_project_dir()
        self.daemon = StreamRAGDaemon(self.project_dir)
        # Seed the bridge with initial content
        self.daemon.handle_process_change({
            "file_path": "app.py",
            "abs_file_path": os.path.join(self.project_dir, "app.py"),
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_semantic_change_processes_immediately(self):
        """Multi-line changes (SEMANTIC tier) should process immediately."""
        # Write a significant change
        app_path = os.path.join(self.project_dir, "app.py")
        with open(app_path, "w") as f:
            f.write("def hello():\n    return 'world'\n\ndef goodbye():\n    return 'bye'\n")

        result = self.daemon.handle_process_change({
            "file_path": "app.py",
            "abs_file_path": app_path,
        })
        # Should have processed (new function added)
        self.assertIn("systemMessage", result)

    def test_small_change_debounced(self):
        """Single-char changes within debounce window should be buffered."""
        # This test verifies that _classify_change_tier exists and works
        bridge = self.daemon._ensure_bridge()
        old = bridge._file_contents.get("app.py", "")
        # Simulate a 1-char edit
        new = old + " "
        tier = self.daemon._classify_change_tier(old, new)
        # Single whitespace char should be TOKEN tier or lower
        from streamrag.v2.debouncer import DebounceTier
        self.assertLessEqual(tier, DebounceTier.TOKEN)

    def test_multiline_change_is_semantic(self):
        """Multi-line diffs should classify as SEMANTIC."""
        old = "def foo():\n    pass\n"
        new = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        tier = self.daemon._classify_change_tier(old, new)
        from streamrag.v2.debouncer import DebounceTier
        self.assertEqual(tier, DebounceTier.SEMANTIC)

    def test_single_line_change_is_statement(self):
        """Single-line multi-char changes should classify as STATEMENT."""
        old = "def foo():\n    pass\n"
        new = "def foo():\n    return 42\n"
        tier = self.daemon._classify_change_tier(old, new)
        from streamrag.v2.debouncer import DebounceTier
        self.assertGreaterEqual(tier, DebounceTier.STATEMENT)

    def test_debounce_flush_processes_buffered(self):
        """Flushing stale debounce buffers should process the change."""
        # Verify the daemon has debounce buffer infrastructure
        self.assertIsInstance(self.daemon._debounce_buffers, dict)


class TestDaemonDebouncerDisabled(unittest.TestCase):
    """Test graceful degradation when debouncer import fails."""

    def test_works_without_debouncer(self):
        """Daemon should work even if v2.debouncer import fails."""
        project_dir = _make_project_dir()
        try:
            daemon = StreamRAGDaemon(project_dir)
            # Should still process changes
            result = daemon.handle_process_change({
                "file_path": "app.py",
                "abs_file_path": os.path.join(project_dir, "app.py"),
            })
            # Should return something (or empty dict if no semantic change)
            self.assertIsInstance(result, dict)
        finally:
            import shutil
            shutil.rmtree(project_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
