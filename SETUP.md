# StreamRAG Setup Guide

## Prerequisites

- **Python 3.9+** installed and available as `python3`
- **Claude Code** CLI installed ([docs](https://docs.anthropic.com/en/docs/claude-code))

No external Python dependencies required — StreamRAG runs entirely on the Python standard library.

## Installation

### Option 1: Install from the plugin registry (recommended)

```bash
claude plugin add streamrag
```

### Option 2: Install from a local directory

If you have the source code locally:

```bash
claude plugin add /path/to/streamrag
```

For example, if you cloned this repo:

```bash
git clone https://github.com/anthropics/claude-code.git
claude plugin add ./claude-code/plugins/streamrag
```

### Verify Installation

Start a Claude Code session in any project and run:

```
/streamrag
```

You should see graph status output (0 nodes/edges if the graph hasn't been initialized yet — that's normal).

## How It Works

Once installed, StreamRAG is fully automatic. There is **nothing to configure**.

### Auto-Initialization

The first time you edit a file in a project, StreamRAG scans the project directory for supported source files (up to 200 files, 7-second timeout) and builds the initial code graph. No manual setup needed.

Supported file types: `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.rs`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.h`, `.c`, `.java`

### Incremental Updates

Every `Edit`, `Write`, `MultiEdit`, or `NotebookEdit` triggers an automatic graph update. StreamRAG computes the minimal AST diff and patches only the changed nodes and edges — no full rebuilds.

### Persistence

The graph state saves automatically to `~/.claude/streamrag/` and restores on the next session. Your code intelligence survives restarts.

## Usage

### Slash Commands

StreamRAG provides three slash commands:

| Command | Description |
|---------|-------------|
| `/streamrag` | Show graph status (nodes, edges, files tracked) |
| `/streamrag-ask <question>` | Ask natural language questions about the code |
| `/streamrag-context` | Get code relationship context for the current task |

### Natural Language Queries

Ask questions in plain English via `/streamrag-ask`:

```
/streamrag-ask what calls validate
/streamrag-ask what depends on auth.py
/streamrag-ask impact of models.py
/streamrag-ask find dead code
/streamrag-ask path from UserModel to validate
/streamrag-ask circular dependencies
/streamrag-ask summary
```

### Direct Query Commands

For precise control, use `query_graph.py` directly:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers <name>      # Who calls this?
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callees <name>      # What does this call?
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py deps <file>         # File dependencies
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py rdeps <file>        # Reverse dependencies
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact <file>       # Impact analysis
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py dead                # Dead code
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py cycles              # Circular deps
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py path <src> <dst>    # Shortest path
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py file <file>         # Entities in file
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py entity <name>       # Entity detail
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py search <regex>      # Regex search
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py exports <file>      # Module exports
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py stats               # Resolution stats
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py visualize <file>    # Dependency diagram
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py summary             # Architecture overview
```

### Name Resolution

Names are resolved progressively — you don't need to be exact:

1. **Exact match**: `callers User` finds the `User` class
2. **Suffix match**: `callers bar` finds `Foo.bar` method
3. **Qualified names**: `callers DeltaGraphBridge.process_change` for specificity
4. **Regex**: `search "test_.*"` finds all test functions

## What Happens Automatically

StreamRAG hooks into Claude Code transparently via four hooks:

| Hook | Trigger | What It Does |
|------|---------|--------------|
| **PostToolUse** | Every file edit | Updates the graph, warns about new cycles/dead code/breaking changes |
| **PreToolUse Read** | Every file read | Injects entity signatures, callers, imports, and affected files as context |
| **PreToolUse Task/Grep** | Explore agents and grep | Auto-redirects relationship queries to the graph instead of spawning agents |
| **Stop** | Session end / compaction | Serializes a graph summary so knowledge survives context compaction |

You don't need to invoke any of these — they run automatically.

## Manual Initialization (optional)

If you want to pre-build the graph before making edits (e.g., for a large project):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/init_graph.py /path/to/your/project
```

To dump the full graph state:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dump_graph.py
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dump_graph.py --json    # Raw JSON output
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dump_graph.py --stats   # Detailed resolution stats
```

## Graph Analyzer Agent

StreamRAG includes a specialized agent for architectural analysis. It is available as a subagent type in Claude Code sessions where the plugin is active. It can analyze circular dependencies, high fan-out functions, isolated components, and refactoring opportunities.

## Troubleshooting

### "No StreamRAG graph found"

The graph hasn't been initialized yet. Edit any supported source file and the graph will auto-initialize, or run `init_graph.py` manually.

### Graph seems stale or empty

The graph persists at `~/.claude/streamrag/`. To force a rebuild:

```bash
# Remove the cached state
rm -rf ~/.claude/streamrag/

# Re-initialize
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/init_graph.py /path/to/your/project
```

### Python version issues

StreamRAG requires Python 3.9+ (uses `ast.dump` keyword args and `end_lineno`). Check your version:

```bash
python3 --version
```

### Plugin not loading

Verify it's installed:

```bash
claude plugin list
```

If not listed, re-add it:

```bash
claude plugin add streamrag
```

## Running Tests (for contributors)

```bash
cd plugins/streamrag
pip install -e ".[dev]"
python -m pytest tests/ -q
```

All 597 tests should pass in under 0.5 seconds.

## Uninstalling

```bash
claude plugin remove streamrag
```

To also remove persisted graph data:

```bash
rm -rf ~/.claude/streamrag/
```
