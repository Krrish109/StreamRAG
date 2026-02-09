"""End-to-end integration tests for V1."""

import time

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange


def test_full_workflow():
    """Complete workflow: create, modify, rename, delete across files."""
    bridge = DeltaGraphBridge()

    # File A: initial
    code_a = """
def compute(x):
    return x * 2

def validate(data):
    return len(data) > 0
"""
    bridge.process_change(CodeChange("a.py", "", code_a))
    assert bridge.graph.node_count == 2

    # File B: depends on A
    code_b = """
def process(items):
    if validate(items):
        return [compute(i) for i in items]
    return []
"""
    bridge.process_change(CodeChange("b.py", "", code_b))
    assert bridge.graph.node_count == 3
    assert bridge.graph.edge_count >= 1  # process -> compute/validate

    # Modify compute in A
    code_a_v2 = """
def compute(x):
    return x * 3

def validate(data):
    return len(data) > 0
"""
    ops = bridge.process_change(CodeChange("a.py", code_a, code_a_v2))
    assert len(ops) == 1  # Only compute changed
    assert ops[0].op_type == "update_node"

    # Rename validate -> check in A
    code_a_v3 = """
def compute(x):
    return x * 3

def check(data):
    return len(data) > 0
"""
    ops = bridge.process_change(CodeChange("a.py", code_a_v2, code_a_v3))
    rename_ops = [op for op in ops if op.properties.get("renamed_from")]
    assert len(rename_ops) == 1
    assert rename_ops[0].properties["renamed_from"] == "validate"

    # Add new file C
    code_c = """
from a import compute

def transform(values):
    return [compute(v) for v in values]
"""
    bridge.process_change(CodeChange("c.py", "", code_c))
    assert bridge.graph.node_count >= 5  # nodes from a, b, c

    # Verify ripple detection
    affected = bridge.get_affected_files("a.py", "compute")
    assert "b.py" in affected or "c.py" in affected


def test_performance_cold_start():
    """100-function file cold start should be fast."""
    bridge = DeltaGraphBridge()
    lines = []
    for i in range(100):
        lines.append(f"def func_{i}(x):")
        lines.append(f"    return x + {i}")
        lines.append("")
    code = "\n".join(lines)

    start = time.perf_counter()
    bridge.process_change(CodeChange("big.py", "", code))
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert bridge.graph.node_count == 100
    assert elapsed_ms < 500, f"Cold start took {elapsed_ms:.1f}ms, expected < 500ms"


def test_graph_hash_consistency():
    """Same changes produce same graph hash."""
    bridge1 = DeltaGraphBridge()
    bridge2 = DeltaGraphBridge()

    code = "def foo():\n    return 1\n\ndef bar():\n    foo()\n"
    bridge1.process_change(CodeChange("test.py", "", code))
    bridge2.process_change(CodeChange("test.py", "", code))

    assert bridge1.graph.compute_hash() == bridge2.graph.compute_hash()


def test_empty_file_handling():
    """Empty files should be handled gracefully."""
    bridge = DeltaGraphBridge()
    ops = bridge.process_change(CodeChange("empty.py", "", ""))
    assert len(ops) == 0
    assert bridge.graph.node_count == 0


def test_multiple_files_independent():
    """Changes in one file don't affect unrelated files."""
    bridge = DeltaGraphBridge()

    code_a = "def foo():\n    return 1\n"
    code_b = "def bar():\n    return 2\n"
    bridge.process_change(CodeChange("a.py", "", code_a))
    bridge.process_change(CodeChange("b.py", "", code_b))

    # Modify A only
    code_a_v2 = "def foo():\n    return 42\n"
    ops = bridge.process_change(CodeChange("a.py", code_a, code_a_v2))

    assert len(ops) == 1
    # B's node should still be there
    b_nodes = bridge.graph.query(file_path="b.py")
    assert len(b_nodes) == 1
