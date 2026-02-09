"""Tests for StreamRAG data structures."""

from streamrag.models import ASTEntity, GraphNode, GraphEdge, CodeChange, GraphOperation


def test_ast_entity_defaults():
    e = ASTEntity(
        entity_type="function", name="foo", line_start=1, line_end=5,
        signature_hash="abc", structure_hash="def",
    )
    assert e.calls == []
    assert e.uses == []
    assert e.inherits == []
    assert e.imports == []
    assert e.old_name is None


def test_ast_entity_with_all_fields():
    e = ASTEntity(
        entity_type="class", name="Foo", line_start=1, line_end=10,
        signature_hash="a", structure_hash="b",
        calls=["bar"], uses=["x"], inherits=["Base"],
        imports=[("os", "path")], old_name="OldFoo",
    )
    assert e.entity_type == "class"
    assert e.calls == ["bar"]
    assert e.old_name == "OldFoo"


def test_graph_node_defaults():
    n = GraphNode(id="abc", type="function", name="foo", file_path="test.py",
                  line_start=1, line_end=5)
    assert n.properties == {}


def test_graph_edge():
    e = GraphEdge(source_id="a", target_id="b", edge_type="calls")
    assert e.properties == {}


def test_code_change_defaults():
    c = CodeChange(file_path="test.py", old_content="", new_content="x = 1")
    assert c.cursor_position == (0, 0)
    assert c.change_type == "replace"


def test_graph_operation_defaults():
    op = GraphOperation(op_type="add_node", node_id="abc")
    assert op.node_type == ""
    assert op.properties == {}
    assert op.edges == []
