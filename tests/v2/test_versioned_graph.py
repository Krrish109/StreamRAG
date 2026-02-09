"""Tests for V2 versioned graph."""

from streamrag.models import GraphOperation
from streamrag.v2.versioned_graph import (
    VersionedGraph, AISessionManager, ConflictType,
)


def test_version_increments():
    vg = VersionedGraph()
    assert vg.version == 0
    op = GraphOperation(op_type="add_node", node_id="n1")
    v = vg.record_operation(op, "a.py")
    assert v == 1
    assert vg.version == 1


def test_file_version_tracking():
    vg = VersionedGraph()
    op1 = GraphOperation(op_type="add_node", node_id="n1")
    op2 = GraphOperation(op_type="add_node", node_id="n2")
    vg.record_operation(op1, "a.py")
    vg.record_operation(op2, "b.py")
    assert vg.get_file_version("a.py") == 1
    assert vg.get_file_version("b.py") == 2


def test_get_operations_since():
    vg = VersionedGraph()
    ops = [GraphOperation(op_type="add_node", node_id=f"n{i}") for i in range(5)]
    for op in ops:
        vg.record_operation(op)
    recent = vg.get_operations_since(3)
    assert len(recent) == 2  # Versions 4 and 5


def test_operation_log_trimming():
    vg = VersionedGraph(max_log_size=5)
    for i in range(10):
        vg.record_operation(GraphOperation(op_type="add_node", node_id=f"n{i}"))
    # Only last 5 should remain
    all_ops = vg.get_operations_since(0)
    assert len(all_ops) == 5


def test_detect_deletion_conflict():
    vg = VersionedGraph()
    vg.record_operation(GraphOperation(op_type="remove_node", node_id="n1"))

    proposed = [GraphOperation(op_type="update_node", node_id="n1")]
    conflicts = vg.detect_conflicts(0, proposed)
    assert len(conflicts) >= 1
    assert any(c.conflict_type == ConflictType.DELETION for c in conflicts)


def test_detect_rename_conflict():
    vg = VersionedGraph()
    vg.record_operation(GraphOperation(
        op_type="update_node", node_id="n1",
        properties={"renamed_from": "old_name"},
    ))

    proposed = [GraphOperation(op_type="update_node", node_id="n1")]
    conflicts = vg.detect_conflicts(0, proposed)
    assert any(c.conflict_type == ConflictType.RENAME for c in conflicts)


def test_detect_concurrent_edit():
    vg = VersionedGraph()
    vg.record_operation(GraphOperation(op_type="update_node", node_id="n1"))

    proposed = [GraphOperation(op_type="update_node", node_id="n1")]
    conflicts = vg.detect_conflicts(0, proposed)
    assert any(c.conflict_type == ConflictType.CONCURRENT_EDIT for c in conflicts)


def test_no_conflicts_when_no_drift():
    vg = VersionedGraph()
    proposed = [GraphOperation(op_type="add_node", node_id="n1")]
    conflicts = vg.detect_conflicts(0, proposed)
    assert len(conflicts) == 0


def test_resolve_rename_conflicts():
    vg = VersionedGraph()
    proposed = [GraphOperation(
        op_type="update_node", node_id="n1",
        properties={"calls": ["old_name", "other"]},
    )]
    resolved = vg.resolve_rename_conflicts(proposed, {"old_name": "new_name"})
    assert resolved[0].properties["calls"] == ["new_name", "other"]


def test_resolve_deletion_conflicts():
    vg = VersionedGraph()
    proposed = [
        GraphOperation(op_type="update_node", node_id="n1"),
        GraphOperation(op_type="update_node", node_id="n2"),
    ]
    resolved = vg.resolve_deletion_conflicts(proposed, {"n1"})
    assert len(resolved) == 1
    assert resolved[0].node_id == "n2"


def test_ai_session_clean():
    vg = VersionedGraph()
    mgr = AISessionManager(vg)
    session = mgr.start_session()
    result = mgr.complete_session(session.session_id)
    assert result.status == "clean"
    assert result.drift == 0


def test_ai_session_drift_no_changes():
    vg = VersionedGraph()
    mgr = AISessionManager(vg)
    session = mgr.start_session()

    # External change happens
    vg.record_operation(GraphOperation(op_type="add_node", node_id="n1"))

    result = mgr.complete_session(session.session_id)
    assert result.status == "clean_with_drift"
    assert result.drift == 1


def test_ai_session_conflict():
    vg = VersionedGraph()
    mgr = AISessionManager(vg)
    session = mgr.start_session()

    # External delete
    vg.record_operation(GraphOperation(op_type="remove_node", node_id="n1"))

    # Propose change to deleted node
    proposed = [GraphOperation(op_type="update_node", node_id="n1")]
    result = mgr.complete_session(session.session_id, proposed)
    assert result.status == "conflicts"
    assert result.can_apply is False
    assert len(result.conflicts) >= 1


def test_ai_session_max_active():
    vg = VersionedGraph()
    mgr = AISessionManager(vg, max_active=3)
    sessions = [mgr.start_session() for _ in range(5)]
    # Should have cleaned up to stay under limit
    active = [s for s in sessions if mgr.get_session(s.session_id) is not None]
    assert len(active) <= 3


def test_ai_session_nonexistent():
    vg = VersionedGraph()
    mgr = AISessionManager(vg)
    result = mgr.complete_session("nonexistent")
    assert result.status == "error"
