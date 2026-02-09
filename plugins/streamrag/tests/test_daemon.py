"""Tests for the StreamRAG daemon server and client."""

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# Add plugin root to path
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

os.environ.setdefault("CLAUDE_PLUGIN_ROOT", PLUGIN_ROOT)

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange
from streamrag.daemon import StreamRAGDaemon, get_socket_path, get_pid_path
from streamrag.daemon_client import (
    send_request, ensure_daemon, _is_daemon_alive,
    _is_process_alive, _cleanup_stale, _start_daemon,
)


def _make_project_dir():
    """Create a temp project directory with a Python file."""
    d = tempfile.mkdtemp(prefix="streamrag_test_")
    with open(os.path.join(d, "test_file.py"), "w") as f:
        f.write("def foo():\n    pass\n\nclass Bar:\n    pass\n")
    return d


class TestDaemonUnit(unittest.TestCase):
    """Unit tests for StreamRAGDaemon methods (no server)."""

    def setUp(self):
        self.project_dir = _make_project_dir()
        self.daemon = StreamRAGDaemon(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_ping(self):
        """ping returns alive with node/edge counts."""
        result = self.daemon.handle_ping({})
        self.assertTrue(result["alive"])
        self.assertIn("nodes", result)
        self.assertIn("edges", result)

    def test_process_change(self):
        """process_change processes a file and returns systemMessage."""
        # Create a new file not in the project dir initially
        # (auto-init won't find it since we create it after init)
        self.daemon._initialized = True
        self.daemon.bridge = DeltaGraphBridge()

        test_file = os.path.join(self.project_dir, "new_file.py")
        with open(test_file, "w") as f:
            f.write("def hello():\n    return 'hi'\n")

        result = self.daemon.handle_process_change({
            "file_path": "new_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
            "session_id": "test",
        })
        # First time: entities added
        self.assertIn("systemMessage", result)
        self.assertIn("StreamRAG:", result["systemMessage"])
        self.assertTrue(self.daemon._dirty)

    def test_process_change_unsupported_file(self):
        """process_change returns empty for unsupported files."""
        result = self.daemon.handle_process_change({
            "file_path": "README.md",
            "abs_file_path": os.path.join(self.project_dir, "README.md"),
            "project_path": self.project_dir,
        })
        self.assertEqual(result, {})

    def test_get_read_context_no_graph(self):
        """get_read_context with empty graph returns init message."""
        # Force empty bridge (skip auto-init so graph stays empty)
        self.daemon._initialized = True
        self.daemon.bridge = DeltaGraphBridge()
        result = self.daemon.handle_get_read_context({
            "file_path": "test.py",
            "project_path": self.project_dir,
        })
        self.assertIn("first file edit", result.get("systemMessage", ""))

    def test_get_read_context_with_file(self):
        """get_read_context returns context for tracked file."""
        # First process a file to populate the graph
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })

        result = self.daemon.handle_get_read_context({
            "file_path": "test_file.py",
            "project_path": self.project_dir,
        })
        self.assertIn("systemMessage", result)
        self.assertIn("StreamRAG", result["systemMessage"])

    def test_get_read_context_unsupported(self):
        """get_read_context returns empty for unsupported files."""
        result = self.daemon.handle_get_read_context({
            "file_path": "README.md",
            "project_path": self.project_dir,
        })
        self.assertEqual(result, {})

    def test_get_compact_summary_empty(self):
        """get_compact_summary with empty graph returns empty."""
        # Force bridge to be created but empty (skip auto-init)
        self.daemon._initialized = True
        self.daemon.bridge = DeltaGraphBridge()
        result = self.daemon.handle_get_compact_summary({})
        self.assertEqual(result, {})

    def test_get_compact_summary_with_data(self):
        """get_compact_summary with data returns summary."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })
        result = self.daemon.handle_get_compact_summary({})
        self.assertIn("systemMessage", result)
        self.assertIn("StreamRAG Code Graph", result["systemMessage"])

    def test_classify_query_explore(self):
        """classify_query augments Explore with relationship prompt."""
        # Populate graph
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })

        result = self.daemon.handle_classify_query({
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "Explore",
                "prompt": "what calls foo",
                "description": "find callers",
            },
            "project_path": self.project_dir,
        })
        # Should get systemMessage without deny since we now augment
        self.assertNotIn("decision", result)
        self.assertIn("StreamRAG", result.get("systemMessage", ""))

    def test_classify_query_non_explore(self):
        """classify_query ignores non-Explore tasks."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })
        result = self.daemon.handle_classify_query({
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "Bash",
                "prompt": "what calls foo",
            },
            "project_path": self.project_dir,
        })
        self.assertEqual(result, {})

    def test_classify_query_text_search(self):
        """classify_query allows non-relationship prompts."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })
        result = self.daemon.handle_classify_query({
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "Explore",
                "prompt": "find all TODO comments",
                "description": "search todos",
            },
            "project_path": self.project_dir,
        })
        self.assertEqual(result, {})

    def test_classify_user_prompt_relationship_query(self):
        """classify_user_prompt returns context for relationship queries."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })
        result = self.daemon.handle_classify_user_prompt({
            "user_prompt": "what calls foo",
            "project_path": self.project_dir,
        })
        self.assertIn("systemMessage", result)
        self.assertIn("[StreamRAG]", result["systemMessage"])

    def test_classify_user_prompt_entity_mention(self):
        """classify_user_prompt returns context for entity name mentions."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })
        result = self.daemon.handle_classify_user_prompt({
            "user_prompt": "I want to refactor the foo function",
            "project_path": self.project_dir,
        })
        self.assertIn("systemMessage", result)
        self.assertIn("foo", result["systemMessage"])

    def test_classify_user_prompt_empty(self):
        """classify_user_prompt returns empty for very short prompts."""
        result = self.daemon.handle_classify_user_prompt({
            "user_prompt": "hi",
            "project_path": self.project_dir,
        })
        self.assertEqual(result, {})

    def test_classify_user_prompt_no_graph(self):
        """classify_user_prompt returns empty when graph is empty."""
        self.daemon._initialized = True
        self.daemon.bridge = DeltaGraphBridge()
        result = self.daemon.handle_classify_user_prompt({
            "user_prompt": "what calls foo",
            "project_path": self.project_dir,
        })
        self.assertEqual(result, {})

    def test_classify_user_prompt_no_match(self):
        """classify_user_prompt returns empty for unrelated prompts."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        })
        result = self.daemon.handle_classify_user_prompt({
            "user_prompt": "hello how are you doing today",
            "project_path": self.project_dir,
        })
        self.assertEqual(result, {})

    def test_dispatch_unknown_command(self):
        """dispatch returns error for unknown commands."""
        result = self.daemon.dispatch({"cmd": "nonexistent"})
        self.assertIn("error", result)

    def test_shutdown(self):
        """shutdown saves state."""
        self.daemon.handle_process_change({
            "file_path": "test_file.py",
            "abs_file_path": os.path.join(self.project_dir, "test_file.py"),
            "project_path": self.project_dir,
        })
        with patch("streamrag.daemon.save_project_state") as mock_save:
            result = self.daemon.handle_shutdown({})
            self.assertTrue(result.get("ok"))
            mock_save.assert_called_once()

    def test_cleanup_deleted_files_every_10th(self):
        """_cleanup_deleted_files only runs every 10th call."""
        self.daemon._ensure_bridge()
        self.daemon._initialized = True
        # First call (counter=1) should run
        self.daemon._cleanup_counter = 0
        self.daemon._cleanup_deleted_files()
        self.assertEqual(self.daemon._cleanup_counter, 1)

        # Next 9 calls should be skipped
        for _ in range(9):
            self.daemon._cleanup_deleted_files()
        self.assertEqual(self.daemon._cleanup_counter, 10)

    def test_auto_init_idempotent(self):
        """_maybe_auto_init sets _initialized and doesn't run twice."""
        self.daemon._maybe_auto_init()
        self.assertTrue(self.daemon._initialized)

        # Second call should be no-op (flag already set)
        bridge_before = self.daemon.bridge
        self.daemon._maybe_auto_init()
        self.assertIs(self.daemon.bridge, bridge_before)

    def test_save_if_dirty(self):
        """_save_if_dirty only saves when dirty."""
        self.daemon._ensure_bridge()
        with patch("streamrag.daemon.save_project_state") as mock_save:
            self.daemon._dirty = False
            self.daemon._save_if_dirty()
            mock_save.assert_not_called()

            self.daemon._dirty = True
            self.daemon._save_if_dirty()
            mock_save.assert_called_once()
            self.assertFalse(self.daemon._dirty)


class TestDaemonClient(unittest.TestCase):
    """Tests for daemon_client functions."""

    def test_is_process_alive_self(self):
        """Current process should be alive."""
        self.assertTrue(_is_process_alive(os.getpid()))

    def test_is_process_alive_dead(self):
        """Non-existent PID should not be alive."""
        self.assertFalse(_is_process_alive(99999999))

    def test_is_daemon_alive_no_pid_file(self):
        """No PID file means daemon is not alive."""
        self.assertFalse(_is_daemon_alive("/nonexistent/path"))

    def test_cleanup_stale(self):
        """_cleanup_stale removes PID and socket files."""
        with tempfile.TemporaryDirectory() as d:
            pid_path = os.path.join(d, "test.pid")
            sock_path = os.path.join(d, "test.sock")
            open(pid_path, "w").close()
            open(sock_path, "w").close()
            self.assertTrue(os.path.exists(pid_path))
            # Patch the functions where they're looked up (in daemon_client module)
            with patch("streamrag.daemon_client.get_pid_path", return_value=pid_path), \
                 patch("streamrag.daemon_client.get_socket_path", return_value=sock_path):
                _cleanup_stale("/fake/path")
            self.assertFalse(os.path.exists(pid_path))
            self.assertFalse(os.path.exists(sock_path))

    def test_send_request_no_socket(self):
        """send_request returns None when no socket exists."""
        result = send_request("/nonexistent/path", {"cmd": "ping"}, timeout=0.5)
        self.assertIsNone(result)

    def test_ensure_daemon_starts_daemon(self):
        """ensure_daemon tries to start daemon when not running."""
        with patch("streamrag.daemon_client._is_daemon_alive", return_value=False), \
             patch("streamrag.daemon_client._cleanup_stale"), \
             patch("streamrag.daemon_client._start_daemon", return_value=True) as mock_start:
            result = ensure_daemon("/some/path")
            self.assertTrue(result)
            mock_start.assert_called_once_with("/some/path")

    def test_ensure_daemon_already_running(self):
        """ensure_daemon returns True when daemon is already running."""
        with patch("streamrag.daemon_client._is_daemon_alive", return_value=True):
            result = ensure_daemon("/some/path")
            self.assertTrue(result)


class TestDaemonServerAsync(unittest.TestCase):
    """Tests for the actual async daemon server."""

    def setUp(self):
        self.project_dir = _make_project_dir()
        self.daemon = StreamRAGDaemon(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_dir, ignore_errors=True)
        # Clean up any leftover socket/pid files
        sock = get_socket_path(self.project_dir)
        pid = get_pid_path(self.project_dir)
        for f in (sock, pid):
            try:
                os.unlink(f)
            except OSError:
                pass

    def _run_server_with_requests(self, requests):
        """Start server, send requests, collect responses, stop."""
        responses = []

        async def _test():
            sock_path = get_socket_path(self.project_dir)
            pid_path = get_pid_path(self.project_dir)

            # Clean up
            for f in (sock_path, pid_path):
                try:
                    os.unlink(f)
                except OSError:
                    pass

            # Start server
            self.daemon._ensure_bridge()
            self.daemon._initialized = True
            server = await asyncio.start_unix_server(
                self.daemon._handle_client, path=sock_path)

            async with server:
                for req in requests:
                    reader, writer = await asyncio.open_unix_connection(sock_path)
                    writer.write(json.dumps(req).encode() + b"\n")
                    await writer.drain()
                    data = await asyncio.wait_for(reader.readline(), timeout=5.0)
                    responses.append(json.loads(data.decode()))
                    writer.close()
                    await writer.wait_closed()

            server.close()
            await server.wait_closed()
            try:
                os.unlink(sock_path)
            except OSError:
                pass

        asyncio.run(_test())
        return responses

    def test_server_ping(self):
        """Server responds to ping over socket."""
        responses = self._run_server_with_requests([{"cmd": "ping"}])
        self.assertEqual(len(responses), 1)
        self.assertTrue(responses[0]["alive"])

    def test_server_process_change(self):
        """Server processes file change over socket."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        responses = self._run_server_with_requests([{
            "cmd": "process_change",
            "file_path": "test_file.py",
            "abs_file_path": test_file,
            "project_path": self.project_dir,
        }])
        self.assertEqual(len(responses), 1)
        # Should have a systemMessage with ops
        self.assertIn("systemMessage", responses[0])

    def test_server_multiple_requests(self):
        """Server handles multiple sequential requests."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        responses = self._run_server_with_requests([
            {"cmd": "ping"},
            {
                "cmd": "process_change",
                "file_path": "test_file.py",
                "abs_file_path": test_file,
                "project_path": self.project_dir,
            },
            {
                "cmd": "get_read_context",
                "file_path": "test_file.py",
                "project_path": self.project_dir,
            },
            {"cmd": "ping"},
        ])
        self.assertEqual(len(responses), 4)
        self.assertTrue(responses[0]["alive"])
        # After process_change, graph should have nodes
        self.assertGreater(responses[3]["nodes"], 0)

    def test_server_unknown_command(self):
        """Server returns error for unknown commands."""
        responses = self._run_server_with_requests([{"cmd": "bogus"}])
        self.assertEqual(len(responses), 1)
        self.assertIn("error", responses[0])

    def test_server_get_compact_summary(self):
        """Server returns compact summary."""
        test_file = os.path.join(self.project_dir, "test_file.py")
        responses = self._run_server_with_requests([
            {
                "cmd": "process_change",
                "file_path": "test_file.py",
                "abs_file_path": test_file,
                "project_path": self.project_dir,
            },
            {"cmd": "get_compact_summary"},
        ])
        self.assertEqual(len(responses), 2)
        self.assertIn("systemMessage", responses[1])
        self.assertIn("StreamRAG Code Graph", responses[1]["systemMessage"])


class TestStorageQuickWins(unittest.TestCase):
    """Tests for storage layer improvements."""

    def test_is_state_stale_uses_mtime(self):
        """is_state_stale uses file mtime, not JSON parsing."""
        from streamrag.storage.memory import is_state_stale, save_project_state

        with tempfile.TemporaryDirectory() as d:
            bridge = DeltaGraphBridge()
            bridge.process_change(CodeChange(
                file_path="test.py", old_content="", new_content="x = 1\n"))
            save_project_state(bridge, d)

            # Fresh file should NOT be stale
            self.assertFalse(is_state_stale(d))

            # Stale with very short max_age
            self.assertTrue(is_state_stale(d, max_age_hours=0.0))

    def test_get_project_state_path_helper(self):
        """_get_project_state_path returns consistent paths."""
        from streamrag.storage.memory import _get_project_state_path
        p1 = _get_project_state_path("/some/path")
        p2 = _get_project_state_path("/some/path")
        self.assertEqual(p1, p2)
        self.assertIn("graph_", p1)
        self.assertTrue(p1.endswith(".json"))


if __name__ == "__main__":
    unittest.main()
