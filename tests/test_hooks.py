"""Tests for hook scripts: pre_read_context, on_file_change, pre_compact."""

import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

# Add plugin root to path for imports
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# Also add hooks/scripts to path so we can import hook modules
hooks_dir = os.path.join(PLUGIN_ROOT, "hooks", "scripts")
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

# Add scripts dir to path so query_graph can be imported by the hook
scripts_dir = os.path.join(PLUGIN_ROOT, "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# Set CLAUDE_PLUGIN_ROOT for query_graph imports
os.environ.setdefault("CLAUDE_PLUGIN_ROOT", PLUGIN_ROOT)

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange, GraphEdge, GraphNode


def _make_bridge_with_file(file_path="test.py", source="def foo():\n    pass\n"):
    """Create a bridge with a single file processed."""
    bridge = DeltaGraphBridge()
    change = CodeChange(file_path=file_path, old_content="", new_content=source)
    bridge.process_change(change)
    return bridge


def _make_bridge_with_cross_deps():
    """Create a bridge with cross-file dependencies."""
    bridge = DeltaGraphBridge()
    # File A defines foo
    bridge.process_change(CodeChange(
        file_path="a.py", old_content="",
        new_content="def foo():\n    pass\n\ndef bar():\n    foo()\n",
    ))
    # File B imports and calls foo
    bridge.process_change(CodeChange(
        file_path="b.py", old_content="",
        new_content="from a import foo\n\ndef baz():\n    foo()\n",
    ))
    return bridge


def _capture_hook_output(main_fn, input_data, bridge=None, load_project=True,
                         file_content=None, save_mocks=False):
    """Run a hook's main() with mocked stdin/stdout and graph loading.

    Returns the parsed JSON output dict (or {} if empty/invalid).
    Daemon client is mocked to return False (force fallback path).
    """
    stdin_data = json.dumps(input_data)
    captured_stdout = StringIO()

    patches = {
        'sys.stdin': patch('sys.stdin', StringIO(stdin_data)),
        'sys.stdout': patch('sys.stdout', captured_stdout),
        # Force all hooks to use fallback path (no daemon)
        'ensure_daemon': patch(
            'streamrag.daemon_client.ensure_daemon', return_value=False),
        '_is_daemon_alive': patch(
            'streamrag.daemon_client._is_daemon_alive', return_value=False),
    }

    if load_project:
        patches['load_project'] = patch(
            'streamrag.storage.memory.load_project_state', return_value=bridge)
    patches['load_state'] = patch(
        'streamrag.storage.memory.load_state', return_value=bridge)

    if save_mocks:
        patches['save_state'] = patch(
            'streamrag.storage.memory.save_state', return_value="/tmp/s.json")
        patches['save_project'] = patch(
            'streamrag.storage.memory.save_project_state', return_value="/tmp/p.json")

    # Stack all patches
    active = {}
    for name, p in patches.items():
        active[name] = p.start()

    try:
        main_fn()
    except SystemExit:
        pass
    finally:
        for p in patches.values():
            p.stop()

    output = captured_stdout.getvalue().strip()
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {}
    return {}


# ---- pre_read_context tests ----

class TestPreReadContext(unittest.TestCase):
    """Tests for the pre_read_context.py hook."""

    @staticmethod
    def _main_fn():
        """Import and call pre_read_context.main() with signal mocks."""
        # pre_read_context sets signal.alarm at module level, so we need to
        # reimport fresh each time but the function is already importable
        # since we added hooks/scripts to sys.path. We just call it directly.
        import importlib
        # Ensure a fresh import
        if 'pre_read_context' in sys.modules:
            mod = importlib.reload(sys.modules['pre_read_context'])
        else:
            with patch('signal.signal'), patch('signal.alarm'):
                import pre_read_context as mod
        mod.main()

    def test_read_python_file_with_entities(self):
        """Read tool on Python file outputs systemMessage with entity info."""
        bridge = _make_bridge_with_file("test.py", "def foo():\n    pass\n\nclass Bar:\n    pass\n")
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Read",
                "tool_input": {"file_path": "test.py"},
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertIn("systemMessage", result)
        msg = result["systemMessage"]
        # Single-line format includes entity type counts
        self.assertIn("[StreamRAG] test.py:", msg)
        self.assertIn("1fn", msg)
        self.assertIn("1cls", msg)

    def test_non_read_tool_exits_silently(self):
        """Non-Read tool exits with empty output."""
        bridge = _make_bridge_with_file()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Edit",
                "tool_input": {"file_path": "test.py"},
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_unsupported_extension_exits_silently(self):
        """Unsupported file extension (.md) exits silently."""
        bridge = _make_bridge_with_file()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_file_not_in_graph_exits_silently(self):
        """File not tracked in graph exits silently."""
        bridge = _make_bridge_with_file("other.py")
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Read",
                "tool_input": {"file_path": "unknown.py"},
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_no_graph_shows_init_message(self):
        """No graph loaded shows initialization guidance message."""
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Read",
                "tool_input": {"file_path": "test.py"},
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=None)
        self.assertIn("systemMessage", result)
        self.assertIn("first file edit", result["systemMessage"])

    def test_read_shows_reverse_deps(self):
        """Read shows caller/reverse dependency info when present."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Read",
                "tool_input": {"file_path": "a.py"},
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertIn("systemMessage", result)
        msg = result["systemMessage"]
        # Multi-line context shows entity type counts and affected files
        self.assertIn("[StreamRAG] a.py:", msg)
        self.assertIn("Affected:", msg)


# ---- pre_compact tests ----

class TestPreCompact(unittest.TestCase):
    """Tests for the pre_compact.py hook logic."""

    def _build_summary(self, bridge):
        """Replicate pre_compact logic for testing."""
        if bridge is None or bridge.graph.node_count == 0:
            return None

        files = set()
        for node in bridge.graph._nodes.values():
            files.add(node.file_path)

        entity_counts = {}
        for node in bridge.graph._nodes.values():
            entity_counts[node.type] = entity_counts.get(node.type, 0) + 1

        summary_lines = [
            f"StreamRAG Code Graph: {bridge.graph.node_count} entities, "
            f"{bridge.graph.edge_count} edges across {len(files)} files.",
        ]

        for etype, count in sorted(entity_counts.items()):
            summary_lines.append(f"  {etype}: {count}")

        cross_file_edges = []
        for edges in bridge.graph._outgoing_edges.values():
            for edge in edges:
                src = bridge.graph.get_node(edge.source_id)
                tgt = bridge.graph.get_node(edge.target_id)
                if src and tgt and src.file_path != tgt.file_path:
                    cross_file_edges.append(
                        f"{src.file_path}:{src.name} -> {tgt.file_path}:{tgt.name}"
                    )

        if cross_file_edges:
            summary_lines.append(f"Cross-file deps ({len(cross_file_edges)}):")
            for dep in cross_file_edges[:10]:
                summary_lines.append(f"  {dep}")

        return "\n".join(summary_lines)

    def test_graph_with_entities_outputs_summary(self):
        """Graph with entities outputs summary with entity breakdown."""
        bridge = _make_bridge_with_file("test.py", "def foo():\n    pass\n\nclass Bar:\n    pass\n")
        summary = self._build_summary(bridge)
        self.assertIsNotNone(summary)
        self.assertIn("StreamRAG Code Graph", summary)
        self.assertIn("function", summary)
        self.assertIn("class", summary)

    def test_empty_graph_exits_silently(self):
        """Empty graph exits silently."""
        summary = self._build_summary(None)
        self.assertIsNone(summary)

    def test_empty_bridge_exits_silently(self):
        """Bridge with no nodes exits silently."""
        bridge = DeltaGraphBridge()
        summary = self._build_summary(bridge)
        self.assertIsNone(summary)

    def test_cross_file_deps_in_output(self):
        """Cross-file deps listed in output."""
        bridge = _make_bridge_with_cross_deps()
        summary = self._build_summary(bridge)
        self.assertIsNotNone(summary)
        self.assertIn("Cross-file dep", summary)


# ---- on_file_change tests (unit-level, testing main logic flow) ----

class TestOnFileChangeLogic(unittest.TestCase):
    """Tests for on_file_change.py logic via direct bridge operations."""

    def test_edit_produces_ops(self):
        """Editing a file produces graph operations."""
        bridge = _make_bridge_with_file("test.py", "def old_func():\n    pass\n")
        ops = bridge.process_change(CodeChange(
            file_path="test.py",
            old_content="def old_func():\n    pass\n",
            new_content="def new_func(x):\n    return x\n",
        ))
        self.assertGreater(len(ops), 0)

    def test_non_semantic_change_no_ops(self):
        """Whitespace-only change produces no operations."""
        bridge = _make_bridge_with_file("test.py", "def foo():\n    pass\n")
        ops = bridge.process_change(CodeChange(
            file_path="test.py",
            old_content="def foo():\n    pass\n",
            new_content="def foo():\n    pass\n\n",
        ))
        self.assertEqual(len(ops), 0)

    def test_affected_files_reported(self):
        """Affected files are reported after change."""
        bridge = _make_bridge_with_cross_deps()
        ops = bridge.process_change(CodeChange(
            file_path="a.py",
            old_content="def foo():\n    pass\n\ndef bar():\n    foo()\n",
            new_content="def foo(x):\n    return x\n\ndef bar():\n    foo()\n",
        ))
        self.assertGreater(len(ops), 0)
        affected = set()
        for op in ops:
            name = op.properties.get("name", "")
            if name:
                affected.update(bridge.get_affected_files("a.py", name))
        self.assertIn("b.py", affected)

    def test_unsupported_extension_skipped(self):
        """Unsupported extensions are not processed."""
        from streamrag.languages.registry import create_default_registry
        registry = create_default_registry()
        self.assertFalse(registry.can_handle("README.md"))
        self.assertTrue(registry.can_handle("test.py"))


# ---- pre_explore_redirect tests ----

class TestPreExploreRedirect(unittest.TestCase):
    """Tests for the pre_explore_redirect.py hook."""

    @staticmethod
    def _main_fn():
        """Import and call pre_explore_redirect.main() with signal mocks."""
        import importlib
        if 'pre_explore_redirect' in sys.modules:
            mod = importlib.reload(sys.modules['pre_explore_redirect'])
        else:
            with patch('signal.signal'), patch('signal.alarm'):
                import pre_explore_redirect as mod
        mod.main()

    def test_explore_with_relationship_prompt_augments(self):
        """Task/Explore with 'what calls foo' augments with graph context."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "Explore",
                    "prompt": "what calls foo",
                    "description": "find callers",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertNotIn("decision", result)
        msg = result.get("systemMessage", "")
        self.assertIn("[StreamRAG]", msg)
        # Auto-executed: actual callers output
        self.assertIn("Callers of foo", msg)
        self.assertIn("bar", msg)

    def test_explore_with_text_prompt_allowed(self):
        """Task/Explore with text search prompt is allowed (empty output)."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "Explore",
                    "prompt": "find all TODO comments in the codebase",
                    "description": "search TODOs",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_explore_non_explore_agent_allowed(self):
        """Task with subagent_type='Bash' is allowed (empty output)."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "Bash",
                    "prompt": "what calls process_change",
                    "description": "run command",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_grep_call_pattern_returns_callers(self):
        """Grep with pattern 'foo\\(' augments with actual callers output."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Grep",
                "tool_input": {
                    "pattern": "foo\\(",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        # Graph answered successfully -- augments grep with context
        self.assertNotIn("decision", result)
        self.assertIn("systemMessage", result)
        msg = result["systemMessage"]
        self.assertIn("[StreamRAG]", msg)
        # Auto-executed: actual callers output
        self.assertIn("Callers of foo", msg)
        self.assertIn("bar", msg)

    def test_grep_import_pattern_returns_rdeps(self):
        """Grep with pattern 'from models import' augments with rdeps output."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Grep",
                "tool_input": {
                    "pattern": "from models import",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        # Graph command executed -- augments grep with context
        self.assertNotIn("decision", result)
        self.assertIn("systemMessage", result)
        msg = result["systemMessage"]
        self.assertIn("[StreamRAG]", msg)
        self.assertIn("models", msg)

    def test_grep_text_pattern_allowed(self):
        """Grep with pattern 'TODO' is allowed (empty output)."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Grep",
                "tool_input": {
                    "pattern": "TODO",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_no_graph_allows_everything(self):
        """No graph (bridge=None) allows both Explore and Grep."""
        with patch('signal.signal'), patch('signal.alarm'):
            explore_result = _capture_hook_output(self._main_fn, {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "Explore",
                    "prompt": "what calls foo",
                    "description": "find callers",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=None)
        self.assertEqual(explore_result, {})

        with patch('signal.signal'), patch('signal.alarm'):
            grep_result = _capture_hook_output(self._main_fn, {
                "tool_name": "Grep",
                "tool_input": {
                    "pattern": "foo\\(",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=None)
        self.assertEqual(grep_result, {})

    def test_explore_verbose_prompt_caught(self):
        """Verbose 'find all usages of foo' is caught and augments with callers."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "Explore",
                    "prompt": "find all usages of foo in the codebase",
                    "description": "search usages",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertNotIn("decision", result)
        msg = result.get("systemMessage", "")
        self.assertIn("[StreamRAG]", msg)
        # Auto-executed callers query for 'foo'
        self.assertIn("Callers of foo", msg)

    def test_explore_deps_prompt_augments(self):
        """'what depends on a.py' augments with actual rdeps results."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "Explore",
                    "prompt": "what depends on a.py",
                    "description": "find deps",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertNotIn("decision", result)
        msg = result.get("systemMessage", "")
        self.assertIn("[StreamRAG]", msg)
        # Auto-executed: rdeps of a.py shows b.py depends on it
        self.assertIn("b.py", msg)

    def test_explore_impact_prompt_augments(self):
        """'impact of a.py' augments with actual impact results."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "Explore",
                    "prompt": "impact of a.py",
                    "description": "impact analysis",
                },
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertNotIn("decision", result)
        msg = result.get("systemMessage", "")
        self.assertIn("[StreamRAG]", msg)
        # Auto-executed: impact of a.py shows b.py is affected
        self.assertIn("b.py", msg)


# ---- pre_user_prompt tests ----

class TestPreUserPrompt(unittest.TestCase):
    """Tests for the pre_user_prompt.py hook."""

    @staticmethod
    def _main_fn():
        """Import and call pre_user_prompt.main() with signal mocks."""
        import importlib
        if 'pre_user_prompt' in sys.modules:
            mod = importlib.reload(sys.modules['pre_user_prompt'])
        else:
            with patch('signal.signal'), patch('signal.alarm'):
                import pre_user_prompt as mod
        mod.main()

    def test_relationship_query_returns_context(self):
        """User prompt 'what calls foo' returns graph context."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "hook_event_name": "UserPromptSubmit",
                "user_prompt": "what calls foo",
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertIn("systemMessage", result)
        msg = result["systemMessage"]
        self.assertIn("[StreamRAG]", msg)
        self.assertIn("foo", msg)

    def test_non_relationship_prompt_with_entity_mention(self):
        """User prompt mentioning entity name returns entity context."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "hook_event_name": "UserPromptSubmit",
                "user_prompt": "I want to refactor the foo function",
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertIn("systemMessage", result)
        msg = result["systemMessage"]
        self.assertIn("[StreamRAG]", msg)
        self.assertIn("foo", msg)

    def test_non_code_prompt_returns_empty(self):
        """Non-code prompt returns empty output."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "hook_event_name": "UserPromptSubmit",
                "user_prompt": "hello how are you",
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_short_prompt_exits_silently(self):
        """Very short prompt exits without output."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "hook_event_name": "UserPromptSubmit",
                "user_prompt": "hi",
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_wrong_event_exits_silently(self):
        """Non-UserPromptSubmit event exits silently."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "hook_event_name": "PreToolUse",
                "user_prompt": "what calls foo",
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertEqual(result, {})

    def test_no_graph_returns_empty(self):
        """No graph loaded returns empty output."""
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "hook_event_name": "UserPromptSubmit",
                "user_prompt": "what calls foo",
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=None)
        self.assertEqual(result, {})

    def test_impact_query_returns_context(self):
        """Impact analysis query returns affected files."""
        bridge = _make_bridge_with_cross_deps()
        with patch('signal.signal'), patch('signal.alarm'):
            result = _capture_hook_output(self._main_fn, {
                "hook_event_name": "UserPromptSubmit",
                "user_prompt": "what would be affected if I change a.py",
                "session_id": "test",
                "project_path": "/tmp/test",
            }, bridge=bridge)
        self.assertIn("systemMessage", result)
        msg = result["systemMessage"]
        self.assertIn("[StreamRAG]", msg)


if __name__ == "__main__":
    unittest.main()
