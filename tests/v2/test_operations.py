"""Tests for V2 fine-grained operations."""

from streamrag.graph import LiquidGraph
from streamrag.models import GraphNode, GraphEdge
from streamrag.v2.operations import (
    AddNode, RemoveNode, UpdateNode, RenameNode, MoveNode,
    AddEdge, RemoveEdge, RetargetEdge, SetNodeProperty,
    OperationBatch,
)


def _make_graph_with_nodes():
    g = LiquidGraph()
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5, properties={"calls": ["bar"]})
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="a.py",
                   line_start=6, line_end=10, properties={})
    g.add_node(n1)
    g.add_node(n2)
    g.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    return g


def test_add_node_and_inverse():
    g = LiquidGraph()
    node = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                     line_start=1, line_end=5)
    op = AddNode(node=node)
    assert op.apply(g)
    assert g.get_node("n1") is not None

    # Inverse removes it
    inv = op.inverse()
    assert inv.apply(g)
    assert g.get_node("n1") is None


def test_remove_node_and_inverse():
    g = _make_graph_with_nodes()
    op = RemoveNode(node_id="n1")
    assert op.apply(g)
    assert g.get_node("n1") is None

    # Inverse restores it
    inv = op.inverse()
    assert inv.apply(g)
    assert g.get_node("n1") is not None
    assert g.get_node("n1").name == "foo"


def test_update_node_and_inverse():
    g = _make_graph_with_nodes()
    op = UpdateNode(node_id="n1", updates={"calls": ["baz"], "new_prop": True})
    assert op.apply(g)
    assert g.get_node("n1").properties["calls"] == ["baz"]
    assert g.get_node("n1").properties["new_prop"] is True

    # Inverse restores original
    inv = op.inverse()
    assert inv.apply(g)
    assert g.get_node("n1").properties["calls"] == ["bar"]


def test_rename_node_and_inverse():
    g = _make_graph_with_nodes()
    op = RenameNode(node_id="n1", old_name="foo", new_name="foo_renamed")
    assert op.apply(g)
    assert g.get_node("n1").name == "foo_renamed"
    assert g.get_node("n1").properties.get("renamed_from") == "foo"

    # Check name index updated
    assert g.get_node_by_name("foo_renamed") is not None
    assert g.get_node_by_name("foo") is None

    # Inverse restores
    inv = op.inverse()
    assert inv.apply(g)
    assert g.get_node("n1").name == "foo"


def test_move_node_and_inverse():
    g = _make_graph_with_nodes()
    op = MoveNode(node_id="n1", old_file_path="a.py", new_file_path="b.py",
                  old_line_start=1, new_line_start=10, old_line_end=5, new_line_end=15)
    assert op.apply(g)
    assert g.get_node("n1").file_path == "b.py"
    assert g.get_node("n1").line_start == 10

    inv = op.inverse()
    assert inv.apply(g)
    assert g.get_node("n1").file_path == "a.py"


def test_add_edge_and_inverse():
    g = _make_graph_with_nodes()
    edge = GraphEdge(source_id="n2", target_id="n1", edge_type="uses")
    op = AddEdge(edge=edge)
    assert op.apply(g)
    assert len(g.get_outgoing_edges("n2")) == 1

    inv = op.inverse()
    assert inv.apply(g)
    assert len(g.get_outgoing_edges("n2")) == 0


def test_remove_edge_and_inverse():
    g = _make_graph_with_nodes()
    op = RemoveEdge(source_id="n1", target_id="n2", edge_type="calls")
    assert op.apply(g)
    assert len(g.get_outgoing_edges("n1")) == 0

    inv = op.inverse()
    assert inv.apply(g)
    assert len(g.get_outgoing_edges("n1")) == 1


def test_retarget_edge_and_inverse():
    g = _make_graph_with_nodes()
    n3 = GraphNode(id="n3", type="function", name="baz", file_path="a.py",
                   line_start=11, line_end=15)
    g.add_node(n3)

    op = RetargetEdge(source_id="n1", old_target_id="n2", new_target_id="n3",
                      edge_type="calls")
    assert op.apply(g)
    edges = g.get_outgoing_edges("n1")
    assert len(edges) == 1
    assert edges[0].target_id == "n3"

    inv = op.inverse()
    assert inv.apply(g)
    edges = g.get_outgoing_edges("n1")
    assert edges[0].target_id == "n2"


def test_set_node_property_and_inverse():
    g = _make_graph_with_nodes()
    op = SetNodeProperty(node_id="n1", key="version", new_value=2)
    assert op.apply(g)
    assert g.get_node("n1").properties["version"] == 2

    inv = op.inverse()
    assert inv.apply(g)
    assert g.get_node("n1").properties.get("version") is None


def test_operation_batch_success():
    g = LiquidGraph()
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="a.py",
                   line_start=6, line_end=10)
    batch = OperationBatch([AddNode(node=n1), AddNode(node=n2)])
    assert batch.apply(g)
    assert g.node_count == 2


def test_operation_batch_rollback():
    g = LiquidGraph()
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    # Second op tries to add n1 again (will fail since it exists)
    batch = OperationBatch([AddNode(node=n1), AddNode(node=n1)])
    assert not batch.apply(g)
    # After rollback, node should be gone
    assert g.node_count == 0


def test_remove_nonexistent_fails():
    g = LiquidGraph()
    op = RemoveNode(node_id="nonexistent")
    assert not op.apply(g)
