# Native AST Parser Design (v2)

> Supersedes: `2026-02-15-full-ast-migration-design.md` (tree-sitter approach)

## Goal

Replace all regex-based language extractors with **native parsers written in each language**, just like Python uses its own `ast` module. Each parser runs as a persistent daemon, communicating with StreamRAG Python core via Unix domain sockets and MessagePack.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    StreamRAG Python Core                         │
│  bridge.py  ←→  NativeBridge  ←→  LanguageExtractor wrappers   │
└──────────────────────┬──────────────────────────────────────────┘
                       │ msgpack over Unix domain socket
          ┌────────────┼────────────────────────────┐
          │            │                            │
    ┌─────▼────┐ ┌─────▼─────┐ ┌──────▼──────┐ ┌──▼───┐ ┌──▼──┐
    │ TS/JS    │ │ Rust      │ │ C/C++       │ │ Java │ │ Py  │
    │ Parser   │ │ Parser    │ │ Parser      │ │Parser│ │ ast │
    │ (Node)   │ │ (binary)  │ │ (libclang)  │ │(JVM) │ │(in) │
    └──────────┘ └───────────┘ └─────────────┘ └──────┘ └─────┘
    daemon         daemon        daemon          daemon   inline
```

## Native Parser Per Language

| Language | Runtime | Parser Library | Why |
|----------|---------|---------------|-----|
| **Python** | Python (inline) | `ast` module | Already done — stdlib, no daemon needed |
| **TypeScript** | Node.js | `typescript` compiler API (`ts.createSourceFile`) | The actual TS compiler — 100% syntax + type info |
| **JavaScript** | Node.js | Same TS compiler (JS mode) or `@babel/parser` | TS compiler handles JS natively |
| **Rust** | Rust binary | `syn` crate | Standard Rust AST parser, used by rustfmt/clippy |
| **C/C++** | Rust binary | `libclang` via `clang-sys` Rust crate | The actual Clang compiler's AST — full semantic understanding, handles all C/C++ syntax |
| **Java** | JVM | JavaParser (`com.github.javaparser`) | Full Java grammar, no javac needed |

### Why TS compiler for TypeScript/JavaScript?

The TypeScript compiler API (`ts.createSourceFile`) gives us:
- Full AST with exact node types for every TS/JS construct
- Type annotation resolution built in
- Handles all edge cases (template literals, decorators, JSX)
- The same parser used by VS Code, ESLint, Prettier
- JS is a subset of TS — one parser handles both

### Why `syn` for Rust?

- The standard Rust parsing crate (used by proc macros, rustfmt, clippy)
- Compiles to a fast native binary
- Full fidelity: handles lifetimes, generics, macros, attributes
- No runtime dependency (static binary)

### Why libclang for C/C++?

- The actual Clang compiler frontend — 100% accurate AST
- Handles every C/C++ construct (templates, macros, preprocessor, namespaces)
- Accessed from Rust via `clang-sys` crate (FFI bindings to libclang)
- Available on macOS (Xcode), Linux (`libclang-dev`), Windows (LLVM installer)
- Same parser used by clangd, clang-tidy, clang-format

### Why JavaParser for Java?

- Mature, widely used (10k+ GitHub stars)
- Handles all Java syntax (records, sealed classes, pattern matching)
- No javac/JDK compilation step needed — pure parsing
- Runs on any JRE

## Protocol

### Transport

- Unix domain sockets at `~/.claude/streamrag/parsers/{language}.sock`
- PID files at `~/.claude/streamrag/parsers/{language}.pid`
- Same lifecycle pattern as existing `StreamRAGDaemon`

### Message Format

MessagePack-encoded, length-prefixed frames:

```
[4 bytes: payload length (big-endian uint32)] [payload: msgpack bytes]
```

### Request

```python
{
    "action": "parse",          # or "ping", "shutdown"
    "source": b"...",           # raw source bytes
    "file_path": "src/main.ts", # for context (optional)
}
```

### Response

```python
{
    "ok": True,
    "entities": [
        {
            "entity_type": "function",     # function|class|variable|import|module_code
            "name": "ClassName.method",     # hierarchically scoped
            "line_start": 10,              # 1-indexed
            "line_end": 25,                # 1-indexed
            "signature_hash": "a1b2c3d4e5f6",  # SHA256[:12] of full text
            "structure_hash": "f6e5d4c3b2a1",  # SHA256[:12] with name removed
            "calls": ["otherFunc", "Foo.bar"],
            "inherits": ["BaseClass"],
            "type_refs": ["UserModel", "Config"],
            "decorators": ["Service", "inject"],
            "imports": [["./module", "name"]],
            "params": ["arg1", "arg2"],
        },
        ...
    ]
}
```

### Error Response

```python
{
    "ok": False,
    "error": "SyntaxError at line 42: unexpected token",
    "entities": []  # empty on error, never crash
}
```

## Python Glue Layer

### `streamrag/parsers/` — New Module

```
streamrag/parsers/
├── __init__.py
├── bridge.py           # NativeParserBridge: socket client, msgpack codec
├── manager.py          # ParserDaemonManager: start/stop/health-check daemons
└── wrapper.py          # NativeExtractor: LanguageExtractor wrapper using bridge
```

### NativeParserBridge (bridge.py)

- Connects to language-specific Unix domain socket
- Sends msgpack request, reads msgpack response
- Handles connection failures (daemon not running → fall back to regex)
- Connection pooling (keep socket open between calls)

### ParserDaemonManager (manager.py)

- Starts/stops parser daemons as subprocesses
- Health checks via "ping" action
- Auto-restart on crash
- Launched by StreamRAGDaemon on startup

### NativeExtractor (wrapper.py)

- Implements `LanguageExtractor` ABC
- Sends source to native parser via bridge
- Converts msgpack response to `List[ASTEntity]`
- Falls back to regex extractor if daemon unavailable

## Parser Daemon Implementations

### Directory Structure

```
StreamRAG/
├── streamrag/          # Python core (existing)
├── parsers/
│   ├── typescript/     # Node.js TypeScript/JavaScript parser daemon
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── server.ts       # Unix socket server + msgpack
│   │       ├── parser.ts       # TS compiler API extraction
│   │       └── js-parser.ts    # JS extraction (TS compiler in JS mode)
│   ├── rust/           # Rust parser daemon (syn + libclang)
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── main.rs         # Unix socket server + msgpack
│   │       ├── rust_parser.rs  # syn-based Rust extraction
│   │       ├── c_parser.rs     # libclang-based C extraction
│   │       └── cpp_parser.rs   # libclang-based C++ extraction
│   └── java/           # Java parser daemon
│       ├── pom.xml (or build.gradle)
│       └── src/main/java/
│           ├── Server.java     # Unix socket server + msgpack
│           └── Parser.java     # JavaParser extraction
```

### TypeScript Parser (handles both TS and JS)

- **Runtime**: Node.js
- **Libraries**: `typescript` (compiler API), `msgpack-lite` or `@msgpack/msgpack`
- **Entry**: `node parsers/typescript/dist/server.js --socket ~/.claude/streamrag/parsers/typescript.sock`
- Handles `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`

### Rust Parser (handles Rust + C + C++)

- **Runtime**: Native binary
- **Libraries**: `syn` (Rust), `clang-sys` / `clang` crate for libclang FFI (C/C++)
- **Entry**: `parsers/rust/target/release/streamrag-parser --socket ~/.claude/streamrag/parsers/rust.sock`
- Handles `.rs`, `.c`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.h`
- Single binary, three languages
- Requires `libclang` installed on system (Xcode on macOS, `libclang-dev` on Linux)

### Java Parser

- **Runtime**: JVM
- **Libraries**: `com.github.javaparser:javaparser-core`, `org.msgpack:msgpack-core`
- **Entry**: `java -jar parsers/java/target/parser.jar --socket ~/.claude/streamrag/parsers/java.sock`
- Handles `.java`

## Fallback Strategy

Two-tier fallback per language:

```
1. Native parser daemon (full accuracy)
   ↓ daemon not running or runtime unavailable
2. Regex extractor (baseline accuracy, always available, zero deps)
```

## Builtin Filtering

Each native parser applies the same builtin/common-method filters as the current Python extractors. The filter sets from `builtins.py` are embedded in each native parser (or passed as configuration on daemon startup).

## Performance Budget

| Operation | Target | Notes |
|-----------|--------|-------|
| Socket round-trip | < 0.5ms | Unix domain socket, local |
| Msgpack encode/decode | < 0.1ms | Per file |
| Native parse | < 1ms | Per file (TS compiler: ~0.5ms, syn: ~0.1ms, JavaParser: ~1ms) |
| Total per-edit | < 2ms | Well within StreamRAG's incremental budget |

## Dependencies on User Machine

| Language | Requires |
|----------|----------|
| TypeScript/JavaScript | Node.js ≥ 18 |
| Rust | None (pre-compiled binary) |
| C/C++ | `libclang` (Xcode on macOS, `libclang-dev` on Linux) |
| Java | JRE ≥ 17 |

## Testing

- Each native parser has its own test suite in its language
- Python integration tests verify the full pipeline (source → daemon → ASTEntity)
- Existing regex extractor tests remain as baseline comparison
- Full StreamRAG test suite must pass
