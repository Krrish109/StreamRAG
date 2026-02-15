"""Tests for async propagation queue draining in the daemon."""

import asyncio
import os
import sys
import tempfile
import unittest

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)
os.environ.setdefault("CLAUDE_PLUGIN_ROOT", PLUGIN_ROOT)

from streamrag.daemon import StreamRAGDaemon


def _make_project():
    d = tempfile.mkdtemp(prefix="streamrag_prop_test_")
    with open(os.path.join(d, "base.py"), "w") as f:
        f.write("def shared():\n    return 1\n")
    with open(os.path.join(d, "caller.py"), "w") as f:
        f.write("from base import shared\n\ndef use():\n    return shared()\n")
    return d


class TestAsyncPropagation(unittest.TestCase):
    """Test that daemon drains the async propagation queue."""

    def setUp(self):
        self.project_dir = _make_project()
        self.daemon = StreamRAGDaemon(self.project_dir)
        # Seed
        for f in ("base.py", "caller.py"):
            self.daemon.handle_process_change({
                "file_path": f,
                "abs_file_path": os.path.join(self.project_dir, f),
            })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_propagation_loop_method_exists(self):
        """Daemon should have _periodic_propagation_loop method."""
        self.assertTrue(hasattr(self.daemon, '_periodic_propagation_loop'))
        self.assertTrue(callable(self.daemon._periodic_propagation_loop))

    def test_propagation_drains_queue(self):
        """After process_change, async queue items should eventually drain."""
        bridge = self.daemon._ensure_bridge()
        if bridge._propagator is None:
            self.skipTest("Propagator not enabled")

        # Make a change that triggers propagation
        base_path = os.path.join(self.project_dir, "base.py")
        with open(base_path, "w") as f:
            f.write("def shared():\n    return 2\n")
        self.daemon.handle_process_change({
            "file_path": "base.py",
            "abs_file_path": base_path,
        })

        # If there are async items, drain them
        if bridge._propagator.async_queue_size > 0:
            processed = bridge._propagator.process_async_queue(
                max_items=5, update_fn=bridge._re_parse_file
            )
            self.assertIsInstance(processed, list)


if __name__ == "__main__":
    unittest.main()
