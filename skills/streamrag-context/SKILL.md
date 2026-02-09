---
name: StreamRAG Context
description: Provides code relationship context from the StreamRAG incremental code graph. Use when asked about code dependencies, what calls a function, affected files, impact analysis, or when working with complex multi-file changes.
version: 0.1.0
---

# StreamRAG Context Skill

StreamRAG maintains a real-time code dependency graph that tracks functions, classes, variables, imports, and their relationships across files.

## When to Use This Skill

- "What calls this function?"
- "What files would be affected if I change X?"
- "Show me the dependencies of this module"
- "What's the call graph for this feature?"
- "Impact analysis for changing this API"
- "Find dead code"
- "Are there circular dependencies?"
- "What does this module export?"

## Quick Reference

| User asks... | Run this |
|---|---|
| "What calls X?" / "Who uses X?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers X` |
| "What does X call?" / "What does X depend on?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callees X` |
| "What files does F import?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py deps F` |
| "What files depend on F?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py rdeps F` |
| "What entities are in file F?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py file F` |
| "Show me details about X" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py entity X` |
| "What would break if I change F?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact F` |
| "Is there dead code?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py dead` |
| "Path from A to B?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py path A B` |
| "Find entities matching pattern" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py search PATTERN` |
| "Circular dependencies?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py cycles` |
| "What does F export?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py exports F` |
| "Graph stats?" | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py stats` |

## Auto-Detect Mode

When unsure which query to use, pick the closest subcommand:

```bash
# "what calls validate" -> callers
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers validate

# "impact of auth.py" -> impact
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact auth.py

# "find dead code" -> dead
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py dead
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

## Graph Status

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dump_graph.py
```

## Available Information

The graph tracks:
- **Functions**: definitions, calls, parameter lists, type annotations
- **Classes**: definitions, inheritance, methods
- **Variables**: module-level assignments, `__all__` exports
- **Imports**: per-name import tracking with edge materialization
- **Edges**: calls, imports, inherits, uses, uses_type, decorated_by

## Capabilities

- Cross-file dependency tracking (which files depend on which)
- Type annotation tracking (`uses_type` edges from annotations to classes)
- `__all__` export tracking (what a module publicly exports)
- Rename detection (detects renames vs delete+add)
- Semantic change detection (ignores whitespace/comment-only changes)
- Impact analysis (finds all transitively affected files)
- Dead code detection (functions/classes with zero incoming edges)
- Cycle detection (circular file-level dependencies)
- Auto-initialization (graph populates on first use)
- Ghost node cleanup (deleted files automatically cleaned)
- Incremental updates (only processes changed entities, not full rebuilds)
