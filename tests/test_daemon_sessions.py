"""Tests for AISessionManager integration in the daemon."""

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
    d = tempfile.mkdtemp(prefix="streamrag_sess_test_")
    with open(os.path.join(d, "app.py"), "w") as f:
        f.write("def main():\n    pass\n")
    return d


class TestDaemonSessionManager(unittest.TestCase):
    """Test session manager RPC handlers."""

    def setUp(self):
        self.project_dir = _make_project()
        self.daemon = StreamRAGDaemon(self.project_dir)
        self.daemon.handle_process_change({
            "file_path": "app.py",
            "abs_file_path": os.path.join(self.project_dir, "app.py"),
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_session_manager_exists(self):
        """Daemon should have _session_manager attribute after bridge load."""
        self.assertTrue(hasattr(self.daemon, '_session_manager'))

    def test_start_session_handler(self):
        """start_session RPC should return session_id and base_version."""
        result = self.daemon.handle_start_session({})
        self.assertIn("session_id", result)
        self.assertIn("base_version", result)

    def test_complete_session_clean(self):
        """complete_session with no drift should return clean status."""
        start = self.daemon.handle_start_session({})
        result = self.daemon.handle_complete_session({
            "session_id": start["session_id"],
        })
        self.assertEqual(result["status"], "clean")

    def test_complete_session_with_drift(self):
        """complete_session after changes should detect drift."""
        start = self.daemon.handle_start_session({})

        # Make a change to create drift
        app_path = os.path.join(self.project_dir, "app.py")
        with open(app_path, "w") as f:
            f.write("def main():\n    return 42\n")
        self.daemon.handle_process_change({
            "file_path": "app.py",
            "abs_file_path": app_path,
        })

        result = self.daemon.handle_complete_session({
            "session_id": start["session_id"],
        })
        self.assertIn(result["status"], ("clean_with_drift", "conflicts"))
        self.assertGreater(result["drift"], 0)

    def test_handlers_registered(self):
        """start_session and complete_session should be in HANDLERS dict."""
        self.assertIn("start_session", self.daemon.HANDLERS)
        self.assertIn("complete_session", self.daemon.HANDLERS)

    def test_dispatch_start_session(self):
        """dispatch should route start_session correctly."""
        result = self.daemon.dispatch({"cmd": "start_session"})
        self.assertIn("session_id", result)


class TestDaemonClientSessions(unittest.TestCase):
    """Test client-side session methods."""

    def test_client_methods_exist(self):
        """daemon_client should have start_session and complete_session."""
        from streamrag import daemon_client
        self.assertTrue(hasattr(daemon_client, 'start_session'))
        self.assertTrue(hasattr(daemon_client, 'complete_session'))
        self.assertTrue(callable(daemon_client.start_session))
        self.assertTrue(callable(daemon_client.complete_session))


if __name__ == "__main__":
    unittest.main()
