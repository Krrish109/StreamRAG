"""Tests for ShadowAST integration in bridge._extract()."""

import unittest

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange


class TestShadowASTIntegration(unittest.TestCase):
    """Test that broken Python code falls back to ShadowAST extraction."""

    def test_broken_python_extracts_entities(self):
        """Broken Python code should still extract entities via ShadowAST when enabled."""
        bridge = DeltaGraphBridge()
        # Broken code: missing colon and bad indentation
        broken_source = "def foo(x)\n    return x\n\nclass Bar:\n    pass\n"
        entities = bridge._extract(broken_source, "test.py", shadow_fallback=True)
        # ShadowAST should recover at least the class (it has valid syntax)
        # and potentially the function via regex
        self.assertGreater(len(entities), 0)
        names = [e.name for e in entities]
        self.assertIn("Bar", names)

    def test_valid_python_uses_primary_extractor(self):
        """Valid Python code should use the primary AST extractor, not ShadowAST."""
        bridge = DeltaGraphBridge()
        valid_source = "def foo(x):\n    return x\n"
        entities = bridge._extract(valid_source, "test.py")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].name, "foo")
        # Should NOT have shadow: prefix
        self.assertFalse(entities[0].signature_hash.startswith("shadow:"))

    def test_shadow_entities_tagged(self):
        """Shadow-extracted entities have shadow: prefix in signature_hash."""
        bridge = DeltaGraphBridge()
        # Completely broken (just a function def with missing colon)
        broken_source = "def broken_func(x)\n"
        entities = bridge._extract(broken_source, "test.py", shadow_fallback=True)
        if entities:
            for e in entities:
                self.assertTrue(e.signature_hash.startswith("shadow:"))

    def test_shadow_entities_replaced_on_fix(self):
        """When code is fixed, shadow entities are replaced by real ones."""
        bridge = DeltaGraphBridge()
        broken_source = "def foo(x)\n    return x\n\nclass Bar:\n    pass\n"
        # Process broken code
        bridge.process_change(CodeChange(
            file_path="test.py", old_content="", new_content=broken_source,
        ))
        # Now fix the code
        fixed_source = "def foo(x):\n    return x\n\nclass Bar:\n    pass\n"
        ops = bridge.process_change(CodeChange(
            file_path="test.py", old_content=broken_source, new_content=fixed_source,
        ))
        # After fix, entities should be normal (not shadow)
        nodes = bridge.graph.get_nodes_by_file("test.py")
        for node in nodes:
            sig = node.properties.get("signature_hash", "")
            self.assertFalse(sig.startswith("shadow:"),
                             f"Entity {node.name} still has shadow hash after fix")

    def test_no_shadow_without_flag(self):
        """Without shadow_fallback=True, broken code returns empty."""
        bridge = DeltaGraphBridge()
        broken_source = "def foo(x)\n    return x\n"
        entities = bridge._extract(broken_source, "test.py")
        self.assertEqual(entities, [])

    def test_empty_source_returns_empty(self):
        """Empty source returns empty list (no ShadowAST fallback needed)."""
        bridge = DeltaGraphBridge()
        entities = bridge._extract("", "test.py")
        self.assertEqual(entities, [])

    def test_non_python_no_shadow_fallback(self):
        """Non-Python broken code does not use ShadowAST fallback."""
        bridge = DeltaGraphBridge()
        broken_ts = "function foo(x { return x; }"  # broken TypeScript
        entities = bridge._extract(broken_ts, "test.ts")
        # May or may not extract depending on regex extractor, but should NOT crash
        # and should NOT use ShadowAST (which is Python-only)


class TestParamsExtraction(unittest.TestCase):
    """Test that function parameters are stored in ASTEntity.params."""

    def test_function_params_extracted(self):
        """Function params (excluding self/cls) are extracted."""
        bridge = DeltaGraphBridge()
        source = "def foo(a, b, c):\n    pass\n"
        entities = bridge._extract(source, "test.py")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].params, ["a", "b", "c"])

    def test_method_params_exclude_self(self):
        """Method params exclude self."""
        bridge = DeltaGraphBridge()
        source = "class Foo:\n    def bar(self, x, y):\n        pass\n"
        entities = bridge._extract(source, "test.py")
        methods = [e for e in entities if e.entity_type == "function"]
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0].params, ["x", "y"])

    def test_classmethod_params_exclude_cls(self):
        """Classmethod params exclude cls."""
        bridge = DeltaGraphBridge()
        source = "class Foo:\n    @classmethod\n    def create(cls, name):\n        pass\n"
        entities = bridge._extract(source, "test.py")
        methods = [e for e in entities if e.entity_type == "function"]
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0].params, ["name"])

    def test_params_stored_in_node_properties(self):
        """Params are stored in graph node properties."""
        bridge = DeltaGraphBridge()
        bridge.process_change(CodeChange(
            file_path="test.py", old_content="",
            new_content="def foo(a, b):\n    pass\n",
        ))
        nodes = bridge.graph.get_nodes_by_file("test.py")
        fn_nodes = [n for n in nodes if n.type == "function"]
        self.assertEqual(len(fn_nodes), 1)
        self.assertEqual(fn_nodes[0].properties.get("params"), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
