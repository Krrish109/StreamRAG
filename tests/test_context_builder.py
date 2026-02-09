"""Tests for agent/context_builder.py — rich context formatting."""

import unittest

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange
from streamrag.agent.context_builder import (
    get_context_for_file,
    get_entity_signature,
    format_rich_context,
    format_graph_summary,
    _format_affected_with_grouping,
)


class TestGetContextForFile(unittest.TestCase):
    """Test get_context_for_file produces correct structure."""

    def _make_bridge(self):
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="app.py", old_content="",
            new_content=(
                "from lib import helper\n\n"
                "class App:\n    def run(self, x: int) -> str:\n        helper()\n"
            ),
        ))
        bridge.process_change(CodeChange(
            file_path="lib.py", old_content="",
            new_content="def helper():\n    pass\n",
        ))
        return bridge

    def test_basic_structure(self):
        bridge = self._make_bridge()
        ctx = get_context_for_file(bridge, "app.py")
        self.assertEqual(ctx["file_path"], "app.py")
        self.assertIn("entity_count", ctx)
        self.assertIn("entities", ctx)
        self.assertIn("affected_files", ctx)
        self.assertGreater(ctx["entity_count"], 0)

    def test_entities_have_params(self):
        bridge = self._make_bridge()
        ctx = get_context_for_file(bridge, "app.py")
        run_ents = [e for e in ctx["entities"] if e["name"] == "App.run"]
        self.assertEqual(len(run_ents), 1)
        self.assertIn("params", run_ents[0])
        self.assertIn("x", run_ents[0]["params"])

    def test_entities_have_type_refs(self):
        bridge = self._make_bridge()
        ctx = get_context_for_file(bridge, "app.py")
        run_ents = [e for e in ctx["entities"] if e["name"] == "App.run"]
        self.assertEqual(len(run_ents), 1)
        self.assertIn("type_refs", run_ents[0])

    def test_calls_out_includes_target_file(self):
        bridge = self._make_bridge()
        ctx = get_context_for_file(bridge, "app.py")
        all_calls = []
        for e in ctx["entities"]:
            all_calls.extend(e.get("calls_out", []))
        # Should have at least one call with a target_file
        files = [c["target_file"] for c in all_calls if c.get("target_file")]
        self.assertTrue(len(files) > 0)

    def test_called_by_includes_source_file(self):
        bridge = self._make_bridge()
        ctx = get_context_for_file(bridge, "lib.py")
        all_callers = []
        for e in ctx["entities"]:
            all_callers.extend(e.get("called_by", []))
        files = [c["source_file"] for c in all_callers if c.get("source_file")]
        self.assertTrue(len(files) > 0)

    def test_affected_files(self):
        bridge = self._make_bridge()
        ctx = get_context_for_file(bridge, "lib.py")
        # app.py depends on lib.py, so it should be affected
        self.assertIn("app.py", ctx["affected_files"])

    def test_empty_file(self):
        bridge = DeltaGraphBridge()
        ctx = get_context_for_file(bridge, "nonexistent.py")
        self.assertEqual(ctx["entity_count"], 0)
        self.assertEqual(ctx["entities"], [])


class TestGetEntitySignature(unittest.TestCase):
    """Test signature reconstruction."""

    def test_function_with_params_and_return(self):
        sig = get_entity_signature({
            "name": "process",
            "type": "function",
            "params": ["x", "y"],
            "type_refs": ["int"],
            "lines": "10-20",
        })
        # type_refs contains ALL annotations (params + return), not just return type,
        # so we don't guess which one is the return type
        self.assertEqual(sig, "def process(x, y)  L10-20")

    def test_function_no_params(self):
        sig = get_entity_signature({
            "name": "init",
            "type": "function",
            "params": [],
            "type_refs": [],
            "lines": "1-5",
        })
        self.assertEqual(sig, "def init()  L1-5")

    def test_class(self):
        sig = get_entity_signature({
            "name": "MyClass",
            "type": "class",
            "lines": "1-50",
        })
        self.assertEqual(sig, "class MyClass  L1-50")

    def test_import(self):
        sig = get_entity_signature({
            "name": "os",
            "type": "import",
        })
        self.assertEqual(sig, "import os")

    def test_no_lines(self):
        sig = get_entity_signature({
            "name": "foo",
            "type": "function",
            "params": [],
        })
        self.assertEqual(sig, "def foo()")


class TestFormatRichContext(unittest.TestCase):
    """Test budget-aware multi-tier formatter."""

    def _make_context(self, **overrides):
        ctx = {
            "file_path": "src/app.py",
            "entity_count": 3,
            "entities": [
                {
                    "name": "App",
                    "type": "class",
                    "line_start": 1,
                    "line_end": 50,
                    "lines": "1-50",
                    "params": [],
                    "type_refs": [],
                    "calls_out": [],
                    "called_by": [],
                },
                {
                    "name": "run",
                    "type": "function",
                    "line_start": 10,
                    "line_end": 30,
                    "lines": "10-30",
                    "params": ["x", "y"],
                    "type_refs": ["str"],
                    "calls_out": [
                        {"target": "helper", "type": "imports", "confidence": "", "target_file": "lib.py"},
                    ],
                    "called_by": [
                        {"source": "test_app", "type": "calls", "confidence": "high", "source_file": "tests/test_app.py"},
                    ],
                },
                {
                    "name": "init",
                    "type": "function",
                    "line_start": 5,
                    "line_end": 9,
                    "lines": "5-9",
                    "params": [],
                    "type_refs": [],
                    "calls_out": [],
                    "called_by": [],
                },
            ],
            "affected_files": ["tests/test_app.py", "main.py"],
        }
        ctx.update(overrides)
        return ctx

    def test_header_present(self):
        result = format_rich_context(self._make_context())
        self.assertIn("[StreamRAG] app.py:", result)

    def test_entity_counts(self):
        result = format_rich_context(self._make_context())
        self.assertIn("2fn", result)
        self.assertIn("1cls", result)

    def test_cross_file_callers_present(self):
        result = format_rich_context(self._make_context())
        # Multi-line format includes cross-file caller info
        self.assertIn("Called by:", result)
        self.assertIn("run", result)
        self.assertIn("test_app.py", result)

    def test_affected_shows_basenames(self):
        result = format_rich_context(self._make_context())
        # Affected files now shows actual basenames, not just count
        self.assertIn("Affected:", result)
        self.assertIn("test_app.py", result)
        self.assertIn("main.py", result)

    def test_deps_present(self):
        result = format_rich_context(self._make_context())
        # Dependencies section shows files called out to
        self.assertIn("Deps:", result)
        self.assertIn("lib.py", result)

    def test_budget_limits_output(self):
        result = format_rich_context(self._make_context(), max_chars=100)
        # Should at least have the header
        self.assertIn("[StreamRAG] app.py:", result)

    def test_empty_entities(self):
        ctx = self._make_context(entities=[], entity_count=0)
        result = format_rich_context(ctx)
        self.assertIn("[StreamRAG] app.py", result)

    def test_no_affected(self):
        ctx = self._make_context(affected_files=[])
        result = format_rich_context(ctx)
        self.assertNotIn("Affected:", result)

    def test_multi_line_format(self):
        result = format_rich_context(self._make_context())
        # Should be multi-line format with sections
        self.assertIn("\n", result)
        self.assertIn("Called by:", result)

    def test_no_cross_file_callers_omits_section(self):
        ctx = self._make_context()
        # Remove all callers
        for e in ctx["entities"]:
            e["called_by"] = []
        result = format_rich_context(ctx)
        self.assertNotIn("Called by:", result)


class TestKeyEntities(unittest.TestCase):
    """Test Key entities section in format_rich_context."""

    def _make_context_with_keys(self):
        return {
            "file_path": "src/api.py",
            "entity_count": 4,
            "entities": [
                {
                    "name": "AgenticModel",
                    "type": "class",
                    "line_start": 15,
                    "line_end": 420,
                    "lines": "15-420",
                    "params": [],
                    "type_refs": [],
                    "calls_out": [],
                    "called_by": [
                        {"source": "fix_code", "type": "calls", "confidence": "high", "source_file": "code_fixer.py"},
                        {"source": "handle", "type": "calls", "confidence": "high", "source_file": "server.py"},
                    ],
                },
                {
                    "name": "chat_completion",
                    "type": "function",
                    "line_start": 429,
                    "line_end": 500,
                    "lines": "429-500",
                    "params": ["request"],
                    "type_refs": [],
                    "calls_out": [
                        {"target": "AgenticModel", "type": "calls", "confidence": "high", "target_file": "agentic_model.py"},
                    ],
                    "called_by": [
                        {"source": "register_routes", "type": "calls", "confidence": "high", "source_file": "server.py"},
                    ],
                },
                {
                    "name": "complete_stream",
                    "type": "function",
                    "line_start": 512,
                    "line_end": 600,
                    "lines": "512-600",
                    "params": ["model", "messages"],
                    "type_refs": [],
                    "calls_out": [],
                    "called_by": [],
                },
                {
                    "name": "os",
                    "type": "import",
                    "line_start": 1,
                    "line_end": 1,
                    "lines": "1-1",
                    "params": [],
                    "type_refs": [],
                    "calls_out": [],
                    "called_by": [],
                },
            ],
            "affected_files": ["server.py", "code_fixer.py"],
        }

    def test_key_entities_present(self):
        """Key entities section shows classes and functions with line numbers."""
        result = format_rich_context(self._make_context_with_keys())
        self.assertIn("Key:", result)
        # Classes should appear first
        self.assertIn("class AgenticModel", result)
        self.assertIn("L15", result)

    def test_key_entities_include_functions(self):
        """Key entities includes top functions."""
        result = format_rich_context(self._make_context_with_keys())
        self.assertIn("def chat_completion", result)

    def test_key_entities_skip_imports(self):
        """Key entities does not include imports."""
        result = format_rich_context(self._make_context_with_keys())
        self.assertNotIn("import os", result)

    def test_key_entities_classes_first(self):
        """Classes appear before functions in Key section."""
        result = format_rich_context(self._make_context_with_keys())
        key_line = [l for l in result.split('\n') if l.startswith('Key:')]
        self.assertEqual(len(key_line), 1)
        key_content = key_line[0]
        class_pos = key_content.find("class AgenticModel")
        func_pos = key_content.find("def chat_completion")
        self.assertGreater(func_pos, class_pos)


class TestFormatAffectedWithGrouping(unittest.TestCase):
    """Test module path grouping for affected files."""

    def test_no_grouping_few_files(self):
        """Fewer than 3 files in a dir are shown individually."""
        result = _format_affected_with_grouping(["server.py", "main.py"])
        self.assertIn("server.py", result)
        self.assertIn("main.py", result)

    def test_group_when_three_or_more(self):
        """3+ files in same directory are collapsed."""
        result = _format_affected_with_grouping([
            "llm/providers/fireworks.py",
            "llm/providers/google.py",
            "llm/providers/cerebras.py",
            "llm/providers/novita.py",
            "server.py",
        ])
        self.assertIn("llm/providers/", result)
        self.assertIn("4 files", result)
        self.assertIn("server.py", result)

    def test_empty_affected(self):
        """Empty affected list returns empty string."""
        result = _format_affected_with_grouping([])
        self.assertEqual(result, "")

    def test_truncation_with_plus_more(self):
        """Many individual files are truncated with +N more."""
        files = [f"dir{i}/file{i}.py" for i in range(10)]
        result = _format_affected_with_grouping(files)
        self.assertIn("+", result)
        self.assertIn("more", result)

    def test_no_grouping_no_parent(self):
        """Files with no parent directory are shown as basenames."""
        result = _format_affected_with_grouping(["a.py", "b.py"])
        self.assertIn("a.py", result)
        self.assertIn("b.py", result)


class TestFormatGraphSummary(unittest.TestCase):
    """Test format_graph_summary."""

    def test_summary_format(self):
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="a.py", old_content="",
            new_content="def foo():\n    pass\n\nclass Bar:\n    pass\n",
        ))
        result = format_graph_summary(bridge)
        self.assertIn("Code Graph:", result)
        self.assertIn("entities", result)
        self.assertIn("Files:", result)

    def test_empty_graph(self):
        bridge = DeltaGraphBridge()
        result = format_graph_summary(bridge)
        self.assertIn("0 entities", result)


if __name__ == "__main__":
    unittest.main()
