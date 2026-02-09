"""Tests for smart_query.py — natural language query routing."""

import unittest

from streamrag.smart_query import parse_query, execute_query
from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange


class TestParseQuery(unittest.TestCase):
    """Test NL pattern matching."""

    def test_who_calls(self):
        result = parse_query("who calls process_change")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "callers")
        self.assertEqual(result[1], ["process_change"])

    def test_what_calls(self):
        result = parse_query("what calls foo")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "callers")

    def test_callers_of(self):
        result = parse_query("callers of foo")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "callers")
        self.assertEqual(result[1], ["foo"])

    def test_where_is_called(self):
        result = parse_query("where is foo called")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "callers")

    def test_what_does_call(self):
        result = parse_query("what does foo call")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "callees")
        self.assertEqual(result[1], ["foo"])

    def test_callees_of(self):
        result = parse_query("callees of bar")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "callees")

    def test_dependencies(self):
        result = parse_query("dependencies of bridge.py")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deps")

    def test_what_depends_on(self):
        result = parse_query("what depends on models.py")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "rdeps")
        self.assertEqual(result[1], ["models.py"])

    def test_reverse_deps(self):
        result = parse_query("reverse dependencies of graph.py")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "rdeps")

    def test_impact(self):
        result = parse_query("impact of models.py")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "impact")
        self.assertEqual(result[1], ["models.py"])

    def test_affected_by_change(self):
        result = parse_query("what would be affected if I change bridge.py")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "impact")

    def test_dead_code(self):
        result = parse_query("find dead code")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "dead")
        self.assertEqual(result[1], [])

    def test_unused_functions(self):
        result = parse_query("unused functions")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "dead")

    def test_cycles(self):
        result = parse_query("circular dependencies")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "cycles")

    def test_find_cycles(self):
        result = parse_query("find cycles")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "cycles")

    def test_path(self):
        result = parse_query("path from foo to bar")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "path")
        self.assertEqual(result[1], ["foo", "bar"])

    def test_how_connected(self):
        result = parse_query("how is foo connected to bar")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "path")

    def test_search(self):
        result = parse_query("search test_.*")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "search")
        self.assertEqual(result[1], ["test_.*"])

    def test_find_entities(self):
        result = parse_query("find entities matching process")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "search")

    def test_summary(self):
        result = parse_query("summary")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "summary")

    def test_architecture(self):
        result = parse_query("architecture")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "summary")

    def test_visualize(self):
        result = parse_query("visualize bridge.py")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "visualize")

    def test_exports(self):
        result = parse_query("exports of models.py")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "exports")

    def test_question_mark_stripped(self):
        result = parse_query("who calls foo?")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "callers")

    def test_unrecognized_returns_none(self):
        result = parse_query("make me a sandwich")
        self.assertIsNone(result)


class TestExecuteQuery(unittest.TestCase):
    """Test end-to-end NL query execution."""

    def _make_bridge(self):
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="app.py", old_content="",
            new_content="from lib import helper\n\ndef main():\n    helper()\n",
        ))
        bridge.process_change(CodeChange(
            file_path="lib.py", old_content="",
            new_content="def helper():\n    pass\n",
        ))
        return bridge

    def test_callers_query(self):
        bridge = self._make_bridge()
        result = execute_query(bridge, "who calls helper")
        self.assertIn("helper", result)

    def test_dead_code_query(self):
        bridge = self._make_bridge()
        result = execute_query(bridge, "find dead code")
        self.assertIn("dead code", result.lower())

    def test_unknown_query_shows_help(self):
        bridge = self._make_bridge()
        result = execute_query(bridge, "make me a sandwich")
        self.assertIn("Could not understand", result)
        self.assertIn("Try questions like", result)

    def test_summary_query(self):
        bridge = self._make_bridge()
        result = execute_query(bridge, "summary")
        self.assertIn("Summary", result)


if __name__ == "__main__":
    unittest.main()
