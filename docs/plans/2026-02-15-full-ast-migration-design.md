# Full AST Migration Design

## Goal

Replace all regex-based language extractors with tree-sitter AST extractors, matching the quality of the existing Python (`ast` module), React (`react_ast.py`), and Rust (`rust_ast.py`) extractors.

## Languages to Migrate

| Language | Current | Target | Grammar Package |
|----------|---------|--------|-----------------|
| TypeScript (.ts) | regex (`typescript.py`) | tree-sitter AST (`typescript_ast.py`) | `tree_sitter_typescript` (already installed) |
| JavaScript (.js/.mjs/.cjs) | regex (`javascript.py`) | tree-sitter AST (`javascript_ast.py`) | `tree_sitter_javascript` (already installed) |
| C++ (.cpp/.cc/.cxx/.hpp/.hh/.hxx/.h) | regex (`cpp.py`) | tree-sitter AST (`cpp_ast.py`) | `tree_sitter_cpp` (to install) |
| C (.c) | regex (`c.py`) | tree-sitter AST (`c_ast.py`) | `tree_sitter_c` (to install) |
| Java (.java) | regex (`java.py`) | tree-sitter AST (`java_ast.py`) | `tree_sitter_java` (to install) |

## Architecture

### Pattern

Each new extractor follows the proven pattern from `react_ast.py` and `rust_ast.py`:

```
_is_available() → bool        # Check if grammar importable
_create_*_parser() → Parser    # Create tree-sitter parser
*ASTExtractor(LanguageExtractor):
  extract(source, file_path) → List[ASTEntity]
```

### Extractor Responsibilities

Each AST extractor walks the tree-sitter CST to produce `ASTEntity` objects with:
- `entity_type`: function, class, variable, import, module_code
- `name`: hierarchically scoped (e.g., `ClassName.methodName`)
- `line_start`/`line_end`: 1-indexed
- `signature_hash`: SHA256[:12] of full entity text (change detection)
- `structure_hash`: SHA256[:12] with name removed (rename detection)
- `calls`: function/method calls, filtered through language-specific builtins
- `inherits`: base classes/interfaces/traits
- `type_refs`: type annotation references
- `decorators`: decorators/annotations
- `imports`: (module, name) tuples

### Node Types Per Language

**TypeScript**: function_declaration, arrow_function, method_definition, class_declaration, interface_declaration, enum_declaration, type_alias_declaration, import_statement

**JavaScript**: function_declaration, arrow_function, method_definition, class_declaration, import_statement, call_expression (require)

**C++**: function_definition, template_declaration, class_specifier, struct_specifier, enum_specifier, namespace_definition, preproc_include, using_declaration

**C**: function_definition, struct_specifier, enum_specifier, union_specifier, type_definition, preproc_include, preproc_def

**Java**: method_declaration, constructor_declaration, class_declaration, interface_declaration, enum_declaration, record_declaration, annotation_type_declaration, import_declaration, marker_annotation

### Registry Changes

Add factory functions in `registry.py` for each language (same pattern as `_create_react_extractor()`):
- `_create_typescript_extractor()`
- `_create_javascript_extractor()`
- `_create_cpp_extractor()`
- `_create_c_extractor()`
- `_create_java_extractor()`

Each prefers tree-sitter AST, falls back to regex.

### Fallback Strategy

Old regex extractors remain untouched as fallbacks for environments without tree-sitter grammars. Registry auto-detects availability.

## New Dependencies

```
pip install tree-sitter-c tree-sitter-cpp tree-sitter-java
```

Already installed: `tree-sitter`, `tree-sitter-typescript`, `tree-sitter-javascript`

## Testing

- Each AST extractor gets a dedicated test file
- Tests verify extraction matches or exceeds regex output
- Full 715-test suite must pass with no regressions
- Copy to plugin directory after completion
