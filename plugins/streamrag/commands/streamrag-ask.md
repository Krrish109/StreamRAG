---
description: Ask natural language questions about the code graph
allowed-tools: ["Bash"]
---

# StreamRAG Ask

Ask natural language questions about code relationships using the StreamRAG graph.

## Instructions

Run the query with the user's question:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/query_graph.py ask "<question>"
```

## Example Questions

- "what calls process_change"
- "what depends on bridge.py"
- "impact of models.py"
- "find dead code"
- "path from DeltaGraphBridge to LiquidGraph"
- "search test_.*"
- "summary"
- "visualize bridge.py"
- "exports models.py"
- "circular dependencies"
