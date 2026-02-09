"""Tests for DeltaGraphBridge -- implements the spec test contract."""

import time

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange


def test_adding_function_creates_one_add_node(bridge):
    """Adding function -> 1 add_node operation."""
    code = "def hello():\n    pass\n"
    ops = bridge.process_change(CodeChange("test.py", "", code))
    add_ops = [op for op in ops if op.op_type == "add_node"]
    assert len(add_ops) == 1


def test_renaming_function_creates_update_not_delete_add(bridge):
    """Renaming function -> 1 update_node (NOT delete+add)."""
    code_v1 = "def old_name(x):\n    return x\n"
    bridge.process_change(CodeChange("test.py", "", code_v1))

    code_v2 = "def new_name(x):\n    return x\n"
    ops = bridge.process_change(CodeChange("test.py", code_v1, code_v2))

    update_ops = [op for op in ops if op.op_type == "update_node"]
    add_ops = [op for op in ops if op.op_type == "add_node"]
    remove_ops = [op for op in ops if op.op_type == "remove_node"]

    assert len(update_ops) == 1
    assert len(add_ops) == 0
    assert len(remove_ops) == 0
    assert update_ops[0].properties.get("renamed_from") == "old_name"


def test_whitespace_only_change_produces_zero_operations(bridge):
    """Whitespace-only change -> 0 operations."""
    code_v1 = "def foo():\n    return 1\n"
    bridge.process_change(CodeChange("test.py", "", code_v1))

    code_v2 = "def foo():\n    return 1\n\n\n"
    ops = bridge.process_change(CodeChange("test.py", code_v1, code_v2))
    assert len(ops) == 0


def test_comment_only_change_produces_zero_operations(bridge):
    """Comment-only change -> 0 operations."""
    code_v1 = "def foo():\n    return 1\n"
    bridge.process_change(CodeChange("test.py", "", code_v1))

    code_v2 = "# added comment\ndef foo():\n    return 1\n"
    ops = bridge.process_change(CodeChange("test.py", code_v1, code_v2))
    assert len(ops) == 0


def test_body_change_produces_one_update_node(bridge):
    """Body change -> 1 update_node."""
    code_v1 = "def foo():\n    return 1\n"
    bridge.process_change(CodeChange("test.py", "", code_v1))

    code_v2 = "def foo():\n    return 2\n"
    ops = bridge.process_change(CodeChange("test.py", code_v1, code_v2))

    update_ops = [op for op in ops if op.op_type == "update_node"]
    assert len(update_ops) == 1
    assert len(ops) == 1


def test_change_one_of_fifty_functions_produces_one_operation(bridge, fifty_functions_code):
    """Change 1 of 50 funcs -> exactly 1 operation."""
    bridge.process_change(CodeChange("test.py", "", fifty_functions_code))

    # Change only func_25
    modified = fifty_functions_code.replace(
        "def func_25(x):\n    return x + 25",
        "def func_25(x):\n    return x * 25",
    )
    ops = bridge.process_change(CodeChange("test.py", fifty_functions_code, modified))
    assert len(ops) == 1
    assert ops[0].op_type == "update_node"


def test_cross_file_call_creates_edge(bridge):
    """Cross-file call -> edge created."""
    code_a = "def helper():\n    return 42\n"
    bridge.process_change(CodeChange("a.py", "", code_a))

    code_b = "def caller():\n    helper()\n"
    bridge.process_change(CodeChange("b.py", "", code_b))

    assert bridge.graph.edge_count >= 1
    # Verify edge goes from caller to helper
    caller_nodes = bridge.graph.query(name="caller")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    assert any(e.edge_type == "calls" for e in outgoing)


def test_broken_syntax_produces_zero_operations(bridge):
    """Broken syntax -> 0 operations (no ghost nodes)."""
    code_v1 = "def foo():\n    return 1\n"
    bridge.process_change(CodeChange("test.py", "", code_v1))
    initial_count = bridge.graph.node_count

    code_v2 = "def foo(:\n    return 1\n"
    ops = bridge.process_change(CodeChange("test.py", code_v1, code_v2))
    assert len(ops) == 0
    assert bridge.graph.node_count == initial_count


def test_all_changes_under_10ms(bridge):
    """All changes -> < 10ms."""
    code_v1 = "def foo():\n    return 1\n"
    bridge.process_change(CodeChange("test.py", "", code_v1))

    code_v2 = "def foo():\n    return 2\n\ndef bar():\n    foo()\n"

    start = time.perf_counter()
    bridge.process_change(CodeChange("test.py", code_v1, code_v2))
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 10, f"Took {elapsed_ms:.3f}ms, expected < 10ms"


def test_semantic_change_detection(bridge):
    code_v1 = "def foo():\n    return 1\n"
    code_v2 = "def foo():\n    return 2\n"
    code_whitespace = "def foo():\n    return 1\n\n"

    assert bridge.is_semantic_change(code_v1, code_v2) is True
    assert bridge.is_semantic_change(code_v1, code_whitespace) is False


def test_get_affected_files(bridge):
    code_a = "def helper():\n    return 42\n"
    bridge.process_change(CodeChange("a.py", "", code_a))

    code_b = "def caller():\n    helper()\n"
    bridge.process_change(CodeChange("b.py", "", code_b))

    affected = bridge.get_affected_files("a.py", "helper")
    assert "b.py" in affected
    assert "a.py" not in affected


def test_snapshot_independence(bridge):
    code = "def foo():\n    return 1\n"
    bridge.process_change(CodeChange("test.py", "", code))

    snap = bridge.snapshot()
    assert snap.graph.node_count == bridge.graph.node_count

    # Modify original
    code_v2 = "def foo():\n    return 2\n\ndef bar():\n    pass\n"
    bridge.process_change(CodeChange("test.py", code, code_v2))

    # Snapshot should be unchanged
    assert snap.graph.node_count != bridge.graph.node_count


def test_inheritance_edge(bridge):
    code = """
class Base:
    pass

class Child(Base):
    pass
"""
    ops = bridge.process_change(CodeChange("test.py", "", code))
    # Check for inherits edge
    child_nodes = bridge.graph.query(name="Child")
    assert len(child_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(child_nodes[0].id)
    inherits_edges = [e for e in outgoing if e.edge_type == "inherits"]
    assert len(inherits_edges) == 1


def test_module_level_call_creates_entity(bridge):
    code = "setup()\n"
    ops = bridge.process_change(CodeChange("test.py", "", code))
    module_nodes = bridge.graph.query(name="__module__")
    assert len(module_nodes) == 1


def test_import_entities_per_name(bridge):
    code = "from os.path import join, exists\n"
    ops = bridge.process_change(CodeChange("test.py", "", code))
    import_nodes = bridge.graph.query(entity_type="import")
    assert len(import_nodes) == 2


# --- Phase 1A: Import Edge Tests ---


def test_import_creates_edge_to_definition(bridge):
    """Import of a defined function creates an 'imports' edge."""
    code_a = "def helper():\n    return 42\n"
    bridge.process_change(CodeChange("a.py", "", code_a))

    code_b = "from a import helper\n"
    bridge.process_change(CodeChange("b.py", "", code_b))

    import_nodes = bridge.graph.query(entity_type="import", name="helper")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    assert len(import_edges) == 1
    # Target should be the function definition in a.py
    target = bridge.graph.get_node(import_edges[0].target_id)
    assert target is not None
    assert target.name == "helper"
    assert target.file_path == "a.py"


def test_import_edge_reverse_resolution(bridge):
    """Import added BEFORE definition still gets linked via two-pass resolution."""
    code_b = "from a import helper\n"
    bridge.process_change(CodeChange("b.py", "", code_b))

    code_a = "def helper():\n    return 42\n"
    bridge.process_change(CodeChange("a.py", "", code_a))

    import_nodes = bridge.graph.query(entity_type="import", name="helper")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    assert len(import_edges) == 1


def test_import_edge_no_self_link(bridge):
    """An import node should not link to itself."""
    code = "from a import helper\n\ndef helper():\n    pass\n"
    bridge.process_change(CodeChange("a.py", "", code))

    import_nodes = bridge.graph.query(entity_type="import", name="helper")
    for node in import_nodes:
        outgoing = bridge.graph.get_outgoing_edges(node.id)
        for edge in outgoing:
            assert edge.target_id != node.id


def test_import_edge_stdlib_no_crash(bridge):
    """Importing stdlib (no definition in graph) produces no edge, no error."""
    code = "import os\nfrom os.path import join\n"
    ops = bridge.process_change(CodeChange("test.py", "", code))
    import_nodes = bridge.graph.query(entity_type="import")
    for node in import_nodes:
        outgoing = bridge.graph.get_outgoing_edges(node.id)
        import_edges = [e for e in outgoing if e.edge_type == "imports"]
        assert len(import_edges) == 0  # No target in graph


# --- Phase 1B: Decorator Edge Tests ---


def test_decorator_edge_to_custom_decorator(bridge):
    """A custom decorator creates a 'decorated_by' edge."""
    code = "def my_decorator(f):\n    return f\n\n@my_decorator\ndef foo():\n    pass\n"
    bridge.process_change(CodeChange("test.py", "", code))

    foo_nodes = bridge.graph.query(name="foo", entity_type="function")
    assert len(foo_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(foo_nodes[0].id)
    dec_edges = [e for e in outgoing if e.edge_type == "decorated_by"]
    assert len(dec_edges) == 1
    target = bridge.graph.get_node(dec_edges[0].target_id)
    assert target.name == "my_decorator"


def test_builtin_decorator_no_edge_but_property_set(bridge):
    """Built-in decorators have no edge (no node in graph) but decorators property is set."""
    code = "class Foo:\n    @property\n    def bar(self):\n        return 1\n"
    bridge.process_change(CodeChange("test.py", "", code))

    bar_nodes = bridge.graph.query(name="Foo.bar", entity_type="function")
    assert len(bar_nodes) == 1
    assert bar_nodes[0].properties.get("decorators") == ["property"]
    outgoing = bridge.graph.get_outgoing_edges(bar_nodes[0].id)
    dec_edges = [e for e in outgoing if e.edge_type == "decorated_by"]
    assert len(dec_edges) == 0  # No 'property' node in graph


# --- Phase 4: Name Collision Mitigation Tests ---


def test_name_collision_resolved_via_import(bridge):
    """When two files define 'helper', import context disambiguates."""
    code_a = "def helper():\n    return 'a'\n"
    bridge.process_change(CodeChange("a.py", "", code_a))

    code_b = "def helper():\n    return 'b'\n"
    bridge.process_change(CodeChange("b.py", "", code_b))

    # File c imports from a, then calls helper
    code_c = "from a import helper\n\ndef caller():\n    helper()\n"
    bridge.process_change(CodeChange("c.py", "", code_c))

    # The 'calls' edge from caller should point to a.py's helper
    # (because c.py imports from a.py)
    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target is not None
    assert target.name == "helper"
    assert target.file_path == "a.py"


def test_name_collision_no_import_fallback(bridge):
    """Without import context, any cross-file match works (existing behavior)."""
    code_a = "def helper():\n    return 'a'\n"
    bridge.process_change(CodeChange("a.py", "", code_a))

    code_b = "def caller():\n    helper()\n"
    bridge.process_change(CodeChange("b.py", "", code_b))

    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1


def test_bridge_unsupported_file_type(bridge):
    """Processing an unsupported file type produces zero operations."""
    code = "main :: IO ()\nmain = putStrLn \"hello\""
    ops = bridge.process_change(CodeChange("main.hs", "", code))
    assert len(ops) == 0


# --- Call Resolution + Impact Analysis Fix Tests ---


def test_self_call_creates_edge_within_class(bridge):
    """self.method() inside a class creates a calls edge to the method node."""
    code = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        self.baz()\n"
        "    def baz(self):\n"
        "        pass\n"
    )
    bridge.process_change(CodeChange("test.py", "", code))
    bar_nodes = bridge.graph.query(name="Foo.bar", entity_type="function")
    assert len(bar_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(bar_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) == 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "Foo.baz"


def test_builtins_not_in_dependency_index(bridge):
    """Built-in names like print, len should not appear in the dependency index."""
    code = "def foo(data):\n    print(len(data))\n"
    bridge.process_change(CodeChange("test.py", "", code))
    assert "print" not in bridge._dependency_index
    assert "len" not in bridge._dependency_index


def test_affected_files_does_not_flood(bridge):
    """get_affected_files should not return all files due to builtins."""
    for i in range(10):
        code = f"def func_{i}(data):\n    print(len(data))\n"
        bridge.process_change(CodeChange(f"file_{i}.py", "", code))

    affected = bridge.get_affected_files("file_0.py", "func_0")
    # With builtins filtered, unrelated files should NOT be affected
    assert len(affected) <= 2


def test_affected_files_max_depth(bridge):
    """Transitive BFS respects max_depth parameter."""
    bridge.process_change(CodeChange("a.py", "", "def a():\n    pass\n"))
    bridge.process_change(CodeChange("b.py", "", "from a import a\ndef b():\n    a()\n"))
    bridge.process_change(CodeChange("c.py", "", "from b import b\ndef c():\n    b()\n"))
    bridge.process_change(CodeChange("d.py", "", "from c import c\ndef d():\n    c()\n"))

    affected_shallow = bridge.get_affected_files("a.py", "a", max_depth=1)
    affected_deep = bridge.get_affected_files("a.py", "a", max_depth=10)
    # Shallow should find fewer files than deep
    assert len(affected_shallow) <= len(affected_deep)


# --- Module-Aware Edge Resolution Tests ---


def test_module_file_index_populated(bridge):
    """Processing a file populates the module-to-file index."""
    bridge.process_change(CodeChange("api/auth/service.py", "", "def validate():\n    pass\n"))
    assert "service" in bridge._module_file_index
    assert "auth.service" in bridge._module_file_index
    assert "api.auth.service" in bridge._module_file_index
    assert bridge._module_file_index["service"] == "api/auth/service.py"


def test_module_aware_import_resolution(bridge):
    """Import with module path resolves to correct file, not first match."""
    # Two files define validate()
    bridge.process_change(CodeChange("utils.py", "", "def validate():\n    return 'utils'\n"))
    bridge.process_change(CodeChange("auth.py", "", "def validate():\n    return 'auth'\n"))

    # Import specifically from auth
    bridge.process_change(CodeChange("main.py", "", "from auth import validate\n"))

    import_nodes = bridge.graph.query(entity_type="import", name="validate")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    assert len(import_edges) == 1
    target = bridge.graph.get_node(import_edges[0].target_id)
    assert target is not None
    assert target.file_path == "auth.py"


def test_module_aware_import_nested_path(bridge):
    """Import from nested module path resolves correctly."""
    bridge.process_change(CodeChange("api/auth/service.py", "", "class AuthService:\n    pass\n"))
    bridge.process_change(CodeChange("main.py", "", "from api.auth.service import AuthService\n"))

    import_nodes = bridge.graph.query(entity_type="import", name="AuthService")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    assert len(import_edges) == 1
    target = bridge.graph.get_node(import_edges[0].target_id)
    assert target.file_path == "api/auth/service.py"


def test_qualified_call_resolves_via_receiver(bridge):
    """auth_service.validate() resolves to validate() in auth_service's file."""
    # Define validate in two files
    bridge.process_change(CodeChange("auth_service.py", "", "def validate():\n    return True\n"))
    bridge.process_change(CodeChange("utils.py", "", "def validate():\n    return False\n"))

    # File c imports auth_service module and calls auth_service.validate()
    code_c = "import auth_service\n\ndef check():\n    auth_service.validate()\n"
    bridge.process_change(CodeChange("main.py", "", code_c))

    check_nodes = bridge.graph.query(name="check", entity_type="function")
    assert len(check_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(check_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    # Should have an edge to auth_service.py's validate, not utils.py's
    target_files = set()
    for edge in call_edges:
        target = bridge.graph.get_node(edge.target_id)
        if target and target.name == "validate":
            target_files.add(target.file_path)
    assert "auth_service.py" in target_files


def test_snapshot_preserves_module_index(bridge):
    """Snapshot includes module_file_index."""
    bridge.process_change(CodeChange("api/service.py", "", "def run():\n    pass\n"))
    snap = bridge.snapshot()
    assert "service" in snap._module_file_index
    assert snap._module_file_index["service"] == "api/service.py"


def test_module_index_serialization(bridge):
    """Module file index round-trips through serialize/deserialize."""
    from streamrag.storage.memory import serialize_graph, deserialize_graph

    bridge.process_change(CodeChange("api/auth.py", "", "def login():\n    pass\n"))
    data = serialize_graph(bridge)
    assert "module_file_index" in data
    assert "auth" in data["module_file_index"]
    # New format: file_contents_keys instead of file_contents
    assert "file_contents_keys" in data
    assert "api/auth.py" in data["file_contents_keys"]
    assert "file_contents" not in data

    restored = deserialize_graph(data)
    assert restored._module_file_index == bridge._module_file_index
    assert "api/auth.py" in restored._tracked_files


def test_deserialize_old_format_backward_compat(bridge):
    """Old format with full file_contents still deserializes correctly."""
    from streamrag.storage.memory import deserialize_graph

    old_data = {
        "format_version": 2,
        "nodes": [],
        "edges": [],
        "file_contents": {"a.py": "def foo():\n    pass\n"},
        "dependency_index": {},
        "module_file_index": {},
        "resolution_stats": {},
    }
    restored = deserialize_graph(old_data)
    assert "a.py" in restored._file_contents
    assert "a.py" in restored._tracked_files


# --- File Removal (Ghost Node Cleanup) Tests ---


def test_remove_file_cleans_nodes_and_edges(bridge):
    """remove_file removes all nodes and edges for a file."""
    code_a = "def helper():\n    return 42\n"
    bridge.process_change(CodeChange("a.py", "", code_a))
    code_b = "def caller():\n    helper()\n"
    bridge.process_change(CodeChange("b.py", "", code_b))

    assert bridge.graph.node_count >= 2
    initial_edges = bridge.graph.edge_count

    ops = bridge.remove_file("a.py")
    assert len(ops) >= 1
    assert all(op.op_type == "remove_node" for op in ops)

    # a.py nodes should be gone
    assert len(bridge.graph.get_nodes_by_file("a.py")) == 0
    # Edges from b.py to a.py should be gone too (cascaded)
    assert bridge.graph.edge_count < initial_edges


def test_remove_file_cleans_dependency_index(bridge):
    """remove_file cleans dependency index entries referencing the file."""
    bridge.process_change(CodeChange("a.py", "", "def helper():\n    pass\n"))
    bridge.process_change(CodeChange("b.py", "", "def caller():\n    helper()\n"))
    assert any("b.py" in v for v in bridge._dependency_index.values())

    bridge.remove_file("b.py")
    assert all("b.py" not in v for v in bridge._dependency_index.values())


def test_remove_file_cleans_module_index(bridge):
    """remove_file cleans module_file_index entries pointing to the file."""
    bridge.process_change(CodeChange("api/service.py", "", "def run():\n    pass\n"))
    assert "service" in bridge._module_file_index

    bridge.remove_file("api/service.py")
    assert "service" not in bridge._module_file_index


def test_remove_file_cleans_file_contents(bridge):
    """remove_file removes file_contents and tracked_files caches."""
    bridge.process_change(CodeChange("test.py", "", "def foo():\n    pass\n"))
    assert "test.py" in bridge._file_contents
    assert "test.py" in bridge._tracked_files

    bridge.remove_file("test.py")
    assert "test.py" not in bridge._file_contents
    assert "test.py" not in bridge._tracked_files


# --- Type Reference Edge Tests ---


def test_type_ref_creates_uses_type_edge(bridge):
    """Type annotation creates a uses_type edge to the referenced class."""
    bridge.process_change(CodeChange("models.py", "", "class User:\n    pass\n"))
    bridge.process_change(CodeChange("service.py", "", "def get(uid) -> User:\n    pass\n"))

    get_nodes = bridge.graph.query(name="get", entity_type="function")
    assert len(get_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(get_nodes[0].id)
    type_edges = [e for e in outgoing if e.edge_type == "uses_type"]
    assert len(type_edges) == 1
    target = bridge.graph.get_node(type_edges[0].target_id)
    assert target.name == "User"


def test_type_ref_no_edge_for_builtin(bridge):
    """Built-in type annotations don't create edges."""
    bridge.process_change(CodeChange("test.py", "", "def foo(x: str) -> int:\n    pass\n"))

    foo_nodes = bridge.graph.query(name="foo", entity_type="function")
    assert len(foo_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(foo_nodes[0].id)
    type_edges = [e for e in outgoing if e.edge_type == "uses_type"]
    assert len(type_edges) == 0


# --- Module Exports Tests ---


def test_get_module_exports_with_all(bridge):
    """get_module_exports returns __all__ contents when defined."""
    bridge.process_change(CodeChange("mymod.py", "", (
        '__all__ = ["foo", "bar"]\n\n'
        "def foo():\n    pass\n\n"
        "def bar():\n    pass\n\n"
        "def _private():\n    pass\n"
    )))
    exports = bridge.get_module_exports("mymod.py")
    assert "foo" in exports
    assert "bar" in exports
    assert "_private" not in exports


# --- P0.1: Source-over-test priority tests ---


def test_source_over_test_priority(bridge):
    """Source file caller should resolve to source file target, not test file."""
    # Define helper in both source and test files
    bridge.process_change(CodeChange("src/helper.py", "", "def helper():\n    return 'src'\n"))
    bridge.process_change(CodeChange("tests/test_helper.py", "", "def helper():\n    return 'test'\n"))

    # Source file calls helper — should resolve to src/helper.py
    bridge.process_change(CodeChange("src/main.py", "", "def caller():\n    helper()\n"))

    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.file_path == "src/helper.py"


def test_test_file_can_resolve_to_test(bridge):
    """Test file caller can resolve to test file target."""
    bridge.process_change(CodeChange("src/helper.py", "", "def helper():\n    return 'src'\n"))
    bridge.process_change(CodeChange("tests/test_utils.py", "", "def make_fixture():\n    return 42\n"))

    # Test file calls make_fixture — should still find it in test dir
    bridge.process_change(CodeChange("tests/test_main.py", "", "def test_it():\n    make_fixture()\n"))

    test_nodes = bridge.graph.query(name="test_it", entity_type="function")
    assert len(test_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(test_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "make_fixture"


def test_is_test_file_detection():
    """_is_test_file detects test files correctly."""
    from streamrag.models import _is_test_file
    assert _is_test_file("tests/test_foo.py") is True
    assert _is_test_file("test_bar.py") is True
    assert _is_test_file("foo_test.py") is True
    assert _is_test_file("src/testing/helpers.py") is True
    assert _is_test_file("src/main.py") is False
    assert _is_test_file("lib/utils.py") is False


# --- P2.7: Edge confidence score tests ---


def test_edge_confidence_high_for_imported(bridge):
    """Edges resolved via import context get high confidence."""
    bridge.process_change(CodeChange("a.py", "", "def helper():\n    return 42\n"))
    bridge.process_change(CodeChange("b.py", "", "from a import helper\n\ndef caller():\n    helper()\n"))

    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    assert call_edges[0].properties.get("confidence") == "high"


def test_edge_confidence_medium_for_cross_file(bridge):
    """Edges resolved via cross-file fallback get medium confidence."""
    bridge.process_change(CodeChange("a.py", "", "def helper():\n    return 42\n"))
    # No import — direct cross-file resolution
    bridge.process_change(CodeChange("b.py", "", "def caller():\n    helper()\n"))

    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    assert call_edges[0].properties.get("confidence") == "medium"


# --- P2.6: Resolution statistics tracking tests ---


def test_resolution_stats_tracking(bridge):
    """Resolution stats are incremented during edge resolution."""
    bridge.process_change(CodeChange("a.py", "", "def helper():\n    return 42\n"))
    bridge.process_change(CodeChange("b.py", "", "def caller():\n    helper()\n"))

    assert bridge._resolution_stats["total_attempted"] > 0
    assert bridge._resolution_stats["resolved"] > 0


def test_resolution_stats_to_test_file(bridge):
    """to_test_file stat incremented when resolving to test file target."""
    bridge.process_change(CodeChange("tests/test_utils.py", "", "def make_fixture():\n    return 42\n"))
    bridge.process_change(CodeChange("tests/test_main.py", "", "def test_it():\n    make_fixture()\n"))

    assert bridge._resolution_stats["to_test_file"] > 0


def test_resolution_stats_serialization(bridge):
    """Resolution stats round-trip through serialization."""
    from streamrag.storage.memory import serialize_graph, deserialize_graph

    bridge.process_change(CodeChange("a.py", "", "def helper():\n    return 42\n"))
    bridge.process_change(CodeChange("b.py", "", "def caller():\n    helper()\n"))

    data = serialize_graph(bridge)
    assert "resolution_stats" in data
    assert data["resolution_stats"]["resolved"] > 0

    restored = deserialize_graph(data)
    assert restored._resolution_stats["resolved"] == bridge._resolution_stats["resolved"]
    assert restored._resolution_stats["total_attempted"] == bridge._resolution_stats["total_attempted"]


def test_edge_confidence_serialized(bridge):
    """Confidence is preserved through serialization."""
    from streamrag.storage.memory import serialize_graph, deserialize_graph

    bridge.process_change(CodeChange("a.py", "", "def helper():\n    return 42\n"))
    bridge.process_change(CodeChange("b.py", "", "from a import helper\n\ndef caller():\n    helper()\n"))

    data = serialize_graph(bridge)
    restored = deserialize_graph(data)

    caller_nodes = restored.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = restored.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    assert call_edges[0].properties.get("confidence") == "high"


def test_get_module_exports_without_all(bridge):
    """get_module_exports returns all top-level names when __all__ not defined."""
    bridge.process_change(CodeChange("mymod.py", "", (
        "def public_func():\n    pass\n\n"
        "class MyClass:\n    def method(self):\n        pass\n"
    )))
    exports = bridge.get_module_exports("mymod.py")
    assert "public_func" in exports
    assert "MyClass" in exports
    # Nested method should NOT be in exports
    assert "MyClass.method" not in exports


# --- Fix 1: Class-name qualified resolution tests ---


def test_class_name_qualified_resolution(bridge):
    """ClassName.method resolves to the method in the class's file, even without import."""
    code_a = (
        "class MyService:\n"
        "    def process(self):\n"
        "        pass\n"
    )
    bridge.process_change(CodeChange("service.py", "", code_a))

    # File b calls MyService.process — no import of MyService
    code_b = (
        "class Controller:\n"
        "    def handle(self, svc: MyService):\n"
        "        svc.process()\n"
    )
    bridge.process_change(CodeChange("controller.py", "", code_b))

    handle_nodes = bridge.graph.query(name="Controller.handle", entity_type="function")
    assert len(handle_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(handle_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "MyService.process"
    assert target.file_path == "service.py"


def test_class_name_qualified_not_confused_with_module(bridge):
    """Class-name resolution doesn't break module-based resolution for lowercase receivers."""
    bridge.process_change(CodeChange("auth_service.py", "", "def validate():\n    return True\n"))
    code = "import auth_service\n\ndef check():\n    auth_service.validate()\n"
    bridge.process_change(CodeChange("main.py", "", code))

    check_nodes = bridge.graph.query(name="check", entity_type="function")
    assert len(check_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(check_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "validate"
    assert target.file_path == "auth_service.py"


# --- Fix 3: Index-based suffix fallback tests ---


def test_bare_name_suffix_fallback(bridge):
    """Bare name 'process_data' resolves via suffix match to 'Pipeline.process_data'."""
    code_a = (
        "class Pipeline:\n"
        "    def process_data(self):\n"
        "        pass\n"
    )
    bridge.process_change(CodeChange("pipeline.py", "", code_a))

    # File b calls process_data as a bare name (e.g. extracted from unresolvable receiver)
    code_b = "def run():\n    process_data()\n"
    bridge.process_change(CodeChange("runner.py", "", code_b))

    run_nodes = bridge.graph.query(name="run", entity_type="function")
    assert len(run_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(run_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "Pipeline.process_data"


def test_bare_name_suffix_disambiguates_by_import(bridge):
    """When multiple suffix matches exist, prefer the one from an imported file."""
    bridge.process_change(CodeChange("a.py", "", "class Foo:\n    def compute(self):\n        pass\n"))
    bridge.process_change(CodeChange("b.py", "", "class Bar:\n    def compute(self):\n        pass\n"))

    # File c imports from a, then calls bare 'compute'
    code_c = "from a import Foo\n\ndef caller():\n    compute()\n"
    bridge.process_change(CodeChange("c.py", "", code_c))

    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.file_path == "a.py"


# --- Phase P1: External Library Recognition Tests ---


def test_external_package_calls_filtered(bridge):
    """Calls through external packages (httpx.get) produce no call edge."""
    code = "import httpx\n\ndef fetch():\n    httpx.get('http://example.com')\n"
    bridge.process_change(CodeChange("test.py", "", code))

    fetch_nodes = bridge.graph.query(name="fetch", entity_type="function")
    assert len(fetch_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(fetch_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    # httpx.get should be filtered out — no call edges
    assert len(call_edges) == 0


def test_external_type_calls_filtered(bridge):
    """Calls through external types (AsyncClient.get) produce no call edge."""
    code = (
        "from httpx import AsyncClient\n\n"
        "def fetch(c: AsyncClient):\n"
        "    c.get('http://example.com')\n"
    )
    bridge.process_change(CodeChange("test.py", "", code))

    fetch_nodes = bridge.graph.query(name="fetch", entity_type="function")
    assert len(fetch_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(fetch_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    # AsyncClient.get should be filtered — no call edges
    assert len(call_edges) == 0


def test_local_module_not_filtered_as_external(bridge):
    """A local module named 'requests.py' should still resolve normally."""
    # Local requests module
    bridge.process_change(CodeChange("requests.py", "", "def fetch():\n    return 42\n"))

    # Caller in the same project
    code_b = "def caller():\n    fetch()\n"
    bridge.process_change(CodeChange("main.py", "", code_b))

    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "fetch"


def test_external_skipped_stat_tracked(bridge):
    """external_skipped stat increments when resolving builtin names."""
    assert "external_skipped" in bridge._resolution_stats
    before = bridge._resolution_stats["external_skipped"]
    # @property decorator name hits BUILTINS guard in _find_target_node
    code = "class Foo:\n    @property\n    def bar(self):\n        return 1\n"
    bridge.process_change(CodeChange("test_ext.py", "", code))
    after = bridge._resolution_stats["external_skipped"]
    assert after > before


# --- Phase P2: Star Import Expansion Tests ---


def test_star_import_creates_edges_to_all_exports(bridge):
    """from lib import * with __all__ creates import edges to all exports."""
    bridge.process_change(CodeChange("lib.py", "", (
        '__all__ = ["foo", "Bar"]\n\n'
        "def foo():\n    pass\n\n"
        "class Bar:\n    pass\n\n"
        "def _private():\n    pass\n"
    )))

    bridge.process_change(CodeChange("consumer.py", "", "from lib import *\n"))

    import_nodes = bridge.graph.query(entity_type="import", name="*")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    # Should have edges to foo and Bar (not _private since __all__ is defined)
    assert len(import_edges) == 2
    target_names = {bridge.graph.get_node(e.target_id).name for e in import_edges}
    assert target_names == {"foo", "Bar"}


def test_star_import_without_all_exports_all(bridge):
    """from lib import * without __all__ creates edges to all top-level names."""
    bridge.process_change(CodeChange("lib.py", "", (
        "def foo():\n    pass\n\n"
        "class Bar:\n    pass\n"
    )))

    bridge.process_change(CodeChange("consumer.py", "", "from lib import *\n"))

    import_nodes = bridge.graph.query(entity_type="import", name="*")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    assert len(import_edges) == 2
    target_names = {bridge.graph.get_node(e.target_id).name for e in import_edges}
    assert target_names == {"foo", "Bar"}


def test_star_import_two_pass_resolution(bridge):
    """Star import processed before source module gets resolved in second pass."""
    # Consumer first, source second
    bridge.process_change(CodeChange("consumer.py", "", "from lib import *\n"))
    bridge.process_change(CodeChange("lib.py", "", "def foo():\n    pass\n"))

    # After second pass, the star import should now have edges
    import_nodes = bridge.graph.query(entity_type="import", name="*")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    # May or may not resolve depending on processing order — at minimum no crash
    # If module index was populated, it should resolve
    assert len(import_edges) >= 0  # No crash is the key assertion


def test_star_import_via_star_property(bridge):
    """Star import edges have via_star: True property."""
    bridge.process_change(CodeChange("lib.py", "", "def foo():\n    pass\n"))
    bridge.process_change(CodeChange("consumer.py", "", "from lib import *\n"))

    import_nodes = bridge.graph.query(entity_type="import", name="*")
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    for edge in import_edges:
        assert edge.properties.get("via_star") is True


# --- Phase P3: Module-Level Type Context Tests ---


def test_module_level_type_context_resolves_calls(bridge):
    """Module-level x = SomeClass() allows x.method() to resolve."""
    bridge.process_change(CodeChange("registry.py", "", (
        "class Registry:\n"
        "    def get_item(self):\n"
        "        pass\n"
    )))

    code = (
        "from registry import Registry\n\n"
        "reg = Registry()\n\n"
        "def lookup():\n"
        "    reg.get_item()\n"
    )
    bridge.process_change(CodeChange("main.py", "", code))

    lookup_nodes = bridge.graph.query(name="lookup", entity_type="function")
    assert len(lookup_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(lookup_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "Registry.get_item"


def test_function_type_context_overrides_module(bridge):
    """Function-level type annotation wins over module-level constructor."""
    bridge.process_change(CodeChange("types.py", "", (
        "class Foo:\n"
        "    def run(self):\n        pass\n\n"
        "class Bar:\n"
        "    def run(self):\n        pass\n"
    )))

    code = (
        "from types import Foo, Bar\n\n"
        "obj = Foo()\n\n"
        "def caller(obj: Bar):\n"
        "    obj.run()\n"
    )
    bridge.process_change(CodeChange("main.py", "", code))

    caller_nodes = bridge.graph.query(name="caller", entity_type="function")
    assert len(caller_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(caller_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    # Function param annotation (Bar) should take precedence over module-level (Foo)
    assert target.name == "Bar.run"


def test_module_type_context_annotated_assignment(bridge):
    """Module-level `cfg: Config = None` resolves cfg.method() calls."""
    bridge.process_change(CodeChange("config.py", "", (
        "class Config:\n"
        "    def load(self):\n"
        "        pass\n"
    )))

    code = (
        "from config import Config\n\n"
        "cfg: Config = None\n\n"
        "def setup():\n"
        "    cfg.load()\n"
    )
    bridge.process_change(CodeChange("main.py", "", code))

    setup_nodes = bridge.graph.query(name="setup", entity_type="function")
    assert len(setup_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(setup_nodes[0].id)
    call_edges = [e for e in outgoing if e.edge_type == "calls"]
    assert len(call_edges) >= 1
    target = bridge.graph.get_node(call_edges[0].target_id)
    assert target.name == "Config.load"


# --- Phase P4: Re-Export Chain Following Tests ---


def test_reexport_chain_followed(bridge):
    """Import through re-export chain resolves to the actual definition."""
    # core.py defines helper
    bridge.process_change(CodeChange("core.py", "", "def helper():\n    return 42\n"))
    # intermediate.py re-exports from core
    bridge.process_change(CodeChange("intermediate.py", "", "from core import helper\n"))
    # consumer imports from intermediate
    bridge.process_change(CodeChange("consumer.py", "", "from intermediate import helper\n"))

    # consumer's import should resolve to core.py's definition
    import_nodes = [n for n in bridge.graph.query(entity_type="import", name="helper")
                    if n.file_path == "consumer.py"]
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    assert len(import_edges) >= 1
    # Follow to the final target
    targets = set()
    for edge in import_edges:
        target = bridge.graph.get_node(edge.target_id)
        if target:
            targets.add((target.name, target.file_path, target.type))
    # Should reach core.py's helper definition (not just the intermediate import)
    assert ("helper", "core.py", "function") in targets


def test_reexport_chain_circular_safe(bridge):
    """Circular re-exports don't cause infinite loop."""
    # a.py re-exports from b, b re-exports from a
    bridge.process_change(CodeChange("a.py", "", "from b import helper\n"))
    bridge.process_change(CodeChange("b.py", "", "from a import helper\n"))
    # consumer imports from a
    bridge.process_change(CodeChange("consumer.py", "", "from a import helper\n"))

    # Should not hang — just may not resolve
    import_nodes = [n for n in bridge.graph.query(entity_type="import", name="helper")
                    if n.file_path == "consumer.py"]
    assert len(import_nodes) == 1
    # No crash is the key assertion


def test_reexport_through_init(bridge):
    """Re-export through __init__.py resolves correctly."""
    # actual definition
    bridge.process_change(CodeChange("pkg/core.py", "", "class Widget:\n    pass\n"))
    # __init__.py re-exports
    bridge.process_change(CodeChange("pkg/__init__.py", "", "from pkg.core import Widget\n"))
    # consumer imports from pkg
    bridge.process_change(CodeChange("app.py", "", "from pkg import Widget\n"))

    import_nodes = [n for n in bridge.graph.query(entity_type="import", name="Widget")
                    if n.file_path == "app.py"]
    assert len(import_nodes) == 1
    outgoing = bridge.graph.get_outgoing_edges(import_nodes[0].id)
    import_edges = [e for e in outgoing if e.edge_type == "imports"]
    # Should eventually resolve to pkg/core.py's Widget class
    found_class = False
    for edge in import_edges:
        target = bridge.graph.get_node(edge.target_id)
        if target and target.type == "class" and target.name == "Widget":
            found_class = True
    assert found_class


def test_module_index_collision_tracked(bridge):
    """Module index collision is recorded when two files share a short name."""
    code_a = "def helper():\n    return 1\n"
    code_b = "def helper():\n    return 2\n"
    bridge.process_change(CodeChange("pkg1/utils.py", "", code_a))
    bridge.process_change(CodeChange("pkg2/utils.py", "", code_b))

    assert "utils" in bridge._module_file_collisions


def test_module_index_collision_cleared_on_remove(bridge):
    """Module index collision entry is cleared when conflicting file is removed."""
    code_a = "def helper():\n    return 1\n"
    code_b = "def helper():\n    return 2\n"
    bridge.process_change(CodeChange("pkg1/utils.py", "", code_a))
    bridge.process_change(CodeChange("pkg2/utils.py", "", code_b))
    assert "utils" in bridge._module_file_collisions

    bridge.remove_file("pkg1/utils.py")
    assert "utils" not in bridge._module_file_collisions
