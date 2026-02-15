# Native AST Parsers Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build native parser daemons for all non-Python languages (TypeScript, JavaScript, Rust, C, C++, Java), communicating with StreamRAG via msgpack over Unix domain sockets.

**Architecture:** 3 daemon processes (Node.js for TS/JS, Rust binary for Rust/C/C++, JVM for Java), Python glue layer in `streamrag/parsers/`, two-tier fallback (native → regex).

**Tech Stack:** TypeScript compiler API, syn crate, libclang, JavaParser, msgpack, Unix domain sockets

---

## Phase 1: Python Glue Layer (Foundation)

### Task 1: Msgpack Protocol Module

**Files:**
- Create: `streamrag/parsers/__init__.py`
- Create: `streamrag/parsers/protocol.py`
- Test: `tests/test_parser_protocol.py`

**What it does:**

The protocol module handles msgpack encoding/decoding and the length-prefixed frame format used by all parser daemons. This is the shared foundation everything else builds on.

**Step 1: Write failing test**

```python
# tests/test_parser_protocol.py
"""Tests for the native parser msgpack protocol."""

import pytest
from streamrag.parsers.protocol import encode_request, decode_response, frame_message, unframe_message


def test_encode_parse_request():
    data = encode_request("parse", source=b"function foo() {}", file_path="test.ts")
    assert isinstance(data, bytes)


def test_decode_response():
    import msgpack
    response = {
        "ok": True,
        "entities": [{
            "entity_type": "function",
            "name": "foo",
            "line_start": 1,
            "line_end": 1,
            "signature_hash": "abc123def456",
            "structure_hash": "654fedcba321",
            "calls": [],
            "inherits": [],
            "type_refs": [],
            "decorators": [],
            "imports": [],
            "params": [],
        }]
    }
    raw = msgpack.packb(response, use_bin_type=True)
    result = decode_response(raw)
    assert result["ok"] is True
    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "foo"


def test_frame_round_trip():
    payload = b"hello world"
    framed = frame_message(payload)
    assert len(framed) == 4 + len(payload)
    unframed = unframe_message(framed)
    assert unframed == payload


def test_encode_ping():
    data = encode_request("ping")
    assert isinstance(data, bytes)
```

**Step 2: Run test to verify it fails**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/test_parser_protocol.py -x -q
```

**Step 3: Install msgpack and implement**

```bash
pip install msgpack --break-system-packages
```

Create `streamrag/parsers/__init__.py` (empty).

Create `streamrag/parsers/protocol.py`:

```python
"""Msgpack protocol for native parser daemons.

Frame format: [4 bytes: payload length (big-endian uint32)] [payload: msgpack bytes]

Request:  {"action": str, "source": bytes, "file_path": str}
Response: {"ok": bool, "entities": list, "error": str|None}
"""

import struct
import msgpack
from typing import Any, Dict, Optional


def encode_request(action: str, *, source: bytes = b"", file_path: str = "") -> bytes:
    """Encode a request as msgpack bytes."""
    req = {"action": action, "source": source, "file_path": file_path}
    return msgpack.packb(req, use_bin_type=True)


def decode_response(data: bytes) -> Dict[str, Any]:
    """Decode a msgpack response."""
    return msgpack.unpackb(data, raw=False)


def frame_message(payload: bytes) -> bytes:
    """Wrap payload in a length-prefixed frame."""
    return struct.pack(">I", len(payload)) + payload


def unframe_message(data: bytes) -> bytes:
    """Extract payload from a length-prefixed frame."""
    if len(data) < 4:
        raise ValueError("Frame too short")
    length = struct.unpack(">I", data[:4])[0]
    return data[4:4 + length]
```

**Step 4: Run test to verify pass**

```bash
cd /Users/krrish/StreamRAG && python -m pytest tests/test_parser_protocol.py -x -q
```

**Step 5: Commit**

```bash
git add streamrag/parsers/ tests/test_parser_protocol.py
git commit -m "feat: add msgpack protocol module for native parser daemons"
```

---

### Task 2: NativeParserBridge (Socket Client)

**Files:**
- Create: `streamrag/parsers/bridge.py`
- Test: `tests/test_parser_bridge.py`

**What it does:**

Socket client that connects to a parser daemon's Unix domain socket, sends a parse request, and reads the response. Handles connection errors gracefully (returns None on failure so callers can fall back to regex).

**Step 1: Write test**

```python
# tests/test_parser_bridge.py
"""Tests for NativeParserBridge socket client."""

import asyncio
import os
import tempfile
import msgpack
import struct
import pytest
from streamrag.parsers.bridge import NativeParserBridge
from streamrag.parsers.protocol import frame_message


@pytest.fixture
def sock_path():
    with tempfile.TemporaryDirectory() as d:
        yield os.path.join(d, "test.sock")


@pytest.fixture
def mock_server(sock_path):
    """A mock parser daemon that echoes back a fixed response."""
    async def handler(reader, writer):
        # Read length prefix
        header = await reader.readexactly(4)
        length = struct.unpack(">I", header)[0]
        payload = await reader.readexactly(length)
        request = msgpack.unpackb(payload, raw=False)

        if request.get("action") == "ping":
            response = {"ok": True, "language": "test"}
        elif request.get("action") == "parse":
            response = {
                "ok": True,
                "entities": [{
                    "entity_type": "function",
                    "name": "hello",
                    "line_start": 1,
                    "line_end": 3,
                    "signature_hash": "abc123",
                    "structure_hash": "def456",
                    "calls": ["world"],
                    "inherits": [],
                    "type_refs": [],
                    "decorators": [],
                    "imports": [],
                    "params": ["name"],
                }]
            }
        else:
            response = {"ok": False, "error": "unknown action"}

        resp_bytes = msgpack.packb(response, use_bin_type=True)
        writer.write(struct.pack(">I", len(resp_bytes)) + resp_bytes)
        await writer.drain()
        writer.close()

    async def start():
        server = await asyncio.start_unix_server(handler, path=sock_path)
        return server

    return start


@pytest.mark.asyncio
async def test_ping(sock_path, mock_server):
    server = await mock_server()
    try:
        bridge = NativeParserBridge(sock_path)
        result = await bridge.ping()
        assert result is True
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_parse(sock_path, mock_server):
    server = await mock_server()
    try:
        bridge = NativeParserBridge(sock_path)
        entities = await bridge.parse(b"function hello(name) {}", "test.ts")
        assert len(entities) == 1
        assert entities[0]["name"] == "hello"
        assert entities[0]["calls"] == ["world"]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_connection_failure():
    bridge = NativeParserBridge("/nonexistent/path.sock")
    result = await bridge.ping()
    assert result is False


@pytest.mark.asyncio
async def test_parse_returns_none_on_failure():
    bridge = NativeParserBridge("/nonexistent/path.sock")
    entities = await bridge.parse(b"code", "test.ts")
    assert entities is None
```

**Step 2: Implement `streamrag/parsers/bridge.py`**

```python
"""Socket client for native parser daemons."""

import asyncio
import struct
import msgpack
from typing import Any, Dict, List, Optional

from streamrag.parsers.protocol import encode_request


class NativeParserBridge:
    """Connect to a parser daemon via Unix domain socket."""

    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    async def ping(self) -> bool:
        """Check if daemon is alive."""
        try:
            resp = await self._send_request("ping")
            return resp is not None and resp.get("ok", False)
        except Exception:
            return False

    async def parse(self, source: bytes, file_path: str) -> Optional[List[Dict[str, Any]]]:
        """Send source to daemon, return entities or None on failure."""
        try:
            resp = await self._send_request("parse", source=source, file_path=file_path)
            if resp and resp.get("ok"):
                return resp.get("entities", [])
            return None
        except Exception:
            return None

    async def _send_request(self, action: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Send a framed msgpack request and read framed response."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(self._socket_path),
            timeout=self._timeout,
        )
        try:
            payload = encode_request(action, **kwargs)
            frame = struct.pack(">I", len(payload)) + payload
            writer.write(frame)
            await writer.drain()

            header = await asyncio.wait_for(reader.readexactly(4), timeout=self._timeout)
            length = struct.unpack(">I", header)[0]
            data = await asyncio.wait_for(reader.readexactly(length), timeout=self._timeout)
            return msgpack.unpackb(data, raw=False)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
```

**Step 3: Run tests, full suite, commit**

```bash
pip install pytest-asyncio --break-system-packages
cd /Users/krrish/StreamRAG && python -m pytest tests/test_parser_bridge.py -x -q
cd /Users/krrish/StreamRAG && python -m pytest tests/ -x -q
git add streamrag/parsers/bridge.py tests/test_parser_bridge.py
git commit -m "feat: add NativeParserBridge socket client"
```

---

### Task 3: NativeExtractor Wrapper

**Files:**
- Create: `streamrag/parsers/wrapper.py`
- Test: `tests/test_native_wrapper.py`

**What it does:**

Implements `LanguageExtractor` ABC. Uses `NativeParserBridge` to send source to the daemon, converts the msgpack response dicts into `ASTEntity` objects. Falls back to a given regex extractor if daemon is unavailable.

**Step 1: Write test, Step 2: Implement**

The wrapper takes a bridge + fallback extractor. On `extract(source, file_path)`:
1. Try `bridge.parse()` (async, use `asyncio.run()` or event loop)
2. If success: convert dicts to `ASTEntity` objects, return
3. If failure: call `fallback.extract(source, file_path)`, return

**Step 3: Commit**

```bash
git add streamrag/parsers/wrapper.py tests/test_native_wrapper.py
git commit -m "feat: add NativeExtractor wrapper with fallback"
```

---

### Task 4: ParserDaemonManager

**Files:**
- Create: `streamrag/parsers/manager.py`
- Test: `tests/test_parser_manager.py`

**What it does:**

Manages lifecycle of parser daemon subprocesses:
- `start(language)` — spawn daemon process, wait for socket readiness
- `stop(language)` — send shutdown command, clean up socket/pid
- `ensure_running(language)` — start if not running, health check if running
- `stop_all()` — shut down all daemons

Socket paths: `~/.claude/streamrag/parsers/{language}.sock`
PID files: `~/.claude/streamrag/parsers/{language}.pid`

**Commit**

```bash
git add streamrag/parsers/manager.py tests/test_parser_manager.py
git commit -m "feat: add ParserDaemonManager for lifecycle management"
```

---

## Phase 2: TypeScript/JavaScript Parser Daemon (Node.js)

### Task 5: TypeScript Parser — Project Setup

**Files:**
- Create: `parsers/typescript/package.json`
- Create: `parsers/typescript/tsconfig.json`
- Create: `parsers/typescript/src/server.ts`

**What it does:**

Node.js daemon that listens on a Unix domain socket. Receives msgpack-framed parse requests, uses the TypeScript compiler API to parse source code, extracts entities, returns msgpack-framed responses.

**Dependencies:**
```json
{
  "dependencies": {
    "typescript": "^5.4",
    "@msgpack/msgpack": "^3.0"
  }
}
```

**Server skeleton (`src/server.ts`):**
- Listen on Unix domain socket (path from `--socket` CLI arg)
- On connection: read length-prefixed frame, decode msgpack
- Dispatch to parser based on file extension (.ts/.tsx vs .js/.jsx)
- Encode response as msgpack, write length-prefixed frame

**Step 1: Setup project**

```bash
cd /Users/krrish/StreamRAG && mkdir -p parsers/typescript/src
cd parsers/typescript && npm init -y && npm install typescript @msgpack/msgpack
```

**Step 2: Implement server.ts, Step 3: Test manually, Step 4: Commit**

---

### Task 6: TypeScript Parser — Entity Extraction

**Files:**
- Create: `parsers/typescript/src/parser.ts`

**What it does:**

Uses `ts.createSourceFile()` to parse TypeScript source, walks the AST with `ts.forEachChild()`, extracts:

- **Functions**: `FunctionDeclaration`, `ArrowFunction`, `MethodDeclaration` → entity_type="function"
- **Classes**: `ClassDeclaration` → entity_type="class"
- **Interfaces**: `InterfaceDeclaration` → entity_type="class"
- **Enums**: `EnumDeclaration` → entity_type="class"
- **Type aliases**: `TypeAliasDeclaration` → entity_type="variable"
- **Imports**: `ImportDeclaration` → entity_type="import"
- **Calls**: Walk `CallExpression` nodes in function bodies
- **Inheritance**: `HeritageClause` (extends/implements)
- **Type refs**: Walk type annotations for `TypeReference` nodes
- **Decorators**: `Decorator` nodes
- **Params**: `Parameter` nodes from function signatures
- **Scoping**: Methods inside classes → "ClassName.methodName"
- **Hashes**: SHA256[:12] of full text (signature), SHA256[:12] with name replaced (structure)

Also handles JavaScript (`.js`, `.jsx`, `.mjs`, `.cjs`) — the TS compiler parses JS natively, just skip TS-specific nodes (interfaces, enums, type aliases) for JS files.

**Builtin filtering**: Embed `TS_BUILTINS`, `TS_COMMON_METHODS` from builtins.py as TypeScript sets.

**Step 1: Implement, Step 2: Write Jest tests, Step 3: Commit**

---

### Task 7: TypeScript Parser — Integration Test

**Files:**
- Test: `tests/test_typescript_native.py`

**What it does:**

Python integration test that:
1. Starts the TypeScript parser daemon
2. Sends TypeScript source via the bridge
3. Verifies extracted entities match expected output
4. Tests all entity types: functions, classes, interfaces, enums, imports, etc.
5. Compares output quality vs regex extractor
6. Shuts down daemon

**Commit**

---

## Phase 3: Rust/C/C++ Parser Daemon (Rust Binary)

### Task 8: Rust Parser — Project Setup

**Files:**
- Create: `parsers/rust/Cargo.toml`
- Create: `parsers/rust/src/main.rs`

**Dependencies (Cargo.toml):**
```toml
[dependencies]
syn = { version = "2", features = ["full", "visit"] }
clang = "2"   # libclang bindings
rmp-serde = "1"  # msgpack
serde = { version = "1", features = ["derive"] }
sha2 = "0.10"
tokio = { version = "1", features = ["full"] }
```

**What it does:**

Single Rust binary that:
- Listens on Unix domain socket
- Routes by file extension: `.rs` → syn parser, `.c`/`.cpp`/`.h` → libclang parser
- Returns msgpack responses

**Step 1: Setup, Step 2: Implement server, Step 3: Commit**

---

### Task 9: Rust Parser — `syn`-Based Extraction

**Files:**
- Create: `parsers/rust/src/rust_parser.rs`

**What it does:**

Uses `syn::parse_file()` to parse Rust source, visits AST nodes:

- `ItemFn` → entity_type="function"
- `ItemStruct` → entity_type="class"
- `ItemEnum` → entity_type="class"
- `ItemTrait` → entity_type="class" (with trait bounds as inherits)
- `ItemImpl` → entity_type="class" (with trait as inherits, methods scoped)
- `ItemMod` → entity_type="module_code"
- `ItemUse` → entity_type="import"
- `ItemType` → entity_type="variable"
- `ItemConst`, `ItemStatic` → entity_type="variable"
- `ItemMacro` → entity_type="function"

Extracts calls by walking `ExprCall` and `ExprMethodCall` in function bodies.
Extracts type refs from function signatures.
Filters through `RUST_BUILTINS`, `RUST_COMMON_METHODS`.

**Step 1: Implement, Step 2: Write Rust tests, Step 3: Commit**

---

### Task 10: Rust Parser — libclang C/C++ Extraction

**Files:**
- Create: `parsers/rust/src/c_parser.rs`
- Create: `parsers/rust/src/cpp_parser.rs`

**What it does:**

Uses libclang to parse C/C++ source. Walks the AST cursor:

**C entities:**
- `CXCursor_FunctionDecl` → entity_type="function"
- `CXCursor_StructDecl` → entity_type="class"
- `CXCursor_EnumDecl` → entity_type="class"
- `CXCursor_UnionDecl` → entity_type="class"
- `CXCursor_TypedefDecl` → entity_type="variable"
- `CXCursor_MacroDefinition` → entity_type="variable" or "function"
- `CXCursor_InclusionDirective` → entity_type="import"

**C++ additional:**
- `CXCursor_ClassDecl` → entity_type="class" (with base classes as inherits)
- `CXCursor_CXXMethod` → entity_type="function" (scoped under class)
- `CXCursor_Constructor`, `CXCursor_Destructor` → entity_type="function"
- `CXCursor_Namespace` → scope container
- `CXCursor_ClassTemplate` → entity_type="class"
- `CXCursor_FunctionTemplate` → entity_type="function"
- `CXCursor_UsingDeclaration` → entity_type="import"

Filters through `CPP_BUILTINS`/`C_BUILTINS` and common methods.

**Step 1: Implement, Step 2: Write Rust tests, Step 3: Commit**

---

### Task 11: Rust Parser — Integration Test

**Files:**
- Test: `tests/test_rust_native.py`
- Test: `tests/test_c_native.py`
- Test: `tests/test_cpp_native.py`

Python integration tests for all three languages (Rust, C, C++) through the Rust daemon.

---

## Phase 4: Java Parser Daemon (JVM)

### Task 12: Java Parser — Project Setup

**Files:**
- Create: `parsers/java/pom.xml`
- Create: `parsers/java/src/main/java/streamrag/Server.java`

**Dependencies (pom.xml):**
```xml
<dependencies>
    <dependency>
        <groupId>com.github.javaparser</groupId>
        <artifactId>javaparser-core</artifactId>
        <version>3.26.1</version>
    </dependency>
    <dependency>
        <groupId>org.msgpack</groupId>
        <artifactId>msgpack-core</artifactId>
        <version>0.9.8</version>
    </dependency>
</dependencies>
```

**Step 1: Setup Maven project, Step 2: Implement server, Step 3: Commit**

---

### Task 13: Java Parser — Entity Extraction

**Files:**
- Create: `parsers/java/src/main/java/streamrag/Parser.java`

**What it does:**

Uses JavaParser to parse Java source, visits:

- `MethodDeclaration` → entity_type="function" (scoped under class)
- `ConstructorDeclaration` → entity_type="function"
- `ClassOrInterfaceDeclaration` → entity_type="class"
- `EnumDeclaration` → entity_type="class"
- `RecordDeclaration` → entity_type="class"
- `AnnotationDeclaration` → entity_type="class"
- `ImportDeclaration` → entity_type="import"
- `AnnotationExpr` → decorators (filter @Override, @Deprecated etc.)
- `MethodCallExpr` → calls
- `ClassOrInterfaceType` → type_refs / inherits

Filters through `JAVA_BUILTINS`, `JAVA_COMMON_METHODS`.

**Step 1: Implement, Step 2: Write JUnit tests, Step 3: Commit**

---

### Task 14: Java Parser — Integration Test

**Files:**
- Test: `tests/test_java_native.py`

---

## Phase 5: Wire Everything Together

### Task 15: Update Registry

**Files:**
- Modify: `streamrag/languages/registry.py`

Update `create_default_registry()` to use `NativeExtractor` wrappers for all languages, with regex fallback.

---

### Task 16: Update StreamRAGDaemon

**Files:**
- Modify: `streamrag/daemon.py`

Add `ParserDaemonManager` startup/shutdown to the daemon lifecycle:
- On daemon start: launch parser daemons for detected languages
- On daemon stop: shut down all parser daemons

---

### Task 17: Full Regression & Deploy

**Step 1:** Run full test suite
**Step 2:** Copy to plugin directory
**Step 3:** Update CLAUDE.md
**Step 4:** Final commit
