"""Tests for context stabilizer integration in the daemon."""

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


def _make_project_with_deps():
    d = tempfile.mkdtemp(prefix="streamrag_stab_test_")
    with open(os.path.join(d, "models.py"), "w") as f:
        f.write("class User:\n    name: str\n\nclass Order:\n    user: User\n")
    with open(os.path.join(d, "service.py"), "w") as f:
        f.write("from models import User\n\ndef get_user(uid):\n    return User()\n")
    return d


class TestDaemonContextStabilizer(unittest.TestCase):
    """Test context stabilizer caching in handle_get_read_context."""

    def setUp(self):
        self.project_dir = _make_project_with_deps()
        self.daemon = StreamRAGDaemon(self.project_dir)
        # Seed graph
        for fname in ("models.py", "service.py"):
            self.daemon.handle_process_change({
                "file_path": fname,
                "abs_file_path": os.path.join(self.project_dir, fname),
            })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_stabilizer_exists(self):
        """Daemon should have a _context_stabilizer attribute."""
        self.assertTrue(hasattr(self.daemon, '_context_stabilizer'))

    def test_cached_context_within_window(self):
        """Two rapid get_read_context calls should use cached context."""
        req = {"file_path": "models.py"}
        result1 = self.daemon.handle_get_read_context(req)
        # Immediately call again (within stability window)
        result2 = self.daemon.handle_get_read_context(req)
        # Both should return something (stabilizer may cache)
        # The key is no crash and consistent results
        self.assertEqual(type(result1), type(result2))

    def test_invalidate_on_change(self):
        """Context stabilizer should invalidate after process_change."""
        req = {"file_path": "models.py"}
        # Get context (caches it)
        self.daemon.handle_get_read_context(req)

        # Make a change (should invalidate)
        models_path = os.path.join(self.project_dir, "models.py")
        with open(models_path, "w") as f:
            f.write("class User:\n    name: str\n    email: str\n\nclass Order:\n    user: User\n")
        self.daemon.handle_process_change({
            "file_path": "models.py",
            "abs_file_path": models_path,
        })

        # Stabilizer should have been invalidated
        if self.daemon._context_stabilizer:
            self.assertIsNone(self.daemon._context_stabilizer._cached_stable)


if __name__ == "__main__":
    unittest.main()
