---
description: Show StreamRAG code graph status, node/edge counts, and file coverage
allowed-tools: ["Bash", "Read"]
---

# StreamRAG Status

Show the current state of the StreamRAG code graph for this session.

## Instructions

1. Run the dump script to get current graph state:
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dump_graph.py
   ```

2. If no graph exists yet, the graph will auto-initialize on the next file edit. You can also manually initialize:
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/init_graph.py <project_dir>
   ```

3. Display a summary of:
   - Total nodes and edges
   - Files tracked
   - Entity type breakdown (functions, classes, variables, imports)
   - Cross-file dependencies
   - Graph hash (for consistency checking)

## Query Commands

Use `query_graph.py` for code intelligence queries:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callers <name>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py callees <name>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py deps <file>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py rdeps <file>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py entity <name>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py file <file>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py impact <file> [name]
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py dead
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py cycles
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py search <regex>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py path <source> <target>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py exports <file>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py stats
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py ask "<question>"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py visualize <file> [--format mermaid|dot] [--type file|entity|inheritance]
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py summary
```
