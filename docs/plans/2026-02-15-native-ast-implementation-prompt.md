# Native AST Implementation — Session Prompt

Copy everything below this line and paste it as your first message in a new Claude Code session:

---

I need you to implement native AST parsers for StreamRAG. Read the design doc first, then implement task by task.

## Context

StreamRAG is at `/Users/krrish/StreamRAG/`. It's a real-time incremental code graph system for Claude Code. Currently it uses regex-based parsers for most languages. We're replacing them with native compiler-level AST parsers.

**Read these files first (in order):**
1. `/Users/krrish/StreamRAG/CLAUDE.md` — project rules and conventions
2. `/Users/krrish/StreamRAG/docs/plans/2026-02-15-native-ast-design.md` — the full architecture design
3. `/Users/krrish/StreamRAG/streamrag/languages/base.py` — LanguageExtractor ABC (interface all extractors implement)
4. `/Users/krrish/StreamRAG/streamrag/models.py` — ASTEntity dataclass (what parsers must output)
5. `/Users/krrish/StreamRAG/streamrag/languages/builtins.py` — per-language builtin filter sets
6. `/Users/krrish/StreamRAG/streamrag/daemon.py` — existing daemon pattern (Unix socket + JSON, we use msgpack instead)
7. `/Users/krrish/StreamRAG/streamrag/languages/registry.py` — how extractors are registered
8. `/Users/krrish/StreamRAG/streamrag/extractor.py` — Python AST extractor (the gold standard to match)

## Architecture

3 daemon processes, each a persistent server on a Unix domain socket, speaking msgpack:

| Daemon | Runtime | Parser | Languages |
|--------|---------|--------|-----------|
| Node.js | Node ≥ 18 | TypeScript compiler API (`ts.createSourceFile`) | TS, JS, TSX, JSX |
| Rust binary | Native | `syn` (Rust) + `libclang` via `clang-sys` (C/C++) | Rust, C, C++ |
| JVM | Java ≥ 17 | JavaParser (`com.github.javaparser`) | Java |

**Protocol:**
- Unix domain sockets at `~/.claude/streamrag/parsers/{language}.sock`
- Length-prefixed msgpack: `[4 bytes big-endian uint32 length][msgpack payload]`
- Request: `{"action": "parse", "source": <bytes>, "file_path": <string>}`
- Response: `{"ok": true, "entities": [<ASTEntity-compatible dicts>]}`
- Also support `{"action": "ping"}` and `{"action": "shutdown"}`

**Each entity in the response must have:**
- `entity_type`: "function" | "class" | "variable" | "import" | "module_code"
- `name`: hierarchically scoped (e.g., "ClassName.methodName")
- `line_start`, `line_end`: 1-indexed
- `signature_hash`: SHA256[:12] of the full entity source text
- `structure_hash`: SHA256[:12] of entity text with name replaced by "___"
- `calls`: list of function/method calls (filtered through language builtins from builtins.py)
- `inherits`: list of base classes/interfaces/traits
- `type_refs`: list of type annotation references (filtered through type builtins)
- `decorators`: list of decorator/annotation names
- `imports`: list of [module, name] pairs
- `params`: list of parameter names

## Tasks — Implement In Order

### Task 1: Python Glue Layer

Create `streamrag/parsers/` module:

**`streamrag/parsers/__init__.py`** — empty

**`streamrag/parsers/bridge.py`** — `NativeParserBridge` class:
- `__init__(self, socket_path: str)` — store path, no connect yet
- `parse(self, source: str, file_path: str) -> List[dict]` — connect, send msgpack request, read msgpack response, return entities list
- `ping(self) -> bool` — send ping, return True if alive
- `shutdown(self)` — send shutdown
- `is_available(self) -> bool` — check if socket exists and daemon responds to ping
- Use length-prefixed msgpack framing (4-byte big-endian uint32 + payload)
- Handle connection errors gracefully (return empty list, not crash)
- Keep connection open between calls (connection pooling)

**`streamrag/parsers/manager.py`** — `ParserDaemonManager` class:
- `start(self, language: str)` — start the appropriate daemon subprocess
- `stop(self, language: str)` — send shutdown, wait, kill if needed
- `ensure_running(self, language: str) -> bool` — start if not running, return success
- `stop_all(self)` — stop all daemons
- Socket paths: `~/.claude/streamrag/parsers/{language}.sock`
- PID files: `~/.claude/streamrag/parsers/{language}.pid`
- Daemon commands:
  - typescript: `node parsers/typescript/dist/server.js --socket <path>`
  - rust: `parsers/rust/target/release/streamrag-parser --socket <path>`
  - java: `java -jar parsers/java/target/parser.jar --socket <path>`

**`streamrag/parsers/wrapper.py`** — `NativeExtractor` class:
- Implements `LanguageExtractor` ABC
- `__init__(self, language_id, extensions, bridge, fallback_extractor)`
- `extract(source, file_path)` — try bridge.parse(), convert dicts to ASTEntity objects, fall back to fallback_extractor on failure
- `can_handle(file_path)` — check extensions
- `language_id` / `supported_extensions` properties

**Dependencies:** `pip install msgpack` (or use pure-Python `msgpack` — check if it works with `--break-system-packages` or in the project venv)

**Tests:** `tests/test_parser_bridge.py` — test bridge with a mock socket server, test NativeExtractor fallback behavior

**Commit after this task.**

### Task 2: TypeScript/JavaScript Parser Daemon

Create `parsers/typescript/` Node.js project:

**`parsers/typescript/package.json`:**
```json
{
  "name": "streamrag-ts-parser",
  "version": "1.0.0",
  "type": "module",
  "scripts": { "build": "tsc", "start": "node dist/server.js" },
  "dependencies": {
    "typescript": "^5.0.0",
    "@msgpack/msgpack": "^3.0.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0"
  }
}
```

**`parsers/typescript/src/server.ts`:**
- Parse `--socket <path>` from CLI args
- Create Unix domain socket server (`net.createServer`)
- On connection: read length-prefixed msgpack frames
- Dispatch to parser based on action
- Write length-prefixed msgpack response
- Handle `ping` (return `{"ok": true}`) and `shutdown` (clean exit)

**`parsers/typescript/src/parser.ts`:**
- Use `ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, scriptKind)`
- For `.ts` files: `ScriptKind.TS`, for `.tsx`: `ScriptKind.TSX`, for `.js`/`.mjs`/`.cjs`: `ScriptKind.JS`, for `.jsx`: `ScriptKind.JSX`
- Walk AST with `ts.forEachChild(node, visitor)`
- Extract:
  - **Functions**: `FunctionDeclaration`, `ArrowFunction`, `MethodDeclaration`, `FunctionExpression`, `GetAccessor`, `SetAccessor`
  - **Classes**: `ClassDeclaration`, `InterfaceDeclaration`, `EnumDeclaration`, `TypeAliasDeclaration`
  - **Imports**: `ImportDeclaration` (named, default, namespace), CommonJS `require()` calls
  - **Calls**: Walk `CallExpression` nodes, extract callee name, filter builtins
  - **Type refs**: Walk type annotations, extract `TypeReference` identifiers
  - **Decorators**: `Decorator` nodes on classes/methods
  - **Inheritance**: `HeritageClause` (extends/implements)
- Compute `signature_hash` and `structure_hash` using SHA256 of source text
- Apply hierarchical scoping: methods inside classes get `ClassName.methodName`
- Filter calls through TS/JS builtins (embed the sets from builtins.py)

**Build:** `cd parsers/typescript && npm install && npm run build`

**Tests:** `parsers/typescript/test/` — unit tests for the parser (use Node test runner or jest)

**Commit after this task.**

### Task 3: Wire TS/JS into StreamRAG Registry

- Update `streamrag/languages/registry.py`:
  - Add `_create_native_typescript_extractor()` and `_create_native_javascript_extractor()`
  - Each creates a `NativeExtractor` with the TS daemon bridge, falling back to existing extractors
- Update `create_default_registry()` to use native extractors
- Add `ParserDaemonManager` integration (auto-start TS daemon when needed)

**Tests:** `tests/test_native_typescript.py` — integration test: start daemon, parse TS/JS source, verify ASTEntity output matches expected

**Commit after this task.**

### Task 4: Rust Parser (syn)

Add to `parsers/rust/` Rust project:

**`parsers/rust/Cargo.toml`:**
```toml
[package]
name = "streamrag-parser"
version = "0.1.0"
edition = "2021"

[dependencies]
syn = { version = "2", features = ["full", "visit"] }
rmp-serde = "1"  # msgpack
serde = { version = "1", features = ["derive"] }
serde_json = "1"
sha2 = "0.10"
tokio = { version = "1", features = ["full"] }
clang-sys = { version = "1", features = ["clang_16_0"] }
```

**`parsers/rust/src/rust_parser.rs`:**
- Use `syn::parse_file(source)` to get full Rust AST
- Walk with syn's visitor pattern
- Extract:
  - **Functions**: `ItemFn`, `ImplItemFn`, `TraitItemFn`
  - **Classes**: `ItemStruct`, `ItemEnum`, `ItemTrait`, `ItemImpl` (→ entity_type="class")
  - **Variables**: `ItemConst`, `ItemStatic`, `ItemType` (type alias)
  - **Imports**: `ItemUse` — parse use trees recursively
  - **Modules**: `ItemMod`
  - **Macros**: `ItemMacro` (macro definitions)
  - **Calls**: Walk `ExprCall`, `ExprMethodCall`, `MacroInvocation`
  - **Type refs**: Walk type annotations
  - **Decorators**: `#[attribute]` items
  - **Inheritance**: trait bounds, impl trait for Type
- Scope methods under their impl/trait block
- Filter through Rust builtins

**`parsers/rust/src/main.rs`:**
- Parse `--socket <path>` and `--language <rust|c|cpp>` from CLI
- Tokio async Unix socket server
- Route to `rust_parser`, `c_parser`, or `cpp_parser` based on file extension
- Msgpack framing (same protocol as TS daemon)

**Build:** `cd parsers/rust && cargo build --release`

**Commit after this task.**

### Task 5: C/C++ Parser (libclang)

Add to same Rust binary:

**`parsers/rust/src/c_parser.rs`** and **`parsers/rust/src/cpp_parser.rs`:**
- Use `clang-sys` to call libclang API
- Create translation unit from source string
- Walk AST cursor tree (`clang_visitChildren`)
- Extract:
  - **C functions**: `CXCursor_FunctionDecl`
  - **C structs**: `CXCursor_StructDecl`
  - **C enums**: `CXCursor_EnumDecl`
  - **C unions**: `CXCursor_UnionDecl`
  - **C typedefs**: `CXCursor_TypedefDecl`
  - **C macros**: `CXCursor_MacroDefinition`
  - **C++ classes**: `CXCursor_ClassDecl`, `CXCursor_ClassTemplate`
  - **C++ methods**: `CXCursor_CXXMethod`, `CXCursor_Constructor`, `CXCursor_Destructor`
  - **C++ namespaces**: `CXCursor_Namespace`
  - **Includes**: `CXCursor_InclusionDirective`
  - **C++ using**: `CXCursor_UsingDeclaration`, `CXCursor_UsingDirective`
  - **Inheritance**: `CXCursor_CXXBaseSpecifier`
- Apply hierarchical scoping (class methods, namespace members)
- Filter through C/C++ builtins

**Build:** Same `cargo build --release` (single binary handles all 3 languages)

**Requires on user machine:** `libclang` (macOS: comes with Xcode CLI tools, Linux: `apt install libclang-dev`)

**Commit after this task.**

### Task 6: Wire Rust/C/C++ into Registry

Same pattern as Task 3 but for Rust, C, C++ extractors.

**Commit after this task.**

### Task 7: Java Parser Daemon

Create `parsers/java/` Maven project:

**Parser:** Use `com.github.javaparser:javaparser-core`
- Parse with `StaticJavaParser.parse(source)`
- Walk AST with visitor pattern
- Extract classes, interfaces, enums, records, methods, constructors, imports, annotations
- Apply scoping, filter builtins, compute hashes

**Server:** Unix socket server using `java.net.UnixDomainSocketAddress` (Java 16+)
- Msgpack via `org.msgpack:msgpack-core`
- Same length-prefixed protocol

**Build:** `cd parsers/java && mvn package` → fat JAR

**Commit after this task.**

### Task 8: Wire Java + Full Regression + Deploy

- Wire Java into registry
- Run full test suite: `python -m pytest tests/ -x -q`
- Copy to plugin directory
- Update CLAUDE.md

**Commit after this task.**

## Important Rules

- Work from `/Users/krrish/StreamRAG/` only
- After modifying streamrag/ files, copy to `~/.claude/streamrag/StreamRAG/streamrag/` (see CLAUDE.md)
- Run `python -m pytest tests/ -x -q` after each task to check for regressions
- Commit after each task with descriptive messages
- All extractors must produce `ASTEntity` objects matching the existing schema exactly
- Each native parser must embed its own builtin filter sets (from builtins.py)
- No tree-sitter anywhere — only native compiler-level parsers
- No regex for parsing — regex only acceptable for hash computation and trivial string ops
