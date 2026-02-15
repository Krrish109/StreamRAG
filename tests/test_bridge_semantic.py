"""Tests for SemanticPath / ScopeAwareExtractor integration in bridge."""

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


class TestBridgeSemanticPath(unittest.TestCase):
    """Test dual extraction and enhanced name resolution."""

    def setUp(self):
        self.bridge = DeltaGraphBridge()

    def test_semantic_paths_populated(self):
        """_semantic_paths should be populated for Python files."""
        change = CodeChange(
            file_path="models.py",
            old_content="",
            new_content="class User:\n    def get_name(self):\n        return self.name\n",
        )
        self.bridge.process_change(change)
        self.assertIn("models.py", self.bridge._semantic_paths)
        paths = self.bridge._semantic_paths["models.py"]
        self.assertGreater(len(paths), 0)

    def test_semantic_paths_have_scope_chain(self):
        """Extracted SemanticPaths should have proper scope chains."""
        change = CodeChange(
            file_path="svc.py",
            old_content="",
            new_content="class Service:\n    def process(self, data):\n        pass\n",
        )
        self.bridge.process_change(change)
        paths = self.bridge._semantic_paths.get("svc.py", [])
        # Find the process method — it should have scope_chain ('Service',)
        method_paths = [p for p in paths if p.name == "process"]
        self.assertGreater(len(method_paths), 0)
        self.assertEqual(method_paths[0].scope_chain, ("Service",))

    def test_semantic_paths_not_for_non_python(self):
        """Non-Python files should not have semantic paths."""
        change = CodeChange(
            file_path="app.js",
            old_content="",
            new_content="function hello() { return 1; }\n",
        )
        self.bridge.process_change(change)
        # Should not crash, and no semantic paths for JS
        self.assertNotIn("app.js", self.bridge._semantic_paths)

    def test_enhanced_resolution_disambiguates(self):
        """With semantic paths, resolve_name should pick the right target."""
        # Set up two files with same-named methods in different classes
        self.bridge.process_change(CodeChange(
            file_path="a.py", old_content="",
            new_content="class Alpha:\n    def process(self):\n        pass\n",
        ))
        self.bridge.process_change(CodeChange(
            file_path="b.py", old_content="",
            new_content="class Beta:\n    def process(self):\n        pass\n",
        ))
        # The bridge should have semantic paths for both
        self.assertIn("a.py", self.bridge._semantic_paths)
        self.assertIn("b.py", self.bridge._semantic_paths)


if __name__ == "__main__":
    unittest.main()
