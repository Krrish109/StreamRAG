"""Tests for OperationBatch integration in bridge.process_change."""

import os
import sys
import unittest

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_dir = os.path.dirname(PLUGIN_ROOT)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)
os.environ.setdefault("CLAUDE_PLUGIN_ROOT", PLUGIN_ROOT)

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange


class TestBridgeOperationBatch(unittest.TestCase):
    """Test that process_change populates _op_log with V2 GraphOps."""

    def setUp(self):
        self.bridge = DeltaGraphBridge()

    def test_op_log_populated_on_add(self):
        """Adding a new function should populate _op_log with AddNode."""
        change = CodeChange(
            file_path="foo.py",
            old_content="",
            new_content="def hello():\n    pass\n",
        )
        self.bridge.process_change(change)
        self.assertGreater(len(self.bridge._op_log), 0)
        # Check that at least one op is an AddNode
        from streamrag.v2.operations import AddNode
        add_ops = [op for op in self.bridge._op_log if isinstance(op, AddNode)]
        self.assertGreater(len(add_ops), 0)

    def test_op_log_populated_on_remove(self):
        """Removing a function should add RemoveNode to _op_log."""
        self.bridge.process_change(CodeChange(
            file_path="foo.py", old_content="",
            new_content="def hello():\n    pass\n\ndef goodbye():\n    pass\n",
        ))
        self.bridge._op_log.clear()

        self.bridge.process_change(CodeChange(
            file_path="foo.py",
            old_content="def hello():\n    pass\n\ndef goodbye():\n    pass\n",
            new_content="def hello():\n    pass\n",
        ))
        from streamrag.v2.operations import RemoveNode
        remove_ops = [op for op in self.bridge._op_log if isinstance(op, RemoveNode)]
        self.assertGreater(len(remove_ops), 0)

    def test_op_log_populated_on_modify(self):
        """Modifying a function body should add UpdateNode to _op_log."""
        self.bridge.process_change(CodeChange(
            file_path="foo.py", old_content="",
            new_content="def hello():\n    pass\n",
        ))
        self.bridge._op_log.clear()

        self.bridge.process_change(CodeChange(
            file_path="foo.py",
            old_content="def hello():\n    pass\n",
            new_content="def hello():\n    return 42\n",
        ))
        from streamrag.v2.operations import UpdateNode
        update_ops = [op for op in self.bridge._op_log if isinstance(op, UpdateNode)]
        self.assertGreater(len(update_ops), 0)

    def test_last_batch_set(self):
        """_last_batch should be set after process_change with semantic change."""
        change = CodeChange(
            file_path="bar.py", old_content="",
            new_content="class Foo:\n    pass\n",
        )
        self.bridge.process_change(change)
        from streamrag.v2.operations import OperationBatch
        self.assertIsInstance(self.bridge._last_batch, OperationBatch)

    def test_op_log_cleared_per_file(self):
        """_op_log should accumulate across calls (not clear per call)."""
        self.bridge.process_change(CodeChange(
            file_path="a.py", old_content="",
            new_content="def a():\n    pass\n",
        ))
        count_after_first = len(self.bridge._op_log)

        self.bridge.process_change(CodeChange(
            file_path="b.py", old_content="",
            new_content="def b():\n    pass\n",
        ))
        self.assertGreater(len(self.bridge._op_log), count_after_first)


if __name__ == "__main__":
    unittest.main()
