"""Tests for V2 semantic paths."""

from streamrag.v2.semantic_path import (
    SemanticPath, ScopeAwareExtractor, find_entity_at_position, resolve_name,
)


def test_semantic_path_fqn():
    sp = SemanticPath(
        file_path="app.py", scope_chain=("UserService",),
        entity_type="function", name="get_user",
        signature_hash="abc123", line_start=5, line_end=10,
    )
    assert "app.py" in sp.fqn
    assert "UserService" in sp.fqn
    assert "get_user" in sp.fqn


def test_semantic_path_unique_id():
    sp1 = SemanticPath(
        file_path="a.py", scope_chain=(), entity_type="function", name="foo",
        signature_hash="hash1", line_start=1, line_end=5,
    )
    sp2 = SemanticPath(
        file_path="a.py", scope_chain=(), entity_type="function", name="foo",
        signature_hash="hash2", line_start=1, line_end=5,
    )
    assert sp1.unique_id != sp2.unique_id  # Different signature = different ID


def test_semantic_path_frozen():
    sp = SemanticPath(
        file_path="a.py", scope_chain=(), entity_type="function", name="foo",
        signature_hash="abc", line_start=1, line_end=5,
    )
    try:
        sp.name = "bar"
        assert False, "Should be frozen"
    except AttributeError:
        pass


def test_scope_aware_extractor_functions():
    ext = ScopeAwareExtractor("test.py")
    code = "def foo(x, y):\n    return x + y\n"
    paths = ext.extract(code, "test.py")
    funcs = [p for p in paths if p.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "foo"
    assert funcs[0].scope_chain == ()


def test_scope_aware_extractor_parameters():
    ext = ScopeAwareExtractor()
    code = "def foo(x, y):\n    return x + y\n"
    paths = ext.extract(code, "test.py")
    params = [p for p in paths if p.entity_type == "parameter"]
    assert len(params) == 2
    param_names = {p.name for p in params}
    assert param_names == {"x", "y"}
    # Parameters should be scoped under their function
    for p in params:
        assert p.scope_chain == ("foo",)


def test_scope_aware_extractor_nested():
    ext = ScopeAwareExtractor()
    code = """
class MyClass:
    def method(self):
        pass
"""
    paths = ext.extract(code, "test.py")
    methods = [p for p in paths if p.entity_type == "function"]
    assert len(methods) == 1
    assert methods[0].scope_chain == ("MyClass",)


def test_scope_aware_extractor_variables_at_all_scopes():
    ext = ScopeAwareExtractor()
    code = """
x = 1
def foo():
    y = 2
"""
    paths = ext.extract(code, "test.py")
    vars_found = [p for p in paths if p.entity_type == "variable"]
    names = {p.name for p in vars_found}
    assert "x" in names  # Module-level
    assert "y" in names  # Function-level (V2 extracts all scopes)


def test_find_entity_at_position():
    paths = [
        SemanticPath("a.py", (), "class", "Foo", "h1", 1, 10),
        SemanticPath("a.py", ("Foo",), "function", "bar", "h2", 3, 8),
    ]
    # Line 5 is inside both Foo (1-10) and bar (3-8)
    result = find_entity_at_position(paths, 5)
    assert result is not None
    assert result.name == "bar"  # Deeper nested wins


def test_find_entity_at_position_no_match():
    paths = [
        SemanticPath("a.py", (), "function", "foo", "h1", 1, 5),
    ]
    result = find_entity_at_position(paths, 10)
    assert result is None


def test_resolve_name_legb():
    paths = [
        SemanticPath("a.py", (), "variable", "x", "h1", 1, 1),
        SemanticPath("a.py", ("foo",), "variable", "x", "h2", 3, 3),
        SemanticPath("a.py", ("foo", "bar"), "variable", "y", "h3", 5, 5),
    ]
    # From innermost scope (foo, bar), x should resolve to foo.x
    result = resolve_name("x", ("foo", "bar"), paths)
    assert result is not None
    assert result.scope_chain == ("foo",)

    # y should resolve to foo.bar.y
    result = resolve_name("y", ("foo", "bar"), paths)
    assert result is not None
    assert result.scope_chain == ("foo", "bar")


def test_resolve_name_not_found():
    paths = [
        SemanticPath("a.py", (), "variable", "x", "h1", 1, 1),
    ]
    result = resolve_name("nonexistent", (), paths)
    assert result is None


def test_empty_source():
    ext = ScopeAwareExtractor()
    paths = ext.extract("", "test.py")
    assert paths == []


def test_syntax_error():
    ext = ScopeAwareExtractor()
    paths = ext.extract("def broken(:", "test.py")
    assert paths == []
