"""Tests for the RegexExtractor base class.

Uses TypeScriptExtractor as the concrete subclass to exercise shared
base behavior defined in regex_base.py.
"""

import pytest

from streamrag.languages.regex_base import RegexExtractor
from streamrag.languages.typescript import TypeScriptExtractor
from streamrag.models import ASTEntity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extractor() -> TypeScriptExtractor:
    return TypeScriptExtractor()


# ---------------------------------------------------------------------------
# 1. RegexExtractor cannot be instantiated directly (ABC)
# ---------------------------------------------------------------------------

def test_regex_extractor_is_abstract():
    """RegexExtractor is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError):
        RegexExtractor()


# ---------------------------------------------------------------------------
# 2. Empty input returns []
# ---------------------------------------------------------------------------

def test_extract_empty_string():
    ext = _make_extractor()
    assert ext.extract("", "test.ts") == []


def test_extract_whitespace_only():
    ext = _make_extractor()
    assert ext.extract("   \n\n  \t  ", "test.ts") == []


# ---------------------------------------------------------------------------
# 3. Comment stripping — single-line //
# ---------------------------------------------------------------------------

def test_strip_single_line_comment():
    ext = _make_extractor()
    source = "// function hidden() {}\nfunction visible() { return 1; }"
    entities = ext.extract(source, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "visible" in names
    assert "hidden" not in names


# ---------------------------------------------------------------------------
# 4. Comment stripping — block /* ... */
# ---------------------------------------------------------------------------

def test_strip_block_comment():
    ext = _make_extractor()
    source = "/* function hidden() {} */\nfunction visible() { return 1; }"
    entities = ext.extract(source, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "visible" in names
    assert "hidden" not in names


# ---------------------------------------------------------------------------
# 5. Comment stripping preserves line numbers
# ---------------------------------------------------------------------------

def test_comment_stripping_preserves_line_numbers():
    ext = _make_extractor()
    source = (
        "// line 1 comment\n"
        "// line 2 comment\n"
        "function foo() {\n"
        "  return 42;\n"
        "}\n"
    )
    entities = ext.extract(source, "test.ts")
    func = [e for e in entities if e.name == "foo"]
    assert len(func) == 1
    # foo is declared on line 3 (after two comment lines)
    assert func[0].line_start == 3


# ---------------------------------------------------------------------------
# 6. String stripping — single, double, backtick
# ---------------------------------------------------------------------------

def test_strip_single_quoted_string():
    ext = _make_extractor()
    source = "const x = 'function hidden() {}';\nfunction visible() { return 1; }"
    entities = ext.extract(source, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "visible" in names
    assert "hidden" not in names


def test_strip_double_quoted_string():
    ext = _make_extractor()
    source = 'const x = "function hidden() {}";\nfunction visible() { return 1; }'
    entities = ext.extract(source, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "visible" in names
    assert "hidden" not in names


def test_strip_backtick_template_literal():
    ext = _make_extractor()
    source = "const x = `function hidden() {}`;\nfunction visible() { return 1; }"
    entities = ext.extract(source, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "visible" in names
    assert "hidden" not in names


# ---------------------------------------------------------------------------
# 7. String stripping preserves line numbers
# ---------------------------------------------------------------------------

def test_string_stripping_preserves_line_numbers():
    ext = _make_extractor()
    source = (
        'const msg = "hello";\n'
        'const greeting = `world`;\n'
        "function bar() {\n"
        "  return 99;\n"
        "}\n"
    )
    entities = ext.extract(source, "test.ts")
    func = [e for e in entities if e.name == "bar"]
    assert len(func) == 1
    assert func[0].line_start == 3


# ---------------------------------------------------------------------------
# 8. Brace counting (_find_body_end)
# ---------------------------------------------------------------------------

def test_find_body_end_simple():
    ext = _make_extractor()
    lines = [
        "function foo() {",  # line 0
        "  return 1;",       # line 1
        "}",                 # line 2
    ]
    assert ext._find_body_end(lines, 0) == 2


def test_find_body_end_nested_braces():
    ext = _make_extractor()
    lines = [
        "function foo() {",   # 0
        "  if (true) {",      # 1
        "    return 1;",      # 2
        "  }",                # 3
        "}",                  # 4
    ]
    assert ext._find_body_end(lines, 0) == 4


def test_find_body_end_no_closing_brace():
    ext = _make_extractor()
    lines = [
        "function foo() {",
        "  return 1;",
    ]
    # No closing brace -> returns last line index
    assert ext._find_body_end(lines, 0) == 1


# ---------------------------------------------------------------------------
# 9. Call extraction (_extract_calls_from_body) with builtin filtering
# ---------------------------------------------------------------------------

def test_extract_calls_basic():
    ext = _make_extractor()
    body = "  doSomething();\n  handleEvent(x);\n"
    calls = ext._extract_calls_from_body(body)
    assert "doSomething" in calls
    assert "handleEvent" in calls


def test_extract_calls_filters_builtins():
    ext = _make_extractor()
    # console, parseInt, JSON are TS builtins
    body = "  console.log('hi');\n  parseInt('42');\n  myFunc();\n"
    calls = ext._extract_calls_from_body(body)
    assert "myFunc" in calls
    assert "parseInt" not in calls
    assert "console" not in calls


def test_extract_calls_filters_common_methods():
    ext = _make_extractor()
    # push, map, filter are TS common methods
    body = "  push(x);\n  map(fn);\n  customCall();\n"
    calls = ext._extract_calls_from_body(body)
    assert "customCall" in calls
    assert "push" not in calls
    assert "map" not in calls


def test_extract_calls_deduplicates():
    ext = _make_extractor()
    body = "  doStuff();\n  doStuff();\n  doStuff();\n"
    calls = ext._extract_calls_from_body(body)
    assert calls.count("doStuff") == 1


# ---------------------------------------------------------------------------
# 10. Hash computation (_compute_signature_hash, _compute_structure_hash)
# ---------------------------------------------------------------------------

def test_compute_signature_hash_deterministic():
    ext = _make_extractor()
    text = "function foo() { return 1; }"
    h1 = ext._compute_signature_hash(text)
    h2 = ext._compute_signature_hash(text)
    assert h1 == h2
    assert len(h1) == 12  # SHA256[:12]


def test_compute_signature_hash_changes_on_different_input():
    ext = _make_extractor()
    h1 = ext._compute_signature_hash("function foo() { return 1; }")
    h2 = ext._compute_signature_hash("function foo() { return 2; }")
    assert h1 != h2


def test_compute_structure_hash_rename_invariant():
    ext = _make_extractor()
    text_a = "function alpha() { return 1; }"
    text_b = "function beta() { return 1; }"
    # structure_hash replaces the name with ___, so renamed functions
    # with the same body should produce the same structure hash
    sh_a = ext._compute_structure_hash(text_a, "alpha")
    sh_b = ext._compute_structure_hash(text_b, "beta")
    assert sh_a == sh_b


def test_compute_structure_hash_differs_on_body_change():
    ext = _make_extractor()
    text_a = "function foo() { return 1; }"
    text_b = "function foo() { return 2; }"
    sh_a = ext._compute_structure_hash(text_a, "foo")
    sh_b = ext._compute_structure_hash(text_b, "foo")
    assert sh_a != sh_b


# ---------------------------------------------------------------------------
# 11. Scope tracking (_apply_scoping)
# ---------------------------------------------------------------------------

def test_apply_scoping_nested_method():
    ext = _make_extractor()
    source = (
        "class MyClass {\n"
        "  doWork() {\n"
        "    return 1;\n"
        "  }\n"
        "}\n"
    )
    entities = ext.extract(source, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "MyClass" in names
    assert "MyClass.doWork" in names
    # Bare "doWork" should not appear (it should be scoped)
    assert "doWork" not in names


def test_apply_scoping_preserves_top_level():
    ext = _make_extractor()
    source = (
        "function topLevel() {\n"
        "  return 1;\n"
        "}\n"
        "class Outer {\n"
        "  inner() {\n"
        "    return 2;\n"
        "  }\n"
        "}\n"
    )
    entities = ext.extract(source, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "topLevel" in names
    assert "Outer" in names
    assert "Outer.inner" in names


# ---------------------------------------------------------------------------
# 12. Decorator extraction
# ---------------------------------------------------------------------------

def test_extract_decorators():
    ext = _make_extractor()
    # Decorators sit on lines immediately before the declaration
    source = (
        "@Injectable\n"
        "@Singleton\n"
        "class MyService {\n"
        "}\n"
    )
    entities = ext.extract(source, "test.ts")
    svc = [e for e in entities if e.name == "MyService"]
    assert len(svc) == 1
    assert "Injectable" in svc[0].decorators
    assert "Singleton" in svc[0].decorators


def test_decorators_stop_at_non_decorator_line():
    ext = _make_extractor()
    source = (
        "const x = 1;\n"
        "@Component\n"
        "class Widget {\n"
        "}\n"
    )
    entities = ext.extract(source, "test.ts")
    widget = [e for e in entities if e.name == "Widget"]
    assert len(widget) == 1
    assert widget[0].decorators == ["Component"]
