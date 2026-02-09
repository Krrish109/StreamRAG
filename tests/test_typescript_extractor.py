"""Tests for the TypeScript regex-based extractor."""

import pytest

from streamrag.languages.typescript import TypeScriptExtractor


@pytest.fixture
def ext():
    return TypeScriptExtractor()


# ── 1. can_handle ────────────────────────────────────────────────────────

def test_can_handle_ts_extensions(ext):
    assert ext.can_handle("app.ts") is True
    assert ext.can_handle("component.tsx") is True
    assert ext.can_handle("src/utils/helpers.ts") is True


def test_can_handle_rejects_other_extensions(ext):
    assert ext.can_handle("app.js") is False
    assert ext.can_handle("main.py") is False
    assert ext.can_handle("lib.rs") is False
    assert ext.can_handle("Main.java") is False


# ── 2. language_id ───────────────────────────────────────────────────────

def test_language_id(ext):
    assert ext.language_id == "typescript"


# ── 3. Function extraction ───────────────────────────────────────────────

def test_extract_regular_function(ext):
    code = "function greet(name: string): string {\n  return `Hello ${name}`;\n}\n"
    entities = ext.extract(code, "test.ts")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "greet"]
    assert len(funcs) == 1
    assert funcs[0].line_start == 1


def test_extract_async_function(ext):
    code = "async function fetchData(url: string): Promise<Response> {\n  return await fetch(url);\n}\n"
    entities = ext.extract(code, "test.ts")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "fetchData"]
    assert len(funcs) == 1


def test_extract_exported_function(ext):
    code = "export function processItems(items: Item[]): void {\n  items.forEach(i => handle(i));\n}\n"
    entities = ext.extract(code, "test.ts")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "processItems"]
    assert len(funcs) == 1


# ── 4. Arrow function extraction ────────────────────────────────────────

def test_extract_arrow_function(ext):
    code = "const add = (a: number, b: number): number => {\n  return a + b;\n};\n"
    entities = ext.extract(code, "test.ts")
    arrows = [e for e in entities if e.entity_type == "function" and e.name == "add"]
    assert len(arrows) == 1


def test_extract_exported_arrow_function(ext):
    code = "export const multiply = (x: number, y: number) => x * y;\n"
    entities = ext.extract(code, "test.ts")
    arrows = [e for e in entities if e.entity_type == "function" and e.name == "multiply"]
    assert len(arrows) == 1


# ── 5. Class extraction with extends/implements ────────────────────────

def test_extract_class_with_extends(ext):
    code = "class Dog extends Animal {\n  bark(): void {\n    console.log('woof');\n  }\n}\n"
    entities = ext.extract(code, "test.ts")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "Dog"]
    assert len(classes) == 1
    assert "Animal" in classes[0].inherits


def test_extract_class_with_implements(ext):
    code = "export class UserService extends BaseService implements Disposable {\n  dispose(): void {}\n}\n"
    entities = ext.extract(code, "test.ts")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "UserService"]
    assert len(classes) == 1
    assert "BaseService" in classes[0].inherits


# ── 6. Interface extraction with extends ─────────────────────────────────

def test_extract_interface(ext):
    code = "interface Shape {\n  area(): number;\n}\n"
    entities = ext.extract(code, "test.ts")
    ifaces = [e for e in entities if e.entity_type == "class" and e.name == "Shape"]
    assert len(ifaces) == 1


def test_extract_interface_with_extends(ext):
    code = "export interface Circle extends Shape {\n  radius: number;\n}\n"
    entities = ext.extract(code, "test.ts")
    ifaces = [e for e in entities if e.entity_type == "class" and e.name == "Circle"]
    assert len(ifaces) == 1
    assert "Shape" in ifaces[0].inherits


# ── 7. Enum extraction ──────────────────────────────────────────────────

def test_extract_enum(ext):
    code = "enum Direction {\n  Up,\n  Down,\n  Left,\n  Right,\n}\n"
    entities = ext.extract(code, "test.ts")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Direction"]
    assert len(enums) == 1


def test_extract_const_enum(ext):
    code = "export const enum Color {\n  Red = 'RED',\n  Blue = 'BLUE',\n}\n"
    entities = ext.extract(code, "test.ts")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Color"]
    assert len(enums) == 1


# ── 8. Type alias extraction ────────────────────────────────────────────

def test_extract_type_alias(ext):
    code = "type StringOrNumber = string | number;\n"
    entities = ext.extract(code, "test.ts")
    aliases = [e for e in entities if e.entity_type == "variable" and e.name == "StringOrNumber"]
    assert len(aliases) == 1


def test_extract_generic_type_alias(ext):
    code = "export type Result<T> = { ok: true; value: T } | { ok: false; error: Error };\n"
    entities = ext.extract(code, "test.ts")
    aliases = [e for e in entities if e.entity_type == "variable" and e.name == "Result"]
    assert len(aliases) == 1


# ── 9. Class method extraction (scoped as ClassName.methodName) ──────────

def test_extract_class_methods_scoped(ext):
    code = (
        "class Calculator {\n"
        "  add(a: number, b: number): number {\n"
        "    return a + b;\n"
        "  }\n"
        "  subtract(a: number, b: number): number {\n"
        "    return a - b;\n"
        "  }\n"
        "}\n"
    )
    entities = ext.extract(code, "test.ts")
    method_names = [e.name for e in entities if e.entity_type == "function"]
    assert "Calculator.add" in method_names
    assert "Calculator.subtract" in method_names


# ── 10. Named import extraction ─────────────────────────────────────────

def test_extract_named_imports(ext):
    code = "import { useState, useEffect } from 'react';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import"]
    import_names = {e.name for e in imports}
    assert "useState" in import_names
    assert "useEffect" in import_names
    for imp in imports:
        assert imp.imports[0][0] == "react"


def test_extract_aliased_named_import(ext):
    code = "import { Component as Comp } from 'react';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "Comp"
    assert imports[0].imports[0] == ("react", "Comp")


# ── 11. Default import extraction ───────────────────────────────────────

def test_extract_default_import(ext):
    code = "import React from 'react';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "React"
    assert imports[0].imports[0] == ("react", "React")


# ── 12. Star import extraction ──────────────────────────────────────────

def test_extract_star_import(ext):
    code = "import * as path from 'path';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "path"
    assert imports[0].imports[0] == ("path", "path")


# ── 13. JSX component extraction ────────────────────────────────────────

def test_extract_jsx_components(ext):
    code = (
        "function App(): JSX.Element {\n"
        "  return (\n"
        "    <div>\n"
        "      <Header title='hello' />\n"
        "      <Sidebar items={items} />\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )
    entities = ext.extract(code, "test.tsx")
    app_func = [e for e in entities if e.name == "App" and e.entity_type == "function"]
    assert len(app_func) == 1
    calls = app_func[0].calls
    assert "Header" in calls
    assert "Sidebar" in calls


# ── 14. Decorator extraction ────────────────────────────────────────────

def test_extract_decorators(ext):
    code = (
        "@Injectable\n"
        "@Singleton\n"
        "class AuthService {\n"
        "  authenticate(): boolean {\n"
        "    return true;\n"
        "  }\n"
        "}\n"
    )
    entities = ext.extract(code, "test.ts")
    cls = [e for e in entities if e.name == "AuthService" and e.entity_type == "class"]
    assert len(cls) == 1
    assert "Injectable" in cls[0].decorators
    assert "Singleton" in cls[0].decorators


# ── 15. Type reference extraction ───────────────────────────────────────

def test_extract_type_refs(ext):
    code = (
        "function processUser(user: UserModel, config: AppConfig): ServiceResult {\n"
        "  return handle(user, config);\n"
        "}\n"
    )
    entities = ext.extract(code, "test.ts")
    func = [e for e in entities if e.name == "processUser" and e.entity_type == "function"]
    assert len(func) == 1
    type_refs = func[0].type_refs
    assert "UserModel" in type_refs
    assert "AppConfig" in type_refs
    assert "ServiceResult" in type_refs


def test_type_refs_exclude_builtins(ext):
    """Built-in type names like Promise, Array, etc. should not appear in type_refs."""
    code = "function getData(): Promise<string> {\n  return fetch('/api');\n}\n"
    entities = ext.extract(code, "test.ts")
    func = [e for e in entities if e.name == "getData" and e.entity_type == "function"]
    assert len(func) == 1
    # Promise and string are builtins, should be filtered
    for ref in func[0].type_refs:
        assert ref not in ("Promise", "Array", "String", "Number", "Boolean")


# ── 16. Empty / whitespace input ────────────────────────────────────────

def test_empty_input_returns_empty(ext):
    assert ext.extract("", "test.ts") == []


def test_whitespace_only_returns_empty(ext):
    assert ext.extract("   \n\n  \t  \n", "test.ts") == []


# ── 17. Comment stripping ───────────────────────────────────────────────

def test_comments_do_not_produce_entities(ext):
    code = (
        "// function fakeFunc() {}\n"
        "/* class FakeClass {} */\n"
        "const real = (x: number) => x;\n"
    )
    entities = ext.extract(code, "test.ts")
    names = [e.name for e in entities if e.entity_type != "import"]
    assert "fakeFunc" not in names
    assert "FakeClass" not in names
    assert "real" in names


def test_string_contents_do_not_produce_entities(ext):
    code = (
        'const msg = "function hidden() { return 1; }";\n'
        "function visible(): void {}\n"
    )
    entities = ext.extract(code, "test.ts")
    names = [e.name for e in entities if e.entity_type == "function"]
    assert "hidden" not in names
    assert "visible" in names
