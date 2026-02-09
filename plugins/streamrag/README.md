<p align="center">
  <img src="assets/logo.svg" alt="StreamRAG" width="700"/>
</p>

<p align="center">
  <strong>Real-time incremental code graph that gives Claude Code structural superpowers.</strong>
</p>

<p align="center">
  <a href="#installation"><img src="https://img.shields.io/badge/python-%3E%3D3.9-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.9+"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge" alt="MIT License"/></a>
  <img src="https://img.shields.io/badge/dependencies-zero-06b6d4?style=for-the-badge" alt="Zero Dependencies"/>
  <img src="https://img.shields.io/badge/tests-597_passing-8b5cf6?style=for-the-badge" alt="597 Tests"/>
  <img src="https://img.shields.io/badge/languages-7-ec4899?style=for-the-badge" alt="7 Languages"/>
</p>

<br/>

## Quick Install

```bash
claude plugin marketplace add Krrish109/StreamRAG
claude plugin install streamrag@streamrag
```

Restart Claude Code — StreamRAG activates automatically on every session.

<br/>

## The Problem

Claude Code is powerful but **flies blind on code structure**. It greps for callers, guesses at dependencies, and can't reliably answer "what breaks if I change this?" For large codebases, this means wasted context window on exploration and missed dependencies on refactors.

## The Solution

StreamRAG maintains a **live dependency graph** that updates incrementally on every edit. Instead of re-scanning the whole project, it computes the minimal AST diff and surgically patches only the changed nodes and edges — achieving **26x faster** code intelligence.

<br/>

<table>
<tr>
<td width="50%">

### Without StreamRAG

```
User: "What calls validate()?"

Claude: Let me search for that...
  → grep -r "validate" --include="*.py"
  → Found 47 matches (includes comments,
    strings, variable names...)
  → Let me grep more specifically...
  → grep -r "validate(" --include="*.py"
  → Still 23 matches to sift through...
```

❌ Multiple grep rounds<br/>
❌ False positives from strings/comments<br/>
❌ No transitive dependency awareness<br/>
❌ Burns context window on exploration

</td>
<td width="50%">

### With StreamRAG

```
User: "What calls validate()?"

Claude: [StreamRAG auto-answers from graph]

  Callers of validate (3):
    auth_service.py → login()     [high]
    auth_service.py → register()  [high]
    middleware.py   → check_auth() [high]

  Affected files: 5
```

✅ Instant, precise answer<br/>
✅ Only real call relationships<br/>
✅ Confidence-scored edges<br/>
✅ Zero context window cost

</td>
</tr>
</table>

<br/>

## ✨ Key Features

<table>
<tr>
<td width="33%" valign="top">

### 🔄 Incremental Updates
Every `Edit`/`Write` triggers a surgical graph patch. Only changed entities are reprocessed — no full rebuilds ever.

</td>
<td width="33%" valign="top">

### 🔍 16 Query Commands
Callers, callees, impact analysis, dead code, cycles, shortest path, exports, natural language queries, visualization, and more.

</td>
<td width="33%" valign="top">

### 🌐 7 Languages
Python (full AST), TypeScript, JavaScript, Rust, C++, C, and Java with regex-based extraction.

</td>
</tr>
<tr>
<td width="33%" valign="top">

### 🧠 Proactive Intelligence
Automatic cycle detection, dead code warnings, and breaking change alerts on every edit — before you even ask.

</td>
<td width="33%" valign="top">

### 📊 Rich Context Injection
When Claude reads a file, StreamRAG injects entity signatures, callers, imports, and affected files as context.

</td>
<td width="33%" valign="top">

### 💾 Persistent Across Sessions
Graph state saves to `~/.claude/streamrag/` and restores automatically. Your code intelligence survives restarts.

</td>
</tr>
</table>

<br/>

---

<br/>

## 📦 Installation

```bash
# Install as a Claude Code plugin
claude plugin add /path/to/streamrag
```

**Requirements:** Python >= 3.9. Zero external dependencies — runs entirely on Python stdlib.

<br/>

## 🚀 Quick Start

StreamRAG activates **automatically**. On your first file edit, it scans the project (up to 200 files, <7s) and builds the initial graph. After that, every edit updates incrementally.

```bash
# Check graph status
/streamrag

# Ask about code relationships
/streamrag-ask what calls process_change

# Get context for a specific file  (auto-invoked by Claude)
/streamrag-context
```

<br/>

## 📖 Query Reference

<table>
<tr>
<th>Command</th>
<th>Description</th>
<th>Example</th>
</tr>

<tr>
<td><code>callers &lt;name&gt;</code></td>
<td>Who calls / imports / inherits this</td>
<td><code>callers validate</code></td>
</tr>

<tr>
<td><code>callees &lt;name&gt;</code></td>
<td>What does this entity call / import</td>
<td><code>callees AuthService</code></td>
</tr>

<tr>
<td><code>deps &lt;file&gt;</code></td>
<td>Forward file dependencies</td>
<td><code>deps auth/service.py</code></td>
</tr>

<tr>
<td><code>rdeps &lt;file&gt;</code></td>
<td>Reverse deps (what depends on this file)</td>
<td><code>rdeps models.py</code></td>
</tr>

<tr>
<td><code>impact &lt;file&gt;</code></td>
<td>Transitive impact analysis</td>
<td><code>impact core/auth.py</code></td>
</tr>

<tr>
<td><code>dead</code></td>
<td>Find unused functions and classes</td>
<td><code>dead --all</code></td>
</tr>

<tr>
<td><code>cycles</code></td>
<td>Detect circular file dependencies</td>
<td><code>cycles</code></td>
</tr>

<tr>
<td><code>path &lt;src&gt; &lt;dst&gt;</code></td>
<td>Shortest dependency chain</td>
<td><code>path UserModel validate</code></td>
</tr>

<tr>
<td><code>file &lt;file&gt;</code></td>
<td>All entities in a file</td>
<td><code>file server.py</code></td>
</tr>

<tr>
<td><code>entity &lt;name&gt;</code></td>
<td>Full detail for an entity</td>
<td><code>entity DeltaGraphBridge</code></td>
</tr>

<tr>
<td><code>search &lt;regex&gt;</code></td>
<td>Find entities by pattern</td>
<td><code>search "test_.*"</code></td>
</tr>

<tr>
<td><code>exports &lt;file&gt;</code></td>
<td>Module exports (<code>__all__</code>)</td>
<td><code>exports utils.py</code></td>
</tr>

<tr>
<td><code>stats</code></td>
<td>Graph statistics</td>
<td><code>stats</code></td>
</tr>

<tr>
<td><code>ask "&lt;question&gt;"</code></td>
<td>Natural language query</td>
<td><code>ask "what calls foo"</code></td>
</tr>

<tr>
<td><code>visualize &lt;file&gt;</code></td>
<td>Generate Mermaid / DOT diagrams</td>
<td><code>visualize --format mermaid</code></td>
</tr>

<tr>
<td><code>summary</code></td>
<td>Architecture overview</td>
<td><code>summary</code></td>
</tr>
</table>

> **Name resolution** is progressive: exact match → suffix match → regex fallback.
> Use bare names (`callers foo`), qualified names (`callers Bar.foo`), or patterns (`search "test_.*"`).

<br/>

## 🌐 Supported Languages

<table>
<tr>
<th>Language</th>
<th>Extraction</th>
<th>Functions</th>
<th>Classes</th>
<th>Imports</th>
<th>Inheritance</th>
<th>Calls</th>
<th>Types</th>
<th>Decorators</th>
</tr>

<tr>
<td>🐍 <strong>Python</strong></td>
<td>Full AST</td>
<td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td>
</tr>

<tr>
<td>🟦 <strong>TypeScript</strong></td>
<td>Regex</td>
<td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td>
</tr>

<tr>
<td>🟨 <strong>JavaScript</strong></td>
<td>Regex</td>
<td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>—</td><td>✅</td>
</tr>

<tr>
<td>🦀 <strong>Rust</strong></td>
<td>Regex</td>
<td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>—</td><td>✅</td>
</tr>

<tr>
<td>⚡ <strong>C++</strong></td>
<td>Regex</td>
<td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>—</td><td>—</td>
</tr>

<tr>
<td>🔧 <strong>C</strong></td>
<td>Regex</td>
<td>✅</td><td>✅</td><td>✅</td><td>—</td><td>✅</td><td>—</td><td>—</td>
</tr>

<tr>
<td>☕ <strong>Java</strong></td>
<td>Regex</td>
<td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>✅</td><td>—</td><td>✅</td>
</tr>
</table>

<br/>

## ⚙️ How It Works

<p align="center">
  <img src="assets/pipeline.svg" alt="StreamRAG Pipeline" width="800"/>
</p>

### The Incremental Pipeline

Traditional code intelligence tools rebuild the entire index on every change. StreamRAG takes a fundamentally different approach:

1. **Extract** — Parse old and new file content into entity lists (functions, classes, imports, variables)
2. **Diff** — Compute the minimal delta: added, removed, modified, or renamed entities
3. **Patch** — Surgically update only affected nodes and edges in the graph
4. **Resolve** — Two-pass edge resolution links calls, imports, and inheritance across files
5. **Propagate** — Bounded propagation re-parses files affected by the change

### Edge Types Tracked

| Edge | Meaning | Example |
|------|---------|---------|
| `calls` | Function/method call | `login()` → `validate()` |
| `imports` | Import linked to definition | `from auth import validate` → `def validate` |
| `inherits` | Class inheritance | `class Admin(User)` → `class User` |
| `uses_type` | Type annotation reference | `def foo(u: User)` → `class User` |
| `decorated_by` | Decorator relationship | `@cache` → `def cache` |

### Semantic Intelligence

StreamRAG doesn't just track syntax — it understands semantics:

- **Rename detection** — Distinguishes `function_a → function_b` renames from delete + add pairs
- **Semantic diffing** — Ignores whitespace-only and comment-only changes (no false updates)
- **ShadowAST fallback** — Recovers partial entities even from broken Python syntax
- **Confidence scoring** — Every edge gets `high` / `medium` / `low` confidence based on resolution certainty

<br/>

## 🔌 Hook Integration

StreamRAG plugs into Claude Code via four hooks that work transparently:

| Hook | When | What It Does |
|------|------|-------------|
| **PostToolUse** `Edit` `Write` `MultiEdit` | Every file edit | Incremental graph update, proactive warnings (new cycles, dead code, breaking changes) |
| **PreToolUse** `Read` | File read | Injects entity signatures, callers grouped by file, imports, affected files into context |
| **PreToolUse** `Task` `Grep` | Explore agents, grep patterns | Auto-redirects relationship queries to the graph (saves agent spawns and grep rounds) |
| **Stop** | Session end | Serializes graph summary for context preservation across compactions |

<br/>

## 🏗️ Architecture

```
streamrag/
├── bridge.py              # DeltaGraphBridge — incremental graph maintenance engine
├── graph.py               # CodeGraph — node/edge storage, traversal, cycle detection
├── extractor.py           # ASTExtractor — full Python AST entity extraction
├── models.py              # Core data models (ASTEntity, GraphNode, GraphEdge, CodeChange)
├── smart_query.py         # Natural language → command router (30+ regex patterns)
│
├── storage/
│   └── memory.py          # JSON serialization, persistence at ~/.claude/streamrag/
│
├── agent/
│   └── context_builder.py # Rich context formatting for pre-read hook injection
│
├── languages/
│   ├── base.py            # LanguageExtractor ABC
│   ├── python.py          # Python extractor (wraps ASTExtractor)
│   ├── registry.py        # ExtractorRegistry — auto-detect language by extension
│   ├── regex_base.py      # RegexExtractor ABC — shared infrastructure for non-Python
│   ├── typescript.py      # TypeScript / TSX extractor
│   ├── javascript.py      # JavaScript extractor (thin TS subclass)
│   ├── rust.py            # Rust extractor
│   ├── cpp.py             # C++ extractor
│   ├── c.py               # C extractor
│   ├── java.py            # Java extractor
│   └── builtins.py        # Per-language builtin and common-method filter sets
│
└── v2/
    ├── versioned_graph.py      # Version tracking and conflict detection
    ├── hierarchical_graph.py   # Zone-based hierarchical grouping
    ├── bounded_propagator.py   # Bounded change propagation
    ├── shadow_ast.py           # ShadowAST — partial entity recovery from broken syntax
    ├── operations.py           # Structured operation logging
    ├── debouncer.py            # Edit debouncing for rapid keystroke sequences
    ├── context_stabilizer.py   # Context stability scoring
    └── semantic_path.py        # Semantic path resolution (LEGB scoping)
```

<br/>

## 📊 Stats

<table>
<tr>
<td align="center"><h3>~6,700</h3><sub>Lines of Code</sub></td>
<td align="center"><h3>597</h3><sub>Tests Passing</sub></td>
<td align="center"><h3>&lt;0.5s</h3><sub>Full Test Suite</sub></td>
<td align="center"><h3>0</h3><sub>External Dependencies</sub></td>
<td align="center"><h3>7</h3><sub>Languages Supported</sub></td>
<td align="center"><h3>16</h3><sub>Query Commands</sub></td>
</tr>
</table>

<br/>

## 🤝 When to Use StreamRAG vs Grep

| Task | StreamRAG | Grep/Glob |
|------|:---------:|:---------:|
| "What calls this function?" | ✅ `callers <name>` | ❌ |
| "What files break if I change this?" | ✅ `impact <file>` | ❌ |
| "Show the dependency chain A → B" | ✅ `path <src> <dst>` | ❌ |
| "What does this class inherit from?" | ✅ `callees <name>` | ❌ |
| "Find dead code" | ✅ `dead` | ❌ |
| "Circular dependencies?" | ✅ `cycles` | ❌ |
| "Architecture overview" | ✅ `summary` | ❌ |
| "Find a file by name" | ❌ | ✅ `glob` |
| "Search for a string literal" | ❌ | ✅ `grep` |
| "Find a TODO comment" | ❌ | ✅ `grep` |

<br/>

## 📄 License

[MIT](LICENSE) — Built by [Krrish](https://github.com/krrish)
