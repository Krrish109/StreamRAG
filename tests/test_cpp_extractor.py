"""Tests for CppExtractor."""

from streamrag.languages.cpp import CppExtractor


def _ext():
    return CppExtractor()


# ── 1. can_handle() ─────────────────────────────────────────────────────

def test_can_handle_cpp_extensions():
    ext = _ext()
    for suffix in (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"):
        assert ext.can_handle(f"foo{suffix}"), f"Expected True for {suffix}"


def test_can_handle_rejects_c_and_py():
    ext = _ext()
    assert not ext.can_handle("main.c"), ".c should be handled by CExtractor"
    assert not ext.can_handle("main.py"), ".py is not C++"


# ── 2. language_id ──────────────────────────────────────────────────────

def test_language_id():
    assert _ext().language_id == "cpp"


# ── 3. Function extraction ──────────────────────────────────────────────

def test_extract_regular_function():
    code = "int compute(int a, int b) {\n    return a + b;\n}\n"
    entities = _ext().extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "compute"
    assert funcs[0].line_start == 1


def test_extract_static_inline_virtual_functions():
    code = (
        "static int helper(int x) {\n    return x;\n}\n"
        "inline void fast() {\n    return;\n}\n"
        "virtual void draw() {\n    return;\n}\n"
    )
    entities = _ext().extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    names = {f.name for f in funcs}
    assert "helper" in names, f"static function not found, got {names}"
    assert "fast" in names, f"inline function not found, got {names}"
    assert "draw" in names, f"virtual function not found, got {names}"


# ── 4. Constructor extraction ───────────────────────────────────────────

def test_extract_constructor():
    code = (
        "class Widget {\n"
        "    Widget(int x) {\n"
        "        m_x = x;\n"
        "    }\n"
        "};\n"
    )
    entities = _ext().extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    ctor_names = [f.name for f in funcs]
    # Constructor should be scoped under Widget
    assert any("Widget" in n for n in ctor_names), (
        f"Constructor not found, got {ctor_names}"
    )


# ── 5. Class extraction with inheritance ────────────────────────────────

def test_extract_class_with_inheritance():
    code = "class Derived : public Base {\n    int x;\n};\n"
    entities = _ext().extract(code)
    classes = [e for e in entities if e.entity_type == "class"]
    assert len(classes) == 1
    assert classes[0].name == "Derived"
    assert "Base" in classes[0].inherits


# ── 6. Struct extraction with inheritance ───────────────────────────────

def test_extract_struct_with_inheritance():
    code = "struct Point3D : public Point2D {\n    int z;\n};\n"
    entities = _ext().extract(code)
    classes = [e for e in entities if e.entity_type == "class"]
    assert len(classes) == 1
    assert classes[0].name == "Point3D"
    assert "Point2D" in classes[0].inherits


# ── 7. Enum / enum class ───────────────────────────────────────────────

def test_extract_enum_and_enum_class():
    code = (
        "enum Color {\n    Red,\n    Green,\n    Blue\n};\n"
        "enum class Direction : int {\n    Up,\n    Down\n};\n"
    )
    entities = _ext().extract(code)
    classes = [e for e in entities if e.entity_type == "class"]
    names = {c.name for c in classes}
    assert "Color" in names
    assert "Direction" in names


# ── 8. Namespace extraction ─────────────────────────────────────────────

def test_extract_namespace():
    code = "namespace MyLib {\n    int helper() { return 0; }\n}\n"
    entities = _ext().extract(code)
    classes = [e for e in entities if e.entity_type == "class"]
    ns_names = [c.name for c in classes]
    assert "MyLib" in ns_names


# ── 9. using alias extraction ──────────────────────────────────────────

def test_extract_using_alias():
    code = "using StringVec = std::vector<std::string>;\n"
    entities = _ext().extract(code)
    variables = [e for e in entities if e.entity_type == "variable"]
    assert len(variables) >= 1
    names = {v.name for v in variables}
    assert "StringVec" in names


# ── 10. typedef extraction ─────────────────────────────────────────────

def test_extract_typedef():
    code = "typedef unsigned long ulong;\n"
    entities = _ext().extract(code)
    variables = [e for e in entities if e.entity_type == "variable"]
    names = {v.name for v in variables}
    assert "ulong" in names


# ── 11. #include "local" import extraction ──────────────────────────────

def test_extract_include_local():
    code = '#include "myheader.h"\n'
    entities = _ext().extract(code)
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    # Local includes use "." as module and the path as the name
    assert imports[0].imports == [(".", "myheader.h")]


# ── 12. #include <system> import extraction ─────────────────────────────

def test_extract_include_system():
    code = "#include <iostream>\n"
    entities = _ext().extract(code)
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    # System includes use "" as module
    assert imports[0].imports == [("", "iostream")]


# ── 13. using namespace import extraction ───────────────────────────────

def test_extract_using_namespace():
    code = "using namespace std;\n"
    entities = _ext().extract(code)
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].imports == [("std", "std")]


# ── 14. Nested class method gets scoped name ───────────────────────────

def test_nested_class_method_scoped_name():
    code = (
        "class Engine {\n"
        "    int start(int rpm) {\n"
        "        return rpm;\n"
        "    }\n"
        "};\n"
    )
    entities = _ext().extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    scoped_names = [f.name for f in funcs]
    assert any(n == "Engine.start" for n in scoped_names), (
        f"Expected 'Engine.start', got {scoped_names}"
    )


# ── 15. Template function / class extraction ───────────────────────────

def test_extract_template_function():
    code = "template <typename T>\nT identity(T val) {\n    return val;\n}\n"
    entities = _ext().extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    names = {f.name for f in funcs}
    assert "identity" in names


def test_extract_template_class():
    code = "template <typename T>\nclass Container {\n    T value;\n};\n"
    entities = _ext().extract(code)
    classes = [e for e in entities if e.entity_type == "class"]
    names = {c.name for c in classes}
    assert "Container" in names


# ── 16. Empty input returns [] ──────────────────────────────────────────

def test_empty_input_returns_empty():
    assert _ext().extract("") == []
    assert _ext().extract("   \n  \n") == []


# ── 17. Comment stripping ──────────────────────────────────────────────

def test_comment_stripping_line_comment():
    """Entities inside line comments should not be extracted."""
    code = (
        "// int hidden(int x) {\n"
        "int visible(int x) {\n"
        "    return x;\n"
        "}\n"
    )
    entities = _ext().extract(code)
    funcs = [e for e in entities if e.entity_type == "function"]
    names = {f.name for f in funcs}
    assert "visible" in names
    assert "hidden" not in names


def test_comment_stripping_block_comment():
    """Entities inside block comments should not be extracted."""
    code = (
        "/* class Phantom {\n"
        "    int spooky() { return 0; }\n"
        "}; */\n"
        "class Real {\n"
        "    int solid() {\n"
        "        return 1;\n"
        "    }\n"
        "};\n"
    )
    entities = _ext().extract(code)
    all_names = {e.name for e in entities}
    assert "Real" in all_names
    assert "Phantom" not in all_names
    assert "spooky" not in all_names
