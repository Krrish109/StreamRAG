"""Tests for ASTExtractor."""

from streamrag.extractor import ASTExtractor, extract


def test_extract_function(extractor):
    code = "def foo(x, y):\n    return x + y\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "foo"
    assert funcs[0].line_start == 1
    assert funcs[0].line_end == 2


def test_extract_async_function(extractor):
    code = "async def fetch(url):\n    return await get(url)\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "fetch"


def test_extract_class(extractor):
    code = "class Foo(Base):\n    def method(self):\n        pass\n"
    entities = extractor.extract(code)
    classes = [e for e in entities if e.entity_type == "class"]
    assert len(classes) == 1
    assert classes[0].name == "Foo"
    assert classes[0].inherits == ["Base"]


def test_extract_nested_method(extractor):
    code = "class Foo:\n    def bar(self):\n        pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "Foo.bar"


def test_extract_module_level_variable(extractor):
    code = "MAX_SIZE = 100\n"
    entities = extractor.extract(code)
    variables = [e for e in entities if e.entity_type == "variable"]
    assert len(variables) == 1
    assert variables[0].name == "MAX_SIZE"


def test_no_variable_inside_function(extractor):
    code = "def foo():\n    x = 1\n"
    entities = extractor.extract(code)
    variables = [e for e in entities if e.entity_type == "variable"]
    assert len(variables) == 0


def test_extract_import(extractor):
    code = "import os\nimport sys\n"
    entities = extractor.extract(code)
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 2


def test_extract_import_from_per_name(extractor):
    code = "from os.path import join, exists\n"
    entities = extractor.extract(code)
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 2
    names = {e.name for e in imports}
    assert names == {"join", "exists"}


def test_extract_module_calls(extractor):
    code = "setup()\nmain()\n"
    entities = extractor.extract(code)
    module_code = [e for e in entities if e.entity_type == "module_code"]
    assert len(module_code) == 1
    assert module_code[0].name == "__module__"
    assert "setup" in module_code[0].calls
    assert "main" in module_code[0].calls


def test_extract_calls(extractor):
    code = "def foo():\n    bar()\n    obj.method()\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert "bar" in funcs[0].calls
    # Qualified call: only "obj.method" emitted (no bare "method" to avoid spurious edges)
    assert "obj.method" in funcs[0].calls


def test_extract_uses(extractor):
    code = "def foo():\n    return x + y\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert "x" in funcs[0].uses
    assert "y" in funcs[0].uses


def test_empty_content_returns_empty(extractor):
    assert extractor.extract("") == []
    assert extractor.extract("   \n\n  ") == []


def test_syntax_error_returns_empty(extractor):
    assert extractor.extract("def foo(:\n") == []


def test_signature_hash_changes_with_body():
    code1 = "def foo():\n    return 1\n"
    code2 = "def foo():\n    return 2\n"
    e1 = extract(code1)[0]
    e2 = extract(code2)[0]
    assert e1.signature_hash != e2.signature_hash


def test_signature_hash_same_for_identical():
    code = "def foo():\n    return 1\n"
    e1 = extract(code)[0]
    e2 = extract(code)[0]
    assert e1.signature_hash == e2.signature_hash


def test_structure_hash_excludes_name():
    code1 = "def foo(x):\n    return x\n"
    code2 = "def bar(x):\n    return x\n"
    e1 = extract(code1)[0]
    e2 = extract(code2)[0]
    # Same structure (same args, same body statement types)
    assert e1.structure_hash == e2.structure_hash
    # Different name means different signature
    assert e1.signature_hash != e2.signature_hash


def test_convenience_extract_function():
    entities = extract("def hello(): pass\n")
    assert len(entities) == 1
    assert entities[0].name == "hello"


def test_deeply_nested_scope(extractor):
    code = """
class Outer:
    class Inner:
        def method(self):
            pass
"""
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert any(e.name == "Outer.Inner.method" for e in funcs)


# --- Decorator extraction tests ---


def test_extract_decorators_simple(extractor):
    code = "@property\ndef foo(self):\n    return 1\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].decorators == ["property"]


def test_extract_decorators_attribute(extractor):
    code = '@app.route("/")\ndef index():\n    pass\n'
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert funcs[0].decorators == ["app.route"]


def test_extract_decorators_call(extractor):
    code = '@pytest.mark.skip(reason="WIP")\ndef test_foo():\n    pass\n'
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert funcs[0].decorators == ["pytest.mark.skip"]


def test_extract_decorators_class(extractor):
    code = "from dataclasses import dataclass\n\n@dataclass\nclass Foo:\n    x: int = 0\n"
    entities = extractor.extract(code)
    classes = [e for e in entities if e.entity_type == "class"]
    assert len(classes) == 1
    assert classes[0].decorators == ["dataclass"]


def test_extract_no_decorators(extractor):
    code = "def plain():\n    pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert funcs[0].decorators == []


def test_extract_multiple_decorators(extractor):
    code = "@staticmethod\n@cache\ndef compute():\n    pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert funcs[0].decorators == ["staticmethod", "cache"]


# --- Call extraction: self/cls qualification and builtin filtering ---


def test_extract_calls_self_qualified(extractor):
    """self.method() inside a class emits 'ClassName.method'."""
    code = "class Foo:\n    def bar(self):\n        self.baz()\n"
    entities = extractor.extract(code)
    bar = [e for e in entities if e.name == "Foo.bar"][0]
    assert "Foo.baz" in bar.calls
    assert "baz" not in bar.calls  # bare name should NOT appear


def test_extract_calls_cls_qualified(extractor):
    """cls.method() inside a class emits 'ClassName.method'."""
    code = "class Foo:\n    @classmethod\n    def bar(cls):\n        cls.baz()\n"
    entities = extractor.extract(code)
    bar = [e for e in entities if e.name == "Foo.bar"][0]
    assert "Foo.baz" in bar.calls


def test_extract_calls_filters_builtins(extractor):
    """Built-in calls like print, len, super are excluded."""
    code = "def foo(data):\n    print(len(data))\n    super().__init__()\n"
    entities = extractor.extract(code)
    foo = [e for e in entities if e.name == "foo"][0]
    assert "print" not in foo.calls
    assert "len" not in foo.calls
    assert "super" not in foo.calls


def test_extract_calls_filters_common_attr_methods(extractor):
    """Common attribute methods like get, append are excluded."""
    code = "def foo(d, lst):\n    d.get('key')\n    lst.append(1)\n"
    entities = extractor.extract(code)
    foo = [e for e in entities if e.name == "foo"][0]
    assert "get" not in foo.calls
    assert "append" not in foo.calls


def test_extract_calls_keeps_custom_attr(extractor):
    """obj.custom_method() (not builtin, not common attr) emits qualified form."""
    code = "def foo(obj):\n    obj.process()\n"
    entities = extractor.extract(code)
    foo = [e for e in entities if e.name == "foo"][0]
    assert "obj.process" in foo.calls


# --- Qualified call extraction tests ---


def test_extract_calls_qualified_receiver(extractor):
    """obj.method() emits only qualified 'obj.method' (no bare to avoid spurious edges)."""
    code = "def foo(auth_service):\n    auth_service.validate()\n"
    entities = extractor.extract(code)
    foo = [e for e in entities if e.name == "foo"][0]
    assert "auth_service.validate" in foo.calls
    assert "validate" not in foo.calls  # No double-counting


def test_extract_calls_qualified_no_builtin_receiver(extractor):
    """Builtin receivers (self, cls) don't emit qualified 'self.method'."""
    code = "class Foo:\n    def bar(self):\n        self.baz()\n"
    entities = extractor.extract(code)
    bar = [e for e in entities if e.name == "Foo.bar"][0]
    assert "Foo.baz" in bar.calls
    # Should NOT have "self.baz" since self is handled specially
    assert "self.baz" not in bar.calls


def test_extract_calls_qualified_filters_common_attr(extractor):
    """Common attr methods like .get() don't emit qualified or bare names."""
    code = "def foo(cache):\n    cache.get('key')\n"
    entities = extractor.extract(code)
    foo = [e for e in entities if e.name == "foo"][0]
    assert "get" not in foo.calls
    assert "cache.get" not in foo.calls


# --- Type annotation extraction tests ---


def test_extract_type_refs_simple(extractor):
    """Simple type annotations are extracted."""
    code = "def process(user: User) -> Response:\n    pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert "User" in funcs[0].type_refs
    assert "Response" in funcs[0].type_refs


def test_extract_type_refs_filters_builtins(extractor):
    """Built-in types like str, int, list are excluded from type_refs."""
    code = "def foo(name: str, count: int) -> list:\n    pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert funcs[0].type_refs == []


def test_extract_type_refs_optional(extractor):
    """Optional[X] extracts X but not Optional."""
    code = "def foo(x: Optional[Config]) -> Optional[str]:\n    pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert "Config" in funcs[0].type_refs
    assert "Optional" not in funcs[0].type_refs


def test_extract_type_refs_no_duplicates(extractor):
    """Same type used multiple times appears only once."""
    code = "def foo(a: User, b: User) -> User:\n    pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert funcs[0].type_refs.count("User") == 1


def test_extract_type_refs_nested_generic(extractor):
    """Nested generics like List[User] extract User."""
    code = "def foo(users: List[User]) -> Dict[str, Response]:\n    pass\n"
    entities = extractor.extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert "User" in funcs[0].type_refs
    assert "Response" in funcs[0].type_refs


# --- __all__ export tracking tests ---


def test_extract_all_list(extractor):
    """__all__ as a list extracts export names into uses."""
    code = '__all__ = ["foo", "bar", "Baz"]\n'
    entities = extractor.extract(code)
    all_vars = [e for e in entities if e.name == "__all__"]
    assert len(all_vars) == 1
    assert "foo" in all_vars[0].uses
    assert "bar" in all_vars[0].uses
    assert "Baz" in all_vars[0].uses


def test_extract_all_tuple(extractor):
    """__all__ as a tuple also works."""
    code = '__all__ = ("alpha", "beta")\n'
    entities = extractor.extract(code)
    all_vars = [e for e in entities if e.name == "__all__"]
    assert len(all_vars) == 1
    assert "alpha" in all_vars[0].uses
    assert "beta" in all_vars[0].uses


def test_extract_calls_type_context_no_bare(extractor):
    """When type context is known, only emit ClassName.method — not bare or receiver.method."""
    code = "def caller(svc: MyService):\n    svc.process_data()\n"
    entities = extractor.extract(code)
    func = [e for e in entities if e.name == "caller"][0]
    assert "MyService.process_data" in func.calls
    assert "svc.process_data" not in func.calls
    assert "process_data" not in func.calls


def test_extract_calls_no_type_context_keeps_bare(extractor):
    """Without type context, only qualified receiver.method is emitted."""
    code = "def caller(svc):\n    svc.process_data()\n"
    entities = extractor.extract(code)
    func = [e for e in entities if e.name == "caller"][0]
    assert "svc.process_data" in func.calls
    assert "process_data" not in func.calls  # No bare duplicate


def test_extract_regular_var_uses_unchanged(extractor):
    """Regular variables still use the standard _extract_uses logic."""
    code = "config = load_config()\n"
    entities = extractor.extract(code)
    vars_ = [e for e in entities if e.entity_type == "variable"]
    assert len(vars_) == 1
    assert "load_config" in vars_[0].uses
