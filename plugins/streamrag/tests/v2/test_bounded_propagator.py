"""Tests for V2 bounded propagator."""

from streamrag.graph import LiquidGraph
from streamrag.models import GraphNode, GraphEdge
from streamrag.v2.bounded_propagator import BoundedPropagator, PropagatorConfig


def _make_chain_graph():
    """Create a chain: a.py -> b.py -> c.py -> d.py."""
    g = LiquidGraph()
    files = ["a.py", "b.py", "c.py", "d.py"]
    for i, fp in enumerate(files):
        g.add_node(GraphNode(
            id=f"n{i}", type="function", name=f"func_{fp[0]}",
            file_path=fp, line_start=1, line_end=5,
        ))
    # a calls b, b calls c, c calls d
    for i in range(len(files) - 1):
        g.add_edge(GraphEdge(source_id=f"n{i+1}", target_id=f"n{i}", edge_type="calls"))
    return g


def test_find_affected_files():
    g = _make_chain_graph()
    bp = BoundedPropagator(graph=g)
    affected = bp.find_affected_files("a.py")
    file_paths = [fp for fp, _ in affected]
    assert "b.py" in file_paths


def test_find_affected_depth_limited():
    g = _make_chain_graph()
    config = PropagatorConfig(max_depth=1)
    bp = BoundedPropagator(graph=g, config=config)
    affected = bp.find_affected_files("a.py")
    # Only depth 1 should be found
    for fp, depth in affected:
        assert depth <= 1


def test_priority_open_file_boost():
    bp = BoundedPropagator()
    bp.set_open_files({"open.py"})
    p_open = bp.compute_priority("open.py", depth=0)
    p_closed = bp.compute_priority("closed.py", depth=0)
    assert p_open < p_closed  # Open file has higher priority (lower number)


def test_priority_test_file_penalty():
    bp = BoundedPropagator()
    p_normal = bp.compute_priority("app.py", depth=0)
    p_test = bp.compute_priority("test_app.py", depth=0)
    assert p_test > p_normal  # Test file has lower priority (higher number)


def test_priority_depth_penalty():
    bp = BoundedPropagator()
    p0 = bp.compute_priority("a.py", depth=0)
    p1 = bp.compute_priority("a.py", depth=1)
    p2 = bp.compute_priority("a.py", depth=2)
    assert p0 < p1 < p2  # Deeper = lower priority


def test_propagate_sync_phase():
    g = _make_chain_graph()
    config = PropagatorConfig(max_sync_updates=2, max_depth=3)
    bp = BoundedPropagator(graph=g, config=config)

    processed = []
    result = bp.propagate("a.py", update_fn=lambda fp: processed.append(fp))
    assert len(result.sync_processed) <= 2


def test_propagate_async_queue():
    g = _make_chain_graph()
    config = PropagatorConfig(max_sync_updates=1, max_async_updates=2, max_depth=3)
    bp = BoundedPropagator(graph=g, config=config)

    result = bp.propagate("a.py")
    assert bp.async_queue_size >= 0
    if result.total_affected > 1:
        assert len(result.async_queued) > 0 or len(result.sync_processed) > 0


def test_process_async_queue():
    g = _make_chain_graph()
    config = PropagatorConfig(max_sync_updates=0, max_async_updates=10, max_depth=3)
    bp = BoundedPropagator(graph=g, config=config)

    bp.propagate("a.py")
    if bp.async_queue_size > 0:
        processed = bp.process_async_queue(max_items=5)
        assert len(processed) > 0


def test_propagate_no_affected():
    g = LiquidGraph()
    g.add_node(GraphNode(id="n1", type="function", name="foo", file_path="a.py",
                         line_start=1, line_end=5))
    bp = BoundedPropagator(graph=g)
    result = bp.propagate("a.py")
    assert result.total_affected == 0


def test_record_edit():
    bp = BoundedPropagator()
    bp.record_edit("a.py")
    # Recent edit should boost priority
    p_edited = bp.compute_priority("a.py", depth=0)
    p_not_edited = bp.compute_priority("b.py", depth=0)
    assert p_edited < p_not_edited


def test_clear_async_queue():
    bp = BoundedPropagator()
    bp.clear_async_queue()
    assert bp.async_queue_size == 0
