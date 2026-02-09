---
description: Provides code relationship context from the StreamRAG incremental code graph. Use when asked about code dependencies, what calls a function, affected files, impact analysis, or when working with complex multi-file changes.
allowed-tools: ["Bash", "Read"]
---

# StreamRAG Context

Query the StreamRAG code dependency graph for code intelligence.

## Instructions

Use `query_graph.py` subcommands to answer questions about code relationships:

```bash
# Who calls/imports/inherits this entity?
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers <name>

# What does this entity call/import/inherit?
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callees <name>

# Forward file dependencies (what does this file depend on?)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py deps <file>

# Reverse file dependencies (what depends on this file?)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py rdeps <file>

# All entities and relationships in a file
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py file <file>

# Full detail for a specific entity
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py entity <name>

# Impact analysis (what files are affected by a change?)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact <file> [name]

# Dead code detection
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py dead

# Shortest dependency path between two entities
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py path <source> <target>

# Regex entity search
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py search <regex>

# Circular file dependency detection
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py cycles

# Module exports (__all__ or top-level names)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py exports <file>

# Graph statistics and resolution metrics
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py stats

# Natural language queries (routes to the right command)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py ask "what calls process_change"

# Mermaid/DOT dependency diagrams
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py visualize <file> [--format mermaid|dot] [--type file|entity|inheritance]

# Architecture overview (key classes, entry points, hot spots)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py summary
```

## Before Modifying Code

Always run these queries first to understand impact:

1. **Find callers**: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers <entity_name>`
2. **Check impact**: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact <file_path>`

## Name Resolution

Names are resolved progressively:
1. **Exact match**: `callers User` finds the `User` class
2. **Suffix match**: `callers bar` finds `Foo.bar` method
3. **Qualified names**: `callers DeltaGraphBridge.process_change` for specificity
4. **Regex**: `search "test_.*"` finds all test functions
