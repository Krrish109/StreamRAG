"""Tests for LiquidGraph."""

from streamrag.graph import LiquidGraph
from streamrag.models import GraphNode, GraphEdge


def test_add_and_get_node(empty_graph):
    node = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                     line_start=1, line_end=5)
    empty_graph.add_node(node)
    assert empty_graph.get_node("n1") is node
    assert empty_graph.node_count == 1


def test_remove_node(empty_graph):
    node = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                     line_start=1, line_end=5)
    empty_graph.add_node(node)
    removed = empty_graph.remove_node("n1")
    assert removed is node
    assert empty_graph.get_node("n1") is None
    assert empty_graph.node_count == 0


def test_remove_node_cascades_edges(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))

    assert empty_graph.edge_count == 1
    empty_graph.remove_node("n1")
    assert empty_graph.edge_count == 0
    assert empty_graph.get_outgoing_edges("n1") == []
    assert empty_graph.get_incoming_edges("n2") == []


def test_remove_nonexistent_node(empty_graph):
    assert empty_graph.remove_node("nonexistent") is None


def test_add_and_get_edge(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))

    outgoing = empty_graph.get_outgoing_edges("n1")
    assert len(outgoing) == 1
    assert outgoing[0].target_id == "n2"

    incoming = empty_graph.get_incoming_edges("n2")
    assert len(incoming) == 1
    assert incoming[0].source_id == "n1"


def test_remove_edge(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))

    removed = empty_graph.remove_edge("n1", "n2", "calls")
    assert removed is not None
    assert empty_graph.edge_count == 0


def test_get_node_by_name(empty_graph):
    node = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                     line_start=1, line_end=5)
    empty_graph.add_node(node)
    assert empty_graph.get_node_by_name("foo") is node
    assert empty_graph.get_node_by_name("nonexistent") is None


def test_get_nodes_by_file(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="b.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    a_nodes = empty_graph.get_nodes_by_file("a.py")
    assert len(a_nodes) == 1
    assert a_nodes[0].name == "foo"


def test_query_no_args_returns_all(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="class", name="Bar", file_path="b.py",
                   line_start=1, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    assert len(empty_graph.query()) == 2


def test_query_by_file(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="b.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    result = empty_graph.query(file_path="a.py")
    assert len(result) == 1
    assert result[0].name == "foo"


def test_query_by_type(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="class", name="Bar", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    result = empty_graph.query(entity_type="function")
    assert len(result) == 1
    assert result[0].name == "foo"


def test_query_intersection(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="bar", file_path="b.py",
                   line_start=1, line_end=5)
    n3 = GraphNode(id="n3", type="class", name="Baz", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)

    result = empty_graph.query(file_path="a.py", entity_type="function")
    assert len(result) == 1
    assert result[0].name == "foo"


def test_compute_hash_deterministic(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    h1 = empty_graph.compute_hash()
    h2 = empty_graph.compute_hash()
    assert h1 == h2
    assert len(h1) == 16


def test_compute_hash_changes_with_graph(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    h1 = empty_graph.compute_hash()

    n2 = GraphNode(id="n2", type="function", name="bar", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n2)
    h2 = empty_graph.compute_hash()
    assert h1 != h2


def test_snapshot(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n1", edge_type="calls"))

    snap = empty_graph.snapshot()
    assert snap.node_count == empty_graph.node_count
    assert snap.edge_count == empty_graph.edge_count
    assert snap.compute_hash() == empty_graph.compute_hash()

    # Mutating snapshot doesn't affect original
    snap.remove_node("n1")
    assert empty_graph.node_count == 1
    assert snap.node_count == 0


# --- Enhanced Query Tests ---


def test_query_regex_prefix(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="test_foo", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="test_bar", file_path="a.py",
                   line_start=6, line_end=10)
    n3 = GraphNode(id="n3", type="function", name="my_test", file_path="a.py",
                   line_start=11, line_end=15)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)

    result = empty_graph.query_regex("^test_.*")
    names = {n.name for n in result}
    assert names == {"test_foo", "test_bar"}


def test_query_regex_suffix(empty_graph):
    n1 = GraphNode(id="n1", type="class", name="RequestHandler", file_path="a.py",
                   line_start=1, line_end=10)
    n2 = GraphNode(id="n2", type="class", name="BaseClass", file_path="a.py",
                   line_start=11, line_end=20)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    result = empty_graph.query_regex(".*Handler$")
    assert len(result) == 1
    assert result[0].name == "RequestHandler"


def test_query_regex_with_type_filter(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="get_user", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="class", name="get_user", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    result = empty_graph.query_regex("get_.*", entity_type="function")
    assert len(result) == 1
    assert result[0].type == "function"


def test_traverse_outgoing(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    n3 = GraphNode(id="n3", type="function", name="c", file_path="x.py",
                   line_start=11, line_end=15)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n3", edge_type="calls"))

    result = empty_graph.traverse("n1", max_depth=2)
    names = {n.name for n, _ in result}
    assert names == {"b", "c"}
    depths = {n.name: d for n, d in result}
    assert depths["b"] == 1
    assert depths["c"] == 2


def test_traverse_edge_type_filter(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    n3 = GraphNode(id="n3", type="class", name="c", file_path="x.py",
                   line_start=11, line_end=15)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n3", edge_type="inherits"))

    result = empty_graph.traverse("n1", edge_types=["calls"])
    assert len(result) == 1
    assert result[0][0].name == "b"


def test_traverse_incoming(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))

    result = empty_graph.traverse("n2", direction="incoming")
    assert len(result) == 1
    assert result[0][0].name == "a"


def test_traverse_max_depth(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    n3 = GraphNode(id="n3", type="function", name="c", file_path="x.py",
                   line_start=11, line_end=15)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n3", edge_type="calls"))

    result = empty_graph.traverse("n1", max_depth=1)
    assert len(result) == 1
    assert result[0][0].name == "b"


def test_find_dead_code_basic(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="used", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="unused", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n1", edge_type="calls"))

    dead = empty_graph.find_dead_code()
    names = {n.name for n in dead}
    assert "unused" in names
    assert "used" not in names


def test_find_dead_code_excludes_entry_points(empty_graph):
    n1 = GraphNode(id="n1", type="module_code", name="__module__", file_path="a.py",
                   line_start=1, line_end=1)
    n2 = GraphNode(id="n2", type="import", name="os", file_path="a.py",
                   line_start=1, line_end=1)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    dead = empty_graph.find_dead_code()
    assert len(dead) == 0


def test_find_dead_code_excludes_dunders(empty_graph):
    """Dunder methods like __init__ should not be flagged as dead code."""
    n1 = GraphNode(id="n1", type="function", name="Foo.__init__", file_path="a.py",
                   line_start=2, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="Foo.__str__", file_path="a.py",
                   line_start=6, line_end=8)
    n3 = GraphNode(id="n3", type="function", name="Foo.regular", file_path="a.py",
                   line_start=9, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)

    dead = empty_graph.find_dead_code()
    dead_names = {n.name for n in dead}
    assert "Foo.__init__" not in dead_names
    assert "Foo.__str__" not in dead_names
    assert "Foo.regular" in dead_names  # regular methods still flagged


def test_is_reachable_direct(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))

    assert empty_graph.is_reachable("n1", "n2") is True
    assert empty_graph.is_reachable("n2", "n1") is False


def test_is_reachable_transitive(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    n3 = GraphNode(id="n3", type="function", name="c", file_path="x.py",
                   line_start=11, line_end=15)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n3", edge_type="calls"))

    assert empty_graph.is_reachable("n1", "n3") is True


def test_is_reachable_self(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    assert empty_graph.is_reachable("n1", "n1") is True


def test_find_path_basic(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    n3 = GraphNode(id="n3", type="function", name="c", file_path="x.py",
                   line_start=11, line_end=15)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n3", edge_type="calls"))

    path = empty_graph.find_path("n1", "n3")
    assert path == ["n1", "n2", "n3"]


def test_find_path_none(empty_graph):
    n1 = GraphNode(id="n1", type="function", name="a", file_path="x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="x.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    path = empty_graph.find_path("n1", "n2")
    assert path is None


# --- Cycle Detection Tests ---


# --- P0.2: Framework-aware dead code exclusion tests ---


def test_find_dead_code_excludes_test_files(empty_graph):
    """Dead code detection excludes nodes in test files by default."""
    n1 = GraphNode(id="n1", type="function", name="real_func", file_path="src/app.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="test_func", file_path="tests/test_app.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    dead = empty_graph.find_dead_code()
    names = {n.name for n in dead}
    assert "real_func" in names
    assert "test_func" not in names  # excluded because test file

    # With both exclusions disabled, both show up
    dead_all = empty_graph.find_dead_code(exclude_tests=False, exclude_framework=False)
    names_all = {n.name for n in dead_all}
    assert "test_func" in names_all


def test_find_dead_code_excludes_framework_patterns(empty_graph):
    """Dead code detection excludes framework patterns like test_, visit_."""
    n1 = GraphNode(id="n1", type="function", name="test_something", file_path="src/visitor.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="visit_Name", file_path="src/visitor.py",
                   line_start=6, line_end=10)
    n3 = GraphNode(id="n3", type="function", name="regular_func", file_path="src/visitor.py",
                   line_start=11, line_end=15)
    n4 = GraphNode(id="n4", type="function", name="setUp", file_path="src/base.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)
    empty_graph.add_node(n4)

    dead = empty_graph.find_dead_code()
    names = {n.name for n in dead}
    assert "regular_func" in names
    assert "test_something" not in names
    assert "visit_Name" not in names
    assert "setUp" not in names


def test_find_dead_code_all_flag(empty_graph):
    """With both exclusions disabled, all unreferenced nodes appear."""
    n1 = GraphNode(id="n1", type="function", name="test_foo", file_path="tests/test_x.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="visit_Assign", file_path="src/ext.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    dead_default = empty_graph.find_dead_code()
    assert len(dead_default) == 0

    dead_all = empty_graph.find_dead_code(exclude_tests=False, exclude_framework=False)
    names = {n.name for n in dead_all}
    assert "test_foo" in names
    assert "visit_Assign" in names


# --- Polymorphic override dead code tests ---


def test_find_dead_code_excludes_property_methods(empty_graph):
    """@property methods should not be flagged as dead code."""
    n1 = GraphNode(id="n1", type="function", name="Foo.bar", file_path="a.py",
                   line_start=2, line_end=5,
                   properties={"decorators": ["property"]})
    n2 = GraphNode(id="n2", type="function", name="Foo.regular", file_path="a.py",
                   line_start=6, line_end=10)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)

    dead = empty_graph.find_dead_code()
    dead_names = {n.name for n in dead}
    assert "Foo.bar" not in dead_names  # property — excluded
    assert "Foo.regular" in dead_names  # regular method — still flagged


def test_find_dead_code_excludes_nested_in_non_dead_parent(empty_graph):
    """Nested function inside a non-dead parent should not be flagged dead."""
    parent = GraphNode(id="p1", type="function", name="Foo.bar", file_path="a.py",
                       line_start=2, line_end=10)
    nested = GraphNode(id="p2", type="function", name="Foo.bar.helper", file_path="a.py",
                       line_start=4, line_end=8)
    caller = GraphNode(id="c1", type="function", name="main", file_path="b.py",
                       line_start=1, line_end=5)
    empty_graph.add_node(parent)
    empty_graph.add_node(nested)
    empty_graph.add_node(caller)
    # caller -> Foo.bar (parent is not dead)
    empty_graph.add_edge(GraphEdge(source_id="c1", target_id="p1", edge_type="calls"))

    dead = empty_graph.find_dead_code()
    dead_names = {n.name for n in dead}
    assert "Foo.bar.helper" not in dead_names  # nested in non-dead parent
    assert "Foo.bar" not in dead_names  # has incoming edges


def test_find_dead_code_excludes_abstract_overrides(empty_graph):
    """Child.process overriding Base.process with @abstractmethod is not dead."""
    base_cls = GraphNode(id="base", type="class", name="Base", file_path="a.py",
                         line_start=1, line_end=10)
    base_method = GraphNode(id="base_proc", type="function", name="Base.process",
                            file_path="a.py", line_start=2, line_end=5,
                            properties={"decorators": ["abstractmethod"]})
    child_cls = GraphNode(id="child", type="class", name="Child", file_path="b.py",
                          line_start=1, line_end=10)
    child_method = GraphNode(id="child_proc", type="function", name="Child.process",
                             file_path="b.py", line_start=2, line_end=5)
    empty_graph.add_node(base_cls)
    empty_graph.add_node(base_method)
    empty_graph.add_node(child_cls)
    empty_graph.add_node(child_method)
    # Child inherits Base
    empty_graph.add_edge(GraphEdge(source_id="child", target_id="base", edge_type="inherits"))

    dead = empty_graph.find_dead_code()
    dead_names = {n.name for n in dead}
    assert "Child.process" not in dead_names


def test_find_dead_code_excludes_polymorphic_override(empty_graph):
    """Child.run overriding Base.run which has callers is not dead."""
    base_cls = GraphNode(id="base", type="class", name="Base", file_path="a.py",
                         line_start=1, line_end=10)
    base_method = GraphNode(id="base_run", type="function", name="Base.run",
                            file_path="a.py", line_start=2, line_end=5)
    child_cls = GraphNode(id="child", type="class", name="Child", file_path="b.py",
                          line_start=1, line_end=10)
    child_method = GraphNode(id="child_run", type="function", name="Child.run",
                             file_path="b.py", line_start=2, line_end=5)
    caller = GraphNode(id="caller", type="function", name="execute", file_path="c.py",
                       line_start=1, line_end=5)
    empty_graph.add_node(base_cls)
    empty_graph.add_node(base_method)
    empty_graph.add_node(child_cls)
    empty_graph.add_node(child_method)
    empty_graph.add_node(caller)
    # Child inherits Base
    empty_graph.add_edge(GraphEdge(source_id="child", target_id="base", edge_type="inherits"))
    # caller -> Base.run (polymorphic call)
    empty_graph.add_edge(GraphEdge(source_id="caller", target_id="base_run", edge_type="calls"))

    dead = empty_graph.find_dead_code()
    dead_names = {n.name for n in dead}
    assert "Child.run" not in dead_names
    assert "Base.run" not in dead_names  # has incoming edges directly


def test_find_dead_code_still_flags_unrelated_methods(empty_graph):
    """Child.unique_method that doesn't exist on parent is still flagged dead."""
    base_cls = GraphNode(id="base", type="class", name="Base", file_path="a.py",
                         line_start=1, line_end=10)
    child_cls = GraphNode(id="child", type="class", name="Child", file_path="b.py",
                          line_start=1, line_end=10)
    child_method = GraphNode(id="child_uniq", type="function", name="Child.unique_method",
                             file_path="b.py", line_start=2, line_end=5)
    empty_graph.add_node(base_cls)
    empty_graph.add_node(child_cls)
    empty_graph.add_node(child_method)
    # Child inherits Base
    empty_graph.add_edge(GraphEdge(source_id="child", target_id="base", edge_type="inherits"))

    dead = empty_graph.find_dead_code()
    dead_names = {n.name for n in dead}
    assert "Child.unique_method" in dead_names


# --- P0.3: Test-aware cycle detection tests ---


def test_find_cycles_excludes_test_files(empty_graph):
    """Cycle involving test files excluded by default."""
    n1 = GraphNode(id="n1", type="function", name="a", file_path="src/a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="tests/test_a.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n1", edge_type="calls"))

    cycles = empty_graph.find_cycles()
    assert len(cycles) == 0  # excluded because test file involved

    cycles_all = empty_graph.find_cycles(exclude_tests=False)
    assert len(cycles_all) >= 1


def test_find_cycles_source_only_cycle_detected(empty_graph):
    """Source-only cycles are still detected."""
    n1 = GraphNode(id="n1", type="function", name="a", file_path="src/a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="src/b.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n1", edge_type="calls"))

    cycles = empty_graph.find_cycles()
    assert len(cycles) >= 1


def test_find_cycles_no_cycles(empty_graph):
    """Graph with no cycles returns empty list."""
    n1 = GraphNode(id="n1", type="function", name="a", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="b.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))

    cycles = empty_graph.find_cycles()
    assert len(cycles) == 0


def test_find_cycles_with_cycle(empty_graph):
    """Graph with a file-level cycle is detected."""
    n1 = GraphNode(id="n1", type="function", name="a", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="b.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n1", edge_type="calls"))

    cycles = empty_graph.find_cycles()
    assert len(cycles) >= 1
    # Cycle should contain both files
    cycle_files = set()
    for cycle in cycles:
        cycle_files.update(cycle)
    assert "a.py" in cycle_files
    assert "b.py" in cycle_files


# --- Cycle deduplication and superset filtering tests ---


def test_find_cycles_deduplication(empty_graph):
    """A<->B cycle should be reported exactly once, not twice from different DFS starts."""
    n1 = GraphNode(id="n1", type="function", name="a", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="b.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n1", edge_type="calls"))

    cycles = empty_graph.find_cycles()
    assert len(cycles) == 1
    # Should contain both files plus trailing duplicate
    assert set(cycles[0][:-1]) == {"a.py", "b.py"}
    assert cycles[0][-1] == cycles[0][0]  # trailing node matches first


def test_find_cycles_superset_filtering(empty_graph):
    """A<->B fundamental cycle + A->B->C->A superset: only A<->B kept."""
    n1 = GraphNode(id="n1", type="function", name="a", file_path="a.py",
                   line_start=1, line_end=5)
    n2 = GraphNode(id="n2", type="function", name="b", file_path="b.py",
                   line_start=1, line_end=5)
    n3 = GraphNode(id="n3", type="function", name="c", file_path="c.py",
                   line_start=1, line_end=5)
    empty_graph.add_node(n1)
    empty_graph.add_node(n2)
    empty_graph.add_node(n3)
    # A <-> B (fundamental 2-node cycle)
    empty_graph.add_edge(GraphEdge(source_id="n1", target_id="n2", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n1", edge_type="calls"))
    # B -> C -> A (creates A->B->C->A superset cycle)
    empty_graph.add_edge(GraphEdge(source_id="n2", target_id="n3", edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n3", target_id="n1", edge_type="calls"))

    cycles = empty_graph.find_cycles()
    # Only the fundamental A<->B cycle should remain
    assert len(cycles) == 1
    assert set(cycles[0][:-1]) == {"a.py", "b.py"}


def test_find_cycles_deep_chain_no_crash(empty_graph):
    """Iterative DFS handles deep dependency chains without RecursionError."""
    for i in range(1500):
        n = GraphNode(id=f"n{i}", type="function", name=f"f{i}",
                      file_path=f"src/f{i}.py", line_start=1, line_end=5)
        empty_graph.add_node(n)
    for i in range(1499):
        empty_graph.add_edge(GraphEdge(source_id=f"n{i}", target_id=f"n{i+1}",
                                       edge_type="calls"))
    cycles = empty_graph.find_cycles()
    assert len(cycles) == 0


def test_find_cycles_deep_chain_with_back_edge(empty_graph):
    """Iterative DFS finds cycle in deep chain with back edge."""
    for i in range(1500):
        n = GraphNode(id=f"n{i}", type="function", name=f"f{i}",
                      file_path=f"src/f{i}.py", line_start=1, line_end=5)
        empty_graph.add_node(n)
    for i in range(1499):
        empty_graph.add_edge(GraphEdge(source_id=f"n{i}", target_id=f"n{i+1}",
                                       edge_type="calls"))
    empty_graph.add_edge(GraphEdge(source_id="n1499", target_id="n0",
                                   edge_type="calls"))
    cycles = empty_graph.find_cycles()
    assert len(cycles) >= 1
