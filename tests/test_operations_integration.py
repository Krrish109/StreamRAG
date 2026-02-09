"""Tests for V2 operations layer integration in bridge."""

import unittest

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange


class TestOperationsIntegration(unittest.TestCase):
    """Test V2 operations (op_log, last_batch) on bridge."""

    def test_op_log_empty_initially(self):
        bridge = DeltaGraphBridge()
        self.assertEqual(bridge._op_log, [])

    def test_last_batch_none_initially(self):
        bridge = DeltaGraphBridge()
        self.assertIsNone(bridge._last_batch)

    def test_process_change_populates_operations(self):
        """process_change still returns V1 GraphOperation list."""
        bridge = DeltaGraphBridge()
        ops = bridge.process_change(CodeChange(
            file_path="test.py", old_content="",
            new_content="def foo():\n    pass\n",
        ))
        self.assertGreater(len(ops), 0)
        self.assertEqual(ops[0].op_type, "add_node")

    def test_had_callers_on_removal(self):
        """Removed entities capture had_callers for proactive warnings."""
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="a.py", old_content="",
            new_content="def target():\n    pass\n",
        ))
        bridge.process_change(CodeChange(
            file_path="b.py", old_content="",
            new_content="from a import target\n\ndef caller():\n    target()\n",
        ))
        # Now remove target (use different body to avoid rename detection)
        ops = bridge.process_change(CodeChange(
            file_path="a.py",
            old_content="def target():\n    pass\n",
            new_content="def other(x):\n    return x\n",
        ))
        removal_ops = [op for op in ops if op.op_type == "remove_node"]
        # Should have at least one removal with had_callers
        callers_found = any(op.properties.get("had_callers") for op in removal_ops)
        self.assertTrue(callers_found)


class TestVersionedIntegration(unittest.TestCase):
    """Test versioned graph integration in bridge."""

    def test_version_zero_without_versioned(self):
        bridge = DeltaGraphBridge()
        self.assertEqual(bridge.version, 0)

    def test_version_increments_with_versioned(self):
        bridge = DeltaGraphBridge(versioned=True)
        self.assertEqual(bridge.version, 0)
        bridge.process_change(CodeChange(
            file_path="test.py", old_content="",
            new_content="def foo():\n    pass\n",
        ))
        self.assertGreater(bridge.version, 0)

    def test_versioned_persists_through_serialization(self):
        """Versioned state round-trips through serialize/deserialize."""
        from streamrag.storage.memory import serialize_graph, deserialize_graph
        bridge = DeltaGraphBridge(versioned=True)
        bridge.process_change(CodeChange(
            file_path="test.py", old_content="",
            new_content="def foo():\n    pass\n",
        ))
        v = bridge.version
        self.assertGreater(v, 0)

        data = serialize_graph(bridge)
        self.assertIn("graph_version", data)
        self.assertEqual(data["graph_version"], v)

        restored = deserialize_graph(data)
        self.assertIsNotNone(restored._versioned)
        self.assertEqual(restored.version, v)


class TestPropagationIntegration(unittest.TestCase):
    """Test hierarchical graph + propagator integration."""

    def test_hierarchical_none_by_default(self):
        bridge = DeltaGraphBridge()
        self.assertIsNone(bridge._hierarchical)

    def test_propagator_none_by_default(self):
        bridge = DeltaGraphBridge()
        self.assertIsNone(bridge._propagator)

    def test_hierarchical_tracks_files(self):
        from streamrag.v2.hierarchical_graph import HierarchicalGraph
        bridge = DeltaGraphBridge()
        bridge._hierarchical = HierarchicalGraph(graph=bridge.graph)
        bridge.process_change(CodeChange(
            file_path="test.py", old_content="",
            new_content="def foo():\n    pass\n",
        ))
        # File should be tracked in hierarchical graph
        from streamrag.v2.hierarchical_graph import Zone
        self.assertEqual(bridge._hierarchical.get_zone("test.py"), Zone.HOT)


class TestProactiveIntelligence(unittest.TestCase):
    """Test proactive intelligence methods on bridge."""

    def test_check_new_cycles_empty(self):
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="a.py", old_content="",
            new_content="def foo():\n    pass\n",
        ))
        cycles = bridge.check_new_cycles("a.py")
        self.assertEqual(cycles, [])

    def test_check_new_dead_code(self):
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="a.py", old_content="",
            new_content="def unused_func():\n    pass\n\ndef another():\n    pass\n",
        ))
        dead = bridge.check_new_dead_code("a.py")
        names = [n.name for n in dead]
        self.assertIn("unused_func", names)

    def test_check_new_dead_code_filters_file(self):
        """Only returns dead code from the specified file."""
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="a.py", old_content="",
            new_content="def foo():\n    pass\n",
        ))
        bridge.process_change(CodeChange(
            file_path="b.py", old_content="",
            new_content="def bar():\n    pass\n",
        ))
        dead = bridge.check_new_dead_code("a.py")
        for n in dead:
            self.assertEqual(n.file_path, "a.py")


if __name__ == "__main__":
    unittest.main()
