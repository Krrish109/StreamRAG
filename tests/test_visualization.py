"""Tests for visualization commands in query_graph.py."""

import os
import sys
import unittest
from io import StringIO
from contextlib import redirect_stdout

# Add scripts to path for query_graph import
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
scripts_dir = os.path.join(PLUGIN_ROOT, "scripts")
parent_dir = os.path.dirname(PLUGIN_ROOT)
for d in [parent_dir, PLUGIN_ROOT, scripts_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange
import query_graph as qg


def _make_bridge():
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


class TestCmdVisualize(unittest.TestCase):
    """Test cmd_visualize."""

    def test_file_deps_mermaid(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_visualize(bridge, ["app.py", "--format", "mermaid"])
        output = buf.getvalue()
        self.assertIn("graph LR", output)
        self.assertIn("mermaid", output)

    def test_file_deps_dot(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_visualize(bridge, ["app.py", "--format", "dot"])
        output = buf.getvalue()
        self.assertIn("digraph", output)

    def test_entity_call_graph(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_visualize(bridge, ["main", "--type", "entity"])
        output = buf.getvalue()
        self.assertIn("mermaid", output)

    def test_no_target_file_shows_all(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_visualize(bridge, ["--format", "mermaid"])
        output = buf.getvalue()
        self.assertIn("graph LR", output)

    def test_unknown_type(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_visualize(bridge, ["app.py", "--type", "bogus"])
        output = buf.getvalue()
        self.assertIn("Unknown visualization type", output)


class TestCmdSummary(unittest.TestCase):
    """Test cmd_summary."""

    def test_summary_output(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_summary(bridge, [])
        output = buf.getvalue()
        self.assertIn("Architecture Summary", output)
        self.assertIn("Entities:", output)
        self.assertIn("Edges:", output)
        self.assertIn("Files:", output)

    def test_summary_shows_types(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_summary(bridge, [])
        output = buf.getvalue()
        self.assertIn("function:", output)

    def test_summary_empty_graph(self):
        bridge = DeltaGraphBridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_summary(bridge, [])
        output = buf.getvalue()
        self.assertIn("Entities: 0", output)


class TestCmdAsk(unittest.TestCase):
    """Test cmd_ask routing."""

    def test_ask_callers(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_ask(bridge, ["who", "calls", "helper"])
        output = buf.getvalue()
        self.assertIn("helper", output)

    def test_ask_no_args(self):
        bridge = _make_bridge()
        buf = StringIO()
        with redirect_stdout(buf):
            qg.cmd_ask(bridge, [])
        output = buf.getvalue()
        self.assertIn("Usage", output)


if __name__ == "__main__":
    unittest.main()
