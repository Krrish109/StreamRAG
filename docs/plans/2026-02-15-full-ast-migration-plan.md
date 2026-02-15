# Full AST Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all 5 regex-based language extractors (TypeScript, JavaScript, C++, C, Java) with tree-sitter AST extractors, achieving parity with the existing Python/React/Rust AST extractors.

**Architecture:** Each language gets a self-contained `*_ast.py` file following the proven pattern from `react_ast.py` and `rust_ast.py`. The registry gains factory functions that prefer AST extractors and fall back to regex. Old regex extractors remain untouched as fallbacks.

**Tech Stack:** tree-sitter, tree-sitter-typescript, tree-sitter-javascript, tree-sitter-c, tree-sitter-cpp, tree-sitter-java

---

### Task 1: Install Missing Tree-Sitter Grammars

**Files:**
- Modify: `pyproject.toml` (optional deps section)

**Step 1: Install grammars**

```bash
cd /Users/krrish/StreamRAG
pip install tree-sitter-c tree-sitter-cpp tree-sitter-java
```

**Step 2: Verify all grammars are available**

```bash
python -c "
import tree_sitter
import tree_sitter_typescript
import tree_sitter_javascript
import tree_sitter_c
import tree_sitter_cpp
import tree_sitter_java
print('All grammars available')
"
```

Expected: `All grammars available`

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: install tree-sitter-c, tree-sitter-cpp, tree-sitter-java grammars"
```

---

### Task 2: TypeScript AST Extractor

**Files:**
- Create: `streamrag/languages/typescript_ast.py`
- Test: `tests/test_typescript_ast_extractor.py`

**What it extracts:**

The TypeScript grammar (`tree_sitter_typescript.language_typescript()`) exposes these node types:
- `function_declaration`, `generator_function_declaration` → entity_type="function"
- `lexical_declaration` / `variable_declaration` containing `arrow_function` or `function_expression` → entity_type="function"
- `class_declaration`, `abstract_class_declaration` → entity_type="class"
- `interface_declaration` → entity_type="class"
- `enum_declaration` → entity_type="class"
- `type_alias_declaration` → entity_type="variable"
- `method_definition` (inside class_body) → entity_type="function" (scoped under class)
- `import_statement` → entity_type="import"
- `export_statement` → recurse into children

**Implementation approach:**

Follow `react_ast.py` almost exactly — TypeScript uses the same grammar package (`tree_sitter_typescript`) but with the `language_typescript()` function instead of `language_tsx()`. The node types are identical.

Key differences from React AST extractor:
- No JSX-specific node handling (no `jsx_element`, `jsx_self_closing_element`)
- No React post-processing (`_detect_custom_hooks`, `_classify_components`, `_link_props`)
- No React wrapper detection (`memo`, `forwardRef`, `lazy`, `createContext`)
- Uses only `TS_BUILTINS`, `TS_COMMON_METHODS`, `TS_TYPE_BUILTINS` (no React sets)
- `supported_extensions` = `[".ts"]`
- `language_id` = `"typescript"`

**Step 1: Write the test file**

Create `tests/test_typescript_ast_extractor.py` with tests mirroring `tests/test_typescript_extractor.py`:

```python
"""Tests for TypeScript tree-sitter AST extractor."""

import pytest

try:
    from streamrag.languages.typescript_ast import TypeScriptASTExtractor, _is_available
    ts_available = _is_available()
except ImportError:
    ts_available = False

pytestmark = pytest.mark.skipif(not ts_available, reason="tree-sitter-typescript not installed")


@pytest.fixture
def ext():
    return TypeScriptASTExtractor()


def test_language_id(ext):
    assert ext.language_id == "typescript"


def test_can_handle(ext):
    assert ext.can_handle("app.ts") is True
    assert ext.can_handle("src/utils.ts") is True
    assert ext.can_handle("app.tsx") is False
    assert ext.can_handle("app.js") is False


def test_empty_source(ext):
    assert ext.extract("", "test.ts") == []
    assert ext.extract("   \n  ", "test.ts") == []


# ── Functions ────────────────────────────────────────────────────────────

def test_function_declaration(ext):
    code = "function greet(name: string): string {\n  return `Hello ${name}`;\n}\n"
    entities = ext.extract(code, "test.ts")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "greet"]
    assert len(funcs) == 1
    assert funcs[0].line_start == 1
    assert funcs[0].line_end == 3


def test_async_function(ext):
    code = "async function fetchData(url: string): Promise<Response> {\n  return await fetch(url);\n}\n"
    entities = ext.extract(code, "test.ts")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "fetchData"]
    assert len(funcs) == 1


def test_exported_function(ext):
    code = "export function processItems(items: Item[]): void {\n  items.forEach(i => handle(i));\n}\n"
    entities = ext.extract(code, "test.ts")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "processItems"]
    assert len(funcs) == 1


def test_arrow_function(ext):
    code = "const add = (a: number, b: number): number => {\n  return a + b;\n};\n"
    entities = ext.extract(code, "test.ts")
    arrows = [e for e in entities if e.entity_type == "function" and e.name == "add"]
    assert len(arrows) == 1


def test_exported_arrow_function(ext):
    code = "export const multiply = (x: number, y: number) => x * y;\n"
    entities = ext.extract(code, "test.ts")
    arrows = [e for e in entities if e.entity_type == "function" and e.name == "multiply"]
    assert len(arrows) == 1


# ── Classes ──────────────────────────────────────────────────────────────

def test_class_with_extends(ext):
    code = "class Dog extends Animal {\n  bark(): void {\n    console.log('woof');\n  }\n}\n"
    entities = ext.extract(code, "test.ts")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "Dog"]
    assert len(cls) == 1
    assert cls[0].inherits == ["Animal"]


def test_class_method_scoped(ext):
    code = "class Dog extends Animal {\n  bark(): void {\n    console.log('woof');\n  }\n}\n"
    entities = ext.extract(code, "test.ts")
    methods = [e for e in entities if e.entity_type == "function" and e.name == "Dog.bark"]
    assert len(methods) == 1


def test_interface(ext):
    code = "interface User {\n  name: string;\n  age: number;\n}\n"
    entities = ext.extract(code, "test.ts")
    ifaces = [e for e in entities if e.entity_type == "class" and e.name == "User"]
    assert len(ifaces) == 1


def test_interface_extends(ext):
    code = "interface Admin extends User {\n  role: string;\n}\n"
    entities = ext.extract(code, "test.ts")
    ifaces = [e for e in entities if e.entity_type == "class" and e.name == "Admin"]
    assert len(ifaces) == 1
    assert "User" in ifaces[0].inherits


def test_enum(ext):
    code = "enum Color {\n  Red,\n  Green,\n  Blue,\n}\n"
    entities = ext.extract(code, "test.ts")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Color"]
    assert len(enums) == 1


def test_type_alias(ext):
    code = "type UserId = string;\n"
    entities = ext.extract(code, "test.ts")
    types = [e for e in entities if e.entity_type == "variable" and e.name == "UserId"]
    assert len(types) == 1


# ── Imports ──────────────────────────────────────────────────────────────

def test_named_import(ext):
    code = "import { useState, useEffect } from 'react';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import"]
    names = {e.name for e in imports}
    assert "useState" in names
    assert "useEffect" in names


def test_default_import(ext):
    code = "import React from 'react';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "React"]
    assert len(imports) == 1
    assert imports[0].imports == [("react", "React")]


def test_namespace_import(ext):
    code = "import * as path from 'path';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "path"]
    assert len(imports) == 1


def test_aliased_import(ext):
    code = "import { Component as Comp } from 'react';\n"
    entities = ext.extract(code, "test.ts")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "Comp"]
    assert len(imports) == 1
    assert imports[0].imports == [("react", "Component")]


# ── Calls ────────────────────────────────────────────────────────────────

def test_call_extraction(ext):
    code = "function init() {\n  validateConfig();\n  setupRoutes();\n}\n"
    entities = ext.extract(code, "test.ts")
    fn = [e for e in entities if e.name == "init"][0]
    assert "validateConfig" in fn.calls
    assert "setupRoutes" in fn.calls


def test_builtin_calls_filtered(ext):
    code = "function test() {\n  console.log('hi');\n  parseInt('42');\n}\n"
    entities = ext.extract(code, "test.ts")
    fn = [e for e in entities if e.name == "test"][0]
    assert "console" not in fn.calls
    assert "parseInt" not in fn.calls


# ── Type references ──────────────────────────────────────────────────────

def test_type_refs(ext):
    code = "function process(user: UserModel): ResultData {\n  return transform(user);\n}\n"
    entities = ext.extract(code, "test.ts")
    fn = [e for e in entities if e.name == "process"][0]
    assert "UserModel" in fn.type_refs
    assert "ResultData" in fn.type_refs


# ── Hashes ───────────────────────────────────────────────────────────────

def test_signature_hash_changes_on_body_edit(ext):
    code1 = "function foo() {\n  return 1;\n}\n"
    code2 = "function foo() {\n  return 2;\n}\n"
    e1 = [e for e in ext.extract(code1, "t.ts") if e.name == "foo"][0]
    e2 = [e for e in ext.extract(code2, "t.ts") if e.name == "foo"][0]
    assert e1.signature_hash != e2.signature_hash


def test_structure_hash_stable_on_rename(ext):
    code1 = "function foo() {\n  return 1;\n}\n"
    code2 = "function bar() {\n  return 1;\n}\n"
    e1 = [e for e in ext.extract(code1, "t.ts") if e.name == "foo"][0]
    e2 = [e for e in ext.extract(code2, "t.ts") if e.name == "bar"][0]
    assert e1.structure_hash == e2.structure_hash


# ── Parameters ───────────────────────────────────────────────────────────

def test_params_extraction(ext):
    code = "function greet(name: string, age: number): string {\n  return '';\n}\n"
    entities = ext.extract(code, "test.ts")
    fn = [e for e in entities if e.name == "greet"][0]
    assert fn.params == ["name", "age"]
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/test_typescript_ast_extractor.py -x -q
```

Expected: ERRORS (module not found)

**Step 3: Implement TypeScriptASTExtractor**

Create `streamrag/languages/typescript_ast.py`. Start from a copy of `react_ast.py` and strip React-specific logic:

- Use `tree_sitter_typescript.language_typescript()` instead of `language_tsx()`
- Remove JSX handling (`jsx_element`, `jsx_self_closing_element`, `_jsx_tag_name`)
- Remove React wrappers (`_FUNCTION_WRAPPERS`, `_VARIABLE_WRAPPERS`)
- Remove React post-processing (`_detect_custom_hooks`, `_classify_components`, `_link_props`)
- Use only `TS_BUILTINS`, `TS_COMMON_METHODS`, `TS_TYPE_BUILTINS`
- For variable declarations with `call_expression`: only extract if the call wraps an arrow function or function expression (generic wrapper detection, no React-specific names)
- `language_id` = `"typescript"`, `supported_extensions` = `[".ts"]`

**Step 4: Run tests to verify they pass**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/test_typescript_ast_extractor.py -x -q
```

Expected: All PASS

**Step 5: Run full test suite**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/ -x -q
```

Expected: All 715+ tests pass

**Step 6: Commit**

```bash
git add streamrag/languages/typescript_ast.py tests/test_typescript_ast_extractor.py
git commit -m "feat: add tree-sitter AST extractor for TypeScript"
```

---

### Task 3: JavaScript AST Extractor

**Files:**
- Create: `streamrag/languages/javascript_ast.py`
- Test: `tests/test_javascript_ast_extractor.py`

**What it extracts:**

Uses `tree_sitter_javascript.language()`. Node types:
- `function_declaration`, `generator_function_declaration` → entity_type="function"
- `lexical_declaration` / `variable_declaration` with `arrow_function` → entity_type="function"
- `class_declaration` → entity_type="class"
- `import_statement` → entity_type="import"
- `call_expression` where callee is `require` → entity_type="import"
- `export_statement` → recurse
- `method_definition` → entity_type="function" (scoped)

Key differences from TypeScript AST:
- No interfaces, enums, or type aliases (JS has none)
- No type annotations → `_extract_type_refs` returns empty
- Handle CommonJS `require()` imports (same logic as React AST's `_collect_require_imports`)
- Uses `TS_BUILTINS`, `TS_COMMON_METHODS` (same builtins, no type builtins)

**Step 1: Write test file**

Create `tests/test_javascript_ast_extractor.py`:

```python
"""Tests for JavaScript tree-sitter AST extractor."""

import pytest

try:
    from streamrag.languages.javascript_ast import JavaScriptASTExtractor, _is_available
    js_available = _is_available()
except ImportError:
    js_available = False

pytestmark = pytest.mark.skipif(not js_available, reason="tree-sitter-javascript not installed")


@pytest.fixture
def ext():
    return JavaScriptASTExtractor()


def test_language_id(ext):
    assert ext.language_id == "javascript"


def test_can_handle(ext):
    assert ext.can_handle("app.js") is True
    assert ext.can_handle("lib.mjs") is True
    assert ext.can_handle("util.cjs") is True
    assert ext.can_handle("app.ts") is False


def test_empty_source(ext):
    assert ext.extract("", "test.js") == []


def test_function_declaration(ext):
    code = "function greet(name) {\n  return 'Hello ' + name;\n}\n"
    entities = ext.extract(code, "test.js")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "greet"]
    assert len(funcs) == 1


def test_arrow_function(ext):
    code = "const add = (a, b) => a + b;\n"
    entities = ext.extract(code, "test.js")
    arrows = [e for e in entities if e.entity_type == "function" and e.name == "add"]
    assert len(arrows) == 1


def test_class_declaration(ext):
    code = "class Animal {\n  constructor(name) {\n    this.name = name;\n  }\n  speak() {\n    return this.name;\n  }\n}\n"
    entities = ext.extract(code, "test.js")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "Animal"]
    assert len(cls) == 1
    methods = [e for e in entities if e.name == "Animal.speak"]
    assert len(methods) == 1


def test_class_extends(ext):
    code = "class Dog extends Animal {\n  bark() { return 'woof'; }\n}\n"
    entities = ext.extract(code, "test.js")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "Dog"]
    assert len(cls) == 1
    assert cls[0].inherits == ["Animal"]


def test_es_import(ext):
    code = "import { readFile } from 'fs';\n"
    entities = ext.extract(code, "test.js")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "readFile"]
    assert len(imports) == 1
    assert imports[0].imports == [("fs", "readFile")]


def test_default_import(ext):
    code = "import express from 'express';\n"
    entities = ext.extract(code, "test.js")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "express"]
    assert len(imports) == 1


def test_require_import(ext):
    code = "const express = require('express');\n"
    entities = ext.extract(code, "test.js")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "express"]
    assert len(imports) == 1
    assert imports[0].imports == [("express", "express")]


def test_destructured_require(ext):
    code = "const { readFile, writeFile } = require('fs');\n"
    entities = ext.extract(code, "test.js")
    names = {e.name for e in entities if e.entity_type == "import"}
    assert "readFile" in names
    assert "writeFile" in names


def test_call_extraction(ext):
    code = "function setup() {\n  initDB();\n  loadConfig();\n}\n"
    entities = ext.extract(code, "test.js")
    fn = [e for e in entities if e.name == "setup"][0]
    assert "initDB" in fn.calls
    assert "loadConfig" in fn.calls


def test_no_type_refs(ext):
    """JavaScript has no type annotations."""
    code = "function foo(x) { return x; }\n"
    entities = ext.extract(code, "test.js")
    fn = [e for e in entities if e.name == "foo"][0]
    assert fn.type_refs == []


def test_no_interfaces_or_enums(ext):
    """JavaScript has no interfaces or enums."""
    code = "class Foo {}\nfunction bar() {}\n"
    entities = ext.extract(code, "test.js")
    types = [e.entity_type for e in entities]
    # No interfaces or enums extracted
    assert all(t in ("function", "class", "import", "variable", "module_code") for t in types)
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/test_javascript_ast_extractor.py -x -q
```

**Step 3: Implement JavaScriptASTExtractor**

Create `streamrag/languages/javascript_ast.py`:

- Use `tree_sitter_javascript.language()`
- Handle the same declaration types as TypeScript minus interfaces, enums, type aliases
- Handle `require()` imports (same pattern as `react_ast.py`)
- No type ref extraction
- `language_id` = `"javascript"`, `supported_extensions` = `[".js", ".mjs", ".cjs"]`

**Step 4: Run tests and full suite**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/test_javascript_ast_extractor.py -x -q
cd /Users/krrish/StreamRAG && python -m pytest tests/ -x -q
```

**Step 5: Commit**

```bash
git add streamrag/languages/javascript_ast.py tests/test_javascript_ast_extractor.py
git commit -m "feat: add tree-sitter AST extractor for JavaScript"
```

---

### Task 4: C AST Extractor

**Files:**
- Create: `streamrag/languages/c_ast.py`
- Test: `tests/test_c_ast_extractor.py`

**What it extracts:**

Uses `tree_sitter_c.language()`. Node types:
- `function_definition` → entity_type="function"
- `struct_specifier` (with body) → entity_type="class"
- `enum_specifier` (with body) → entity_type="class"
- `union_specifier` (with body) → entity_type="class"
- `type_definition` → entity_type="variable"
- `preproc_include` → entity_type="import"
- `preproc_def` (macros) → entity_type="variable"
- `preproc_function_def` (function-like macros) → entity_type="function"

Key C-specific details:
- No classes, methods, or inheritance — C is simpler
- `#include "file.h"` → import with module=".", name=path
- `#include <stdlib.h>` → import with module="", name=path
- Function names found via `declarator` → `function_declarator` → `identifier`
- Struct/enum/union names found via `type_identifier` child
- Call extraction: walk `call_expression` nodes in function bodies
- No type annotations (no type_refs)
- No decorators
- Uses `C_BUILTINS`, `C_COMMON_METHODS` from builtins.py

**Step 1: Write test file**

Create `tests/test_c_ast_extractor.py`:

```python
"""Tests for C tree-sitter AST extractor."""

import pytest

try:
    from streamrag.languages.c_ast import CASTExtractor, _is_available
    c_available = _is_available()
except ImportError:
    c_available = False

pytestmark = pytest.mark.skipif(not c_available, reason="tree-sitter-c not installed")


@pytest.fixture
def ext():
    return CASTExtractor()


def test_language_id(ext):
    assert ext.language_id == "c"


def test_can_handle(ext):
    assert ext.can_handle("main.c") is True
    assert ext.can_handle("main.h") is False
    assert ext.can_handle("main.cpp") is False


def test_empty_source(ext):
    assert ext.extract("", "test.c") == []


def test_function_definition(ext):
    code = "int add(int a, int b) {\n    return a + b;\n}\n"
    entities = ext.extract(code, "test.c")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "add"]
    assert len(funcs) == 1
    assert funcs[0].line_start == 1
    assert funcs[0].line_end == 3


def test_static_function(ext):
    code = "static void helper(void) {\n    // ...\n}\n"
    entities = ext.extract(code, "test.c")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "helper"]
    assert len(funcs) == 1


def test_struct(ext):
    code = "struct Point {\n    int x;\n    int y;\n};\n"
    entities = ext.extract(code, "test.c")
    structs = [e for e in entities if e.entity_type == "class" and e.name == "Point"]
    assert len(structs) == 1


def test_typedef_struct(ext):
    code = "typedef struct {\n    int x;\n    int y;\n} Point;\n"
    entities = ext.extract(code, "test.c")
    # Should extract the typedef name
    types = [e for e in entities if e.name == "Point"]
    assert len(types) >= 1


def test_enum(ext):
    code = "enum Color {\n    RED,\n    GREEN,\n    BLUE\n};\n"
    entities = ext.extract(code, "test.c")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Color"]
    assert len(enums) == 1


def test_union(ext):
    code = "union Data {\n    int i;\n    float f;\n    char c;\n};\n"
    entities = ext.extract(code, "test.c")
    unions = [e for e in entities if e.entity_type == "class" and e.name == "Data"]
    assert len(unions) == 1


def test_include_local(ext):
    code = '#include "myheader.h"\n'
    entities = ext.extract(code, "test.c")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].imports == [(".", "myheader.h")]


def test_include_system(ext):
    code = "#include <stdio.h>\n"
    entities = ext.extract(code, "test.c")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].imports == [("", "stdio.h")]


def test_define_macro(ext):
    code = "#define MAX_SIZE 100\n"
    entities = ext.extract(code, "test.c")
    macros = [e for e in entities if e.name == "MAX_SIZE"]
    assert len(macros) == 1


def test_function_macro(ext):
    code = "#define SQUARE(x) ((x) * (x))\n"
    entities = ext.extract(code, "test.c")
    macros = [e for e in entities if e.name == "SQUARE"]
    assert len(macros) == 1


def test_call_extraction(ext):
    code = "void init() {\n    setup_db();\n    load_config();\n}\n"
    entities = ext.extract(code, "test.c")
    fn = [e for e in entities if e.name == "init"][0]
    assert "setup_db" in fn.calls
    assert "load_config" in fn.calls


def test_builtin_calls_filtered(ext):
    code = "void test() {\n    printf(\"hi\");\n    malloc(100);\n}\n"
    entities = ext.extract(code, "test.c")
    fn = [e for e in entities if e.name == "test"][0]
    assert "printf" not in fn.calls
    assert "malloc" not in fn.calls


def test_params(ext):
    code = "int add(int a, int b) {\n    return a + b;\n}\n"
    entities = ext.extract(code, "test.c")
    fn = [e for e in entities if e.name == "add"][0]
    assert fn.params == ["a", "b"]
```

**Step 2: Run tests to fail, Step 3: Implement, Step 4: Pass, Step 5: Full suite, Step 6: Commit**

Same workflow as above. Implementation creates `streamrag/languages/c_ast.py`.

```bash
git add streamrag/languages/c_ast.py tests/test_c_ast_extractor.py
git commit -m "feat: add tree-sitter AST extractor for C"
```

---

### Task 5: C++ AST Extractor

**Files:**
- Create: `streamrag/languages/cpp_ast.py`
- Test: `tests/test_cpp_ast_extractor.py`

**What it extracts:**

Uses `tree_sitter_cpp.language()`. Node types:
- `function_definition` → entity_type="function"
- `template_declaration` containing function_definition → entity_type="function"
- `class_specifier` → entity_type="class"
- `struct_specifier` → entity_type="class"
- `enum_specifier` → entity_type="class"
- `namespace_definition` → entity_type="class" (with nested walk)
- `template_declaration` containing class/struct → entity_type="class"
- `preproc_include` → entity_type="import"
- `using_declaration` → entity_type="import"
- `alias_declaration` (`using X = Y`) → entity_type="variable"
- `type_definition` → entity_type="variable"

Key C++-specific details:
- Classes/structs have methods — walk `field_declaration_list` for `function_definition` nodes
- Inheritance: parse `base_class_clause` children
- Constructors/destructors: detected by matching class name
- Namespace scoping: recurse into namespace body with scope
- Templates: unwrap template_declaration to find the inner declaration
- `#include "file.h"` / `#include <file>` → imports
- `using namespace X;` → import
- Uses `CPP_BUILTINS`, `CPP_COMMON_METHODS`

**Step 1: Write test file**

Create `tests/test_cpp_ast_extractor.py`:

```python
"""Tests for C++ tree-sitter AST extractor."""

import pytest

try:
    from streamrag.languages.cpp_ast import CppASTExtractor, _is_available
    cpp_available = _is_available()
except ImportError:
    cpp_available = False

pytestmark = pytest.mark.skipif(not cpp_available, reason="tree-sitter-cpp not installed")


@pytest.fixture
def ext():
    return CppASTExtractor()


def test_language_id(ext):
    assert ext.language_id == "cpp"


def test_can_handle(ext):
    assert ext.can_handle("main.cpp") is True
    assert ext.can_handle("header.hpp") is True
    assert ext.can_handle("code.cc") is True
    assert ext.can_handle("header.h") is True
    assert ext.can_handle("main.c") is False
    assert ext.can_handle("main.java") is False


def test_empty_source(ext):
    assert ext.extract("", "test.cpp") == []


def test_function_definition(ext):
    code = "int add(int a, int b) {\n    return a + b;\n}\n"
    entities = ext.extract(code, "test.cpp")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "add"]
    assert len(funcs) == 1


def test_class_with_methods(ext):
    code = (
        "class Dog {\n"
        "public:\n"
        "    void bark() {\n"
        "        // ...\n"
        "    }\n"
        "};\n"
    )
    entities = ext.extract(code, "test.cpp")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "Dog"]
    assert len(cls) == 1
    methods = [e for e in entities if e.entity_type == "function" and "Dog.bark" in e.name]
    assert len(methods) == 1


def test_class_inheritance(ext):
    code = "class Dog : public Animal {\n};\n"
    entities = ext.extract(code, "test.cpp")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "Dog"]
    assert len(cls) == 1
    assert "Animal" in cls[0].inherits


def test_struct(ext):
    code = "struct Point {\n    int x;\n    int y;\n};\n"
    entities = ext.extract(code, "test.cpp")
    structs = [e for e in entities if e.entity_type == "class" and e.name == "Point"]
    assert len(structs) == 1


def test_enum_class(ext):
    code = "enum class Color {\n    Red,\n    Green,\n    Blue\n};\n"
    entities = ext.extract(code, "test.cpp")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Color"]
    assert len(enums) == 1


def test_namespace(ext):
    code = "namespace mylib {\n    void helper() {\n    }\n}\n"
    entities = ext.extract(code, "test.cpp")
    # Function inside namespace should be scoped
    funcs = [e for e in entities if e.entity_type == "function" and "helper" in e.name]
    assert len(funcs) == 1


def test_include_local(ext):
    code = '#include "myheader.h"\n'
    entities = ext.extract(code, "test.cpp")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].imports == [(".", "myheader.h")]


def test_include_system(ext):
    code = "#include <iostream>\n"
    entities = ext.extract(code, "test.cpp")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].imports == [("", "iostream")]


def test_using_namespace(ext):
    code = "using namespace std;\n"
    entities = ext.extract(code, "test.cpp")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1


def test_call_extraction(ext):
    code = "void init() {\n    setup_db();\n    load_config();\n}\n"
    entities = ext.extract(code, "test.cpp")
    fn = [e for e in entities if e.name == "init"][0]
    assert "setup_db" in fn.calls
    assert "load_config" in fn.calls


def test_builtin_calls_filtered(ext):
    code = "void test() {\n    printf(\"hi\");\n}\n"
    entities = ext.extract(code, "test.cpp")
    fn = [e for e in entities if e.name == "test"][0]
    assert "printf" not in fn.calls


def test_template_function(ext):
    code = "template<typename T>\nT identity(T x) {\n    return x;\n}\n"
    entities = ext.extract(code, "test.cpp")
    funcs = [e for e in entities if e.entity_type == "function" and e.name == "identity"]
    assert len(funcs) == 1
```

**Steps 2-6: Same TDD workflow, then commit**

```bash
git add streamrag/languages/cpp_ast.py tests/test_cpp_ast_extractor.py
git commit -m "feat: add tree-sitter AST extractor for C++"
```

---

### Task 6: Java AST Extractor

**Files:**
- Create: `streamrag/languages/java_ast.py`
- Test: `tests/test_java_ast_extractor.py`

**What it extracts:**

Uses `tree_sitter_java.language()`. Node types:
- `method_declaration` → entity_type="function"
- `constructor_declaration` → entity_type="function"
- `class_declaration` → entity_type="class"
- `interface_declaration` → entity_type="class"
- `enum_declaration` → entity_type="class"
- `record_declaration` → entity_type="class"
- `annotation_type_declaration` → entity_type="class"
- `import_declaration` → entity_type="import"
- `marker_annotation` / `annotation` → decorators on the next declaration

Key Java-specific details:
- Methods are always inside classes — scope them as `ClassName.methodName`
- Inheritance: parse `superclass` child for `extends`, `super_interfaces` for `implements`
- Annotations: `@Entity`, `@Service` — collect from `marker_annotation` / `annotation` nodes preceding declarations
- Filter out standard annotations: `@Override`, `@Deprecated`, `@SuppressWarnings`, `@FunctionalInterface`, `@SafeVarargs`
- Import format: `import com.example.Foo;` → module="com.example", name="Foo"
- Static imports: `import static org.junit.Assert.assertEquals;`
- Uses `JAVA_BUILTINS`, `JAVA_COMMON_METHODS`
- Type refs: walk type nodes (`type_identifier`) in method signatures

**Step 1: Write test file**

Create `tests/test_java_ast_extractor.py`:

```python
"""Tests for Java tree-sitter AST extractor."""

import pytest

try:
    from streamrag.languages.java_ast import JavaASTExtractor, _is_available
    java_available = _is_available()
except ImportError:
    java_available = False

pytestmark = pytest.mark.skipif(not java_available, reason="tree-sitter-java not installed")


@pytest.fixture
def ext():
    return JavaASTExtractor()


def test_language_id(ext):
    assert ext.language_id == "java"


def test_can_handle(ext):
    assert ext.can_handle("Main.java") is True
    assert ext.can_handle("Main.py") is False
    assert ext.can_handle("Main.cpp") is False


def test_empty_source(ext):
    assert ext.extract("", "Test.java") == []


def test_class(ext):
    code = "public class UserService {\n}\n"
    entities = ext.extract(code, "UserService.java")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "UserService"]
    assert len(cls) == 1


def test_class_extends(ext):
    code = "public class Dog extends Animal {\n}\n"
    entities = ext.extract(code, "Dog.java")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "Dog"]
    assert len(cls) == 1
    assert "Animal" in cls[0].inherits


def test_class_implements(ext):
    code = "public class UserRepo implements Repository {\n}\n"
    entities = ext.extract(code, "UserRepo.java")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "UserRepo"]
    assert len(cls) == 1
    assert "Repository" in cls[0].inherits


def test_interface(ext):
    code = "public interface Repository {\n    void save(Object entity);\n}\n"
    entities = ext.extract(code, "Repository.java")
    iface = [e for e in entities if e.entity_type == "class" and e.name == "Repository"]
    assert len(iface) == 1


def test_interface_extends(ext):
    code = "public interface CrudRepo extends Repository {\n}\n"
    entities = ext.extract(code, "CrudRepo.java")
    iface = [e for e in entities if e.entity_type == "class" and e.name == "CrudRepo"]
    assert len(iface) == 1
    assert "Repository" in iface[0].inherits


def test_enum(ext):
    code = "public enum Color {\n    RED,\n    GREEN,\n    BLUE\n}\n"
    entities = ext.extract(code, "Color.java")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Color"]
    assert len(enums) == 1


def test_record(ext):
    code = "public record Point(int x, int y) {\n}\n"
    entities = ext.extract(code, "Point.java")
    records = [e for e in entities if e.entity_type == "class" and e.name == "Point"]
    assert len(records) == 1


def test_method(ext):
    code = (
        "public class Calculator {\n"
        "    public int add(int a, int b) {\n"
        "        return a + b;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Calculator.java")
    methods = [e for e in entities if e.entity_type == "function" and e.name == "Calculator.add"]
    assert len(methods) == 1


def test_constructor(ext):
    code = (
        "public class User {\n"
        "    public User(String name) {\n"
        "        this.name = name;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "User.java")
    ctors = [e for e in entities if e.entity_type == "function" and e.name == "User.User"]
    assert len(ctors) == 1


def test_import(ext):
    code = "import com.example.service.UserService;\n"
    entities = ext.extract(code, "Main.java")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "UserService"]
    assert len(imports) == 1
    assert imports[0].imports == [("com.example.service", "UserService")]


def test_static_import(ext):
    code = "import static org.junit.Assert.assertEquals;\n"
    entities = ext.extract(code, "Test.java")
    imports = [e for e in entities if e.entity_type == "import" and e.name == "assertEquals"]
    assert len(imports) == 1


def test_wildcard_import(ext):
    code = "import java.util.*;\n"
    entities = ext.extract(code, "Main.java")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1


def test_annotation_as_decorator(ext):
    code = (
        "import org.springframework.stereotype.Service;\n"
        "\n"
        "@Service\n"
        "public class UserService {\n"
        "}\n"
    )
    entities = ext.extract(code, "UserService.java")
    cls = [e for e in entities if e.entity_type == "class" and e.name == "UserService"]
    assert len(cls) == 1
    assert "Service" in cls[0].decorators


def test_standard_annotations_filtered(ext):
    code = (
        "public class Foo {\n"
        "    @Override\n"
        "    public String toString() {\n"
        "        return \"foo\";\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Foo.java")
    method = [e for e in entities if e.name == "Foo.toString"]
    assert len(method) == 1
    assert "Override" not in method[0].decorators


def test_call_extraction(ext):
    code = (
        "public class App {\n"
        "    public void init() {\n"
        "        setupDB();\n"
        "        loadConfig();\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "App.java")
    method = [e for e in entities if e.name == "App.init"][0]
    assert "setupDB" in method.calls
    assert "loadConfig" in method.calls


def test_builtin_calls_filtered(ext):
    code = (
        "public class App {\n"
        "    public void test() {\n"
        "        System.out.println(\"hi\");\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "App.java")
    method = [e for e in entities if e.name == "App.test"][0]
    assert "println" not in method.calls


def test_params(ext):
    code = (
        "public class Calc {\n"
        "    public int add(int a, int b) {\n"
        "        return a + b;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Calc.java")
    method = [e for e in entities if e.name == "Calc.add"][0]
    assert method.params == ["a", "b"]


def test_type_refs(ext):
    code = (
        "public class Service {\n"
        "    public UserDTO process(UserRequest req) {\n"
        "        return null;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Service.java")
    method = [e for e in entities if e.name == "Service.process"][0]
    assert "UserDTO" in method.type_refs
    assert "UserRequest" in method.type_refs
```

**Steps 2-6: Same TDD workflow, then commit**

```bash
git add streamrag/languages/java_ast.py tests/test_java_ast_extractor.py
git commit -m "feat: add tree-sitter AST extractor for Java"
```

---

### Task 7: Update Registry with Factory Functions

**Files:**
- Modify: `streamrag/languages/registry.py`

**Step 1: Write test**

Add to a new file `tests/test_ast_registry.py`:

```python
"""Tests for AST extractor registry integration."""

import pytest
from streamrag.languages.registry import create_default_registry


def test_registry_prefers_ast_for_typescript():
    reg = create_default_registry()
    ext = reg.get_extractor("app.ts")
    assert ext is not None
    # Should be AST extractor if tree-sitter is available
    assert ext.language_id == "typescript"
    class_name = type(ext).__name__
    assert "AST" in class_name or "TypeScript" in class_name


def test_registry_prefers_ast_for_javascript():
    reg = create_default_registry()
    ext = reg.get_extractor("app.js")
    assert ext is not None
    assert ext.language_id == "javascript"


def test_registry_prefers_ast_for_cpp():
    reg = create_default_registry()
    ext = reg.get_extractor("main.cpp")
    assert ext is not None
    assert ext.language_id == "cpp"


def test_registry_prefers_ast_for_c():
    reg = create_default_registry()
    ext = reg.get_extractor("main.c")
    assert ext is not None
    assert ext.language_id == "c"


def test_registry_prefers_ast_for_java():
    reg = create_default_registry()
    ext = reg.get_extractor("Main.java")
    assert ext is not None
    assert ext.language_id == "java"


def test_registry_all_languages():
    reg = create_default_registry()
    langs = reg.supported_languages
    for lang in ["python", "react", "typescript", "javascript", "rust", "cpp", "c", "java"]:
        assert lang in langs, f"Missing language: {lang}"
```

**Step 2: Update `registry.py`**

Add factory functions for each new language and update `create_default_registry()`:

```python
def _create_typescript_extractor() -> "LanguageExtractor":
    try:
        from streamrag.languages.typescript_ast import TypeScriptASTExtractor, _is_available
        if _is_available():
            return TypeScriptASTExtractor()
    except ImportError:
        pass
    from streamrag.languages.typescript import TypeScriptExtractor
    return TypeScriptExtractor()


def _create_javascript_extractor() -> "LanguageExtractor":
    try:
        from streamrag.languages.javascript_ast import JavaScriptASTExtractor, _is_available
        if _is_available():
            return JavaScriptASTExtractor()
    except ImportError:
        pass
    from streamrag.languages.javascript import JavaScriptExtractor
    return JavaScriptExtractor()


def _create_cpp_extractor() -> "LanguageExtractor":
    try:
        from streamrag.languages.cpp_ast import CppASTExtractor, _is_available
        if _is_available():
            return CppASTExtractor()
    except ImportError:
        pass
    from streamrag.languages.cpp import CppExtractor
    return CppExtractor()


def _create_c_extractor() -> "LanguageExtractor":
    try:
        from streamrag.languages.c_ast import CASTExtractor, _is_available
        if _is_available():
            return CASTExtractor()
    except ImportError:
        pass
    from streamrag.languages.c import CExtractor
    return CExtractor()


def _create_java_extractor() -> "LanguageExtractor":
    try:
        from streamrag.languages.java_ast import JavaASTExtractor, _is_available
        if _is_available():
            return JavaASTExtractor()
    except ImportError:
        pass
    from streamrag.languages.java import JavaExtractor
    return JavaExtractor()
```

Update `create_default_registry()`:
```python
def create_default_registry() -> ExtractorRegistry:
    from streamrag.languages.python import PythonExtractor

    registry = ExtractorRegistry()
    registry.register(PythonExtractor())
    registry.register(_create_react_extractor())
    registry.register(_create_typescript_extractor())
    registry.register(_create_javascript_extractor())
    registry.register(_create_rust_extractor())
    registry.register(_create_cpp_extractor())
    registry.register(_create_c_extractor())
    registry.register(_create_java_extractor())
    return registry
```

**Step 3: Run tests and full suite**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/test_ast_registry.py tests/ -x -q
```

**Step 4: Commit**

```bash
git add streamrag/languages/registry.py tests/test_ast_registry.py
git commit -m "feat: wire all AST extractors into registry with fallback"
```

---

### Task 8: Full Regression Test & Deploy

**Step 1: Run full test suite**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/ -x -q
```

Expected: All tests pass (715+)

**Step 2: Copy to plugin directory**

```bash
rsync -av --exclude='__pycache__' --exclude='.git' --exclude='*.egg-info' \
  /Users/krrish/StreamRAG/streamrag/ /Users/krrish/.claude/streamrag/StreamRAG/streamrag/
```

**Step 3: Update CLAUDE.md extractor hierarchy table**

Update the table in `/Users/krrish/StreamRAG/CLAUDE.md` to reflect all AST extractors:

```markdown
| Language   | AST (preferred)               | Regex (fallback)         |
|------------|-------------------------------|--------------------------|
| Python     | `ast` module (built-in)       | —                        |
| React/TSX  | `react_ast.py` (tree-sitter)  | `react.py`               |
| TypeScript | `typescript_ast.py` (tree-sitter) | `typescript.py`      |
| JavaScript | `javascript_ast.py` (tree-sitter) | `javascript.py`      |
| Rust       | `rust_ast.py` (tree-sitter)   | `rust.py`                |
| C++        | `cpp_ast.py` (tree-sitter)    | `cpp.py`                 |
| C          | `c_ast.py` (tree-sitter)      | `c.py`                   |
| Java       | `java_ast.py` (tree-sitter)   | `java.py`                |
```

**Step 4: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with full AST extractor hierarchy"
```
