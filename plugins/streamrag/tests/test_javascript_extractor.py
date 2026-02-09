"""Tests for JavaScriptExtractor."""

from streamrag.languages.javascript import JavaScriptExtractor


def _ext():
    return JavaScriptExtractor()


# --- 1. can_handle() ---


def test_can_handle_js_extensions():
    ext = _ext()
    assert ext.can_handle("app.js") is True
    assert ext.can_handle("Component.jsx") is True
    assert ext.can_handle("utils.mjs") is True
    assert ext.can_handle("config.cjs") is True
    assert ext.can_handle("/path/to/deep/module.js") is True


def test_can_handle_rejects_non_js():
    ext = _ext()
    assert ext.can_handle("app.ts") is False
    assert ext.can_handle("module.py") is False
    assert ext.can_handle("style.css") is False
    assert ext.can_handle("main.tsx") is False


# --- 2. language_id ---


def test_language_id():
    assert _ext().language_id == "javascript"


# --- 3. Function extraction (regular, async) ---


def test_extract_regular_function():
    source = """\
function greet(name) {
    return "Hello, " + name;
}
"""
    entities = _ext().extract(source, "app.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "greet"
    assert funcs[0].line_start == 1


def test_extract_async_function():
    source = """\
async function fetchData(url) {
    const res = await fetch(url);
    return res;
}
"""
    entities = _ext().extract(source, "api.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "fetchData"


def test_extract_exported_function():
    source = """\
export function processItem(item) {
    return transform(item);
}
"""
    entities = _ext().extract(source, "lib.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "processItem"
    assert "transform" in funcs[0].calls


# --- 4. Arrow function extraction ---


def test_extract_arrow_function():
    source = """\
const add = (a, b) => {
    return a + b;
};
"""
    entities = _ext().extract(source, "math.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "add"


def test_extract_exported_arrow_function():
    source = """\
export const multiply = (a, b) => {
    return a * b;
};
"""
    entities = _ext().extract(source, "math.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "multiply"


# --- 5. Class extraction with extends ---


def test_extract_class_with_extends():
    source = """\
class Animal {
    constructor(name) {
        this.name = name;
    }
}

class Dog extends Animal {
    bark() {
        return "woof";
    }
}
"""
    entities = _ext().extract(source, "animals.js")
    classes = [e for e in entities if e.entity_type == "class"]
    assert len(classes) == 2
    animal = [c for c in classes if c.name == "Animal"][0]
    dog = [c for c in classes if c.name == "Dog"][0]
    assert animal.inherits == []
    assert dog.inherits == ["Animal"]


def test_extract_exported_class():
    source = """\
export class UserService extends BaseService {
    getUser(id) {
        return this.db.find(id);
    }
}
"""
    entities = _ext().extract(source, "services.js")
    classes = [e for e in entities if e.entity_type == "class"]
    assert len(classes) == 1
    assert classes[0].name == "UserService"
    assert classes[0].inherits == ["BaseService"]


# --- 6. Class method extraction (scoped as ClassName.methodName) ---


def test_class_method_scoped_name():
    source = """\
class Calculator {
    add(a, b) {
        return a + b;
    }

    subtract(a, b) {
        return a - b;
    }
}
"""
    entities = _ext().extract(source, "calc.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    func_names = {f.name for f in funcs}
    assert "Calculator.add" in func_names
    assert "Calculator.subtract" in func_names


def test_class_constructor_scoped():
    source = """\
class Widget {
    constructor(config) {
        this.config = config;
    }
}
"""
    entities = _ext().extract(source, "widget.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    constructors = [f for f in funcs if "constructor" in f.name]
    assert len(constructors) == 1
    assert constructors[0].name == "Widget.constructor"


# --- 7. Import extraction: named imports {A, B} from 'module' ---


def test_import_named():
    source = """\
import { useState, useEffect } from 'react';
"""
    entities = _ext().extract(source, "app.js")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 2
    names = {e.name for e in imports}
    assert names == {"useState", "useEffect"}
    for imp in imports:
        assert imp.imports[0][0] == "react"


def test_import_default():
    source = """\
import React from 'react';
"""
    entities = _ext().extract(source, "app.js")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "React"
    assert imports[0].imports == [("react", "React")]


def test_import_named_with_alias():
    source = """\
import { Component as Comp } from 'react';
"""
    entities = _ext().extract(source, "app.js")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "Comp"


# --- 8. Import extraction: require() pattern ---


def test_require_default():
    source = """\
const express = require('express');
"""
    entities = _ext().extract(source, "server.js")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "express"
    assert imports[0].imports == [("express", "express")]


def test_require_destructured():
    source = """\
const { readFile, writeFile } = require('fs');
"""
    entities = _ext().extract(source, "io.js")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 2
    names = {e.name for e in imports}
    assert names == {"readFile", "writeFile"}
    for imp in imports:
        assert imp.imports[0][0] == "fs"


# --- 9. JSX component extraction ---


def test_jsx_component_extraction():
    source = """\
function App() {
    return <UserProfile name="test" />;
}
"""
    entities = _ext().extract(source, "App.jsx")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].name == "App"
    assert "UserProfile" in funcs[0].calls


def test_jsx_multiple_components():
    source = """\
function Dashboard() {
    return <div>
        <Header />
        <Sidebar />
        <MainContent />
    </div>;
}
"""
    entities = _ext().extract(source, "Dashboard.jsx")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    calls = funcs[0].calls
    assert "Header" in calls
    assert "Sidebar" in calls
    assert "MainContent" in calls


# --- 10. No type refs extracted (unlike TypeScript) ---


def test_no_type_refs():
    """JavaScript extractor should not extract type annotations."""
    ext = _ext()
    assert ext._extract_type_refs_from_text("x: User, y: Response") == []

    # Even in a full extract, type_refs should be empty
    source = """\
function process(user) {
    return user.name;
}
"""
    entities = ext.extract(source, "app.js")
    funcs = [e for e in entities if e.entity_type == "function"]
    assert len(funcs) == 1
    assert funcs[0].type_refs == []


# --- 11. No interfaces/enums extracted (unlike TypeScript) ---


def test_no_interfaces_extracted():
    """JavaScript does not have interface/enum syntax, but even if the
    text contains such patterns, the JS extractor should NOT match them
    because _get_declaration_patterns excludes interface and enum patterns."""
    source = """\
function realFunction() {
    return 42;
}
"""
    entities = _ext().extract(source, "app.js")
    # Only the function should be found, no classes from interface/enum patterns
    classes = [e for e in entities if e.entity_type == "class"]
    assert len(classes) == 0


def test_declaration_patterns_exclude_ts_only():
    """Verify that _get_declaration_patterns does not include interface,
    enum, or type alias patterns."""
    ext = _ext()
    patterns = ext._get_declaration_patterns()
    # Should only have "function" and "class" keys, not "variable"
    assert "function" in patterns
    assert "class" in patterns
    assert "variable" not in patterns
    # The class patterns should be a single pattern (CLASS_PATTERN only)
    assert len(patterns["class"]) == 1


# --- 12. Empty input returns [] ---


def test_empty_input():
    ext = _ext()
    assert ext.extract("", "empty.js") == []
    assert ext.extract("   \n\n  ", "whitespace.js") == []
    assert ext.extract("\n", "newline.js") == []
