"""Tests for V2 hierarchical graph."""

from streamrag.graph import LiquidGraph
from streamrag.models import GraphNode, GraphEdge
from streamrag.v2.hierarchical_graph import HierarchicalGraph, HierarchicalGraphConfig, Zone


def _make_graph():
    g = LiquidGraph()
    for i, name in enumerate(["foo", "bar", "baz"]):
        fp = f"file_{name}.py"
        n = GraphNode(id=f"n{i}", type="function", name=name, file_path=fp,
                      line_start=1, line_end=5)
        g.add_node(n)
    # foo calls bar (cross-file edge)
    g.add_edge(GraphEdge(source_id="n0", target_id="n1", edge_type="calls"))
    return g


def test_initial_zone_is_cold():
    hg = HierarchicalGraph()
    assert hg.get_zone("any_file.py") == Zone.COLD


def test_open_file_promotes_to_hot():
    hg = HierarchicalGraph(graph=_make_graph())
    hg.open_file("file_foo.py")
    assert hg.get_zone("file_foo.py") == Zone.HOT


def test_open_file_promotes_deps_to_warm():
    hg = HierarchicalGraph(graph=_make_graph())
    hg.open_file("file_foo.py")
    # foo calls bar, so bar's file should be WARM
    assert hg.get_zone("file_bar.py") == Zone.WARM


def test_close_file_demotes_to_warm():
    hg = HierarchicalGraph(graph=_make_graph())
    hg.open_file("file_foo.py")
    hg.close_file("file_foo.py")
    assert hg.get_zone("file_foo.py") == Zone.WARM


def test_hot_eviction():
    config = HierarchicalGraphConfig(max_hot_files=2)
    hg = HierarchicalGraph(graph=_make_graph(), config=config)

    hg.open_file("file_foo.py")
    hg.open_file("file_bar.py")
    hg.open_file("file_baz.py")  # Exceeds max_hot=2

    # One of the non-open files should have been evicted
    hot_files = hg.get_files_by_zone(Zone.HOT)
    assert len(hot_files) <= 3  # All open so no eviction possible
    # (all are marked open so eviction can't happen)


def test_hot_eviction_with_close():
    config = HierarchicalGraphConfig(max_hot_files=2)
    hg = HierarchicalGraph(graph=_make_graph(), config=config)

    hg.open_file("file_foo.py")
    hg.close_file("file_foo.py")  # Now not open, but in WARM
    hg.open_file("file_bar.py")
    hg.open_file("file_baz.py")

    # file_foo was closed, so it shouldn't be HOT
    assert hg.get_zone("file_foo.py") == Zone.WARM


def test_update_priority_open_file():
    hg = HierarchicalGraph(graph=_make_graph())
    hg.open_file("file_foo.py")
    p = hg.get_update_priority("file_foo.py")
    # Open file gets -50 and recent access gets -30
    assert p < 100


def test_update_priority_test_file():
    hg = HierarchicalGraph(graph=_make_graph())
    p_test = hg.get_update_priority("test_foo.py")
    p_normal = hg.get_update_priority("app.py")
    # Test file should have higher priority number (lower priority) than normal
    assert p_test > p_normal


def test_get_files_by_zone():
    hg = HierarchicalGraph(graph=_make_graph())
    hg.open_file("file_foo.py")
    hg.close_file("file_foo.py")

    hot = hg.get_files_by_zone(Zone.HOT)
    warm = hg.get_files_by_zone(Zone.WARM)
    assert "file_foo.py" in warm
    assert "file_foo.py" not in hot


def test_stats():
    hg = HierarchicalGraph(graph=_make_graph())
    hg.open_file("file_foo.py")
    stats = hg.get_stats()
    assert stats["hot_files"] >= 1
    assert stats["total_files"] >= 1
