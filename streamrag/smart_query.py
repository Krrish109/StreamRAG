"""Natural language query router for StreamRAG.

Maps informal questions to graph query commands using regex patterns.
"""

import re
from typing import List, Optional, Tuple


# (regex_pattern, command, arg_group_index_or_None)
# Patterns are tried in order; first match wins.
NL_PATTERNS: List[Tuple[str, str, Optional[int]]] = [
    # Callers / who calls
    (r"(?:who|what)\s+(?:calls?|invokes?|uses?)\s+(\S+)", "callers", 1),
    (r"callers?\s+(?:of\s+)?(\S+)", "callers", 1),
    (r"where\s+is\s+(\S+)\s+(?:called|used|invoked)", "callers", 1),

    # Callees / what does X call
    (r"what\s+does\s+(\S+)\s+(?:call|invoke|use|import)", "callees", 1),
    (r"callees?\s+(?:of\s+)?(\S+)", "callees", 1),
    (r"(\S+)\s+(?:calls?|depends\s+on)\s+what", "callees", 1),

    # Reverse dependencies (must be before forward deps to match "reverse deps" first)
    (r"reverse\s+dep(?:endencie)?s\s+(?:of\s+|for\s+)?(\S+)", "rdeps", 1),
    (r"what\s+depends\s+on\s+(\S+)", "rdeps", 1),
    (r"what\s+(?:files?|modules?)\s+(?:use|import|require)\s+(\S+)", "rdeps", 1),
    (r"dependents?\s+(?:of\s+)?(\S+)", "rdeps", 1),

    # Dependencies (file-level)
    (r"(?:forward\s+)?dep(?:endencie)?s\s+(?:of\s+|for\s+)?(\S+)", "deps", 1),
    (r"what\s+(?:does|files?)\s+(\S+)\s+(?:depend|import|require)", "deps", 1),

    # Impact analysis
    (r"(?:impact|affected)\s+(?:of\s+|by\s+|from\s+)?(?:(?:changes?\s+(?:to\s+|in\s+))|(?:(?:changing|modifying|editing)\s+))?(\S+)", "impact", 1),
    (r"what\s+(?:is|would\s+be)\s+affected\s+(?:by|if)\s+(?:I\s+)?(?:change|modify|edit)\s+(\S+)", "impact", 1),
    (r"what\s+\w+\s+(?:would|will|could|are|get)\s+(?:be\s+)?affected\s+(?:by|if|when)\s+(?:\w+\s+)?(?:chang(?:e|ing)|modify(?:ing)?|edit(?:ing)?)\s+(\S+)", "impact", 1),
    (r"(?:files?|modules?)\s+(?:that\s+)?(?:would|will|could|are|get)\s+(?:be\s+)?affected\s+(?:by\s+)?(?:changes?\s+(?:to|in)\s+)?(\S+)", "impact", 1),

    # Dead code
    (r"(?:dead|unused|unreachable)\s+(?:code|functions?|classes?)", "dead", None),
    (r"find\s+(?:dead|unused)\s+code", "dead", None),

    # Cycles
    (r"(?:circular|cyclic)\s+(?:dep(?:endencie)?s?|imports?)", "cycles", None),
    (r"(?:find\s+)?cycles?", "cycles", None),

    # Path
    (r"(?:path|route|chain)\s+(?:from\s+)?(\S+)\s+(?:to|->)\s+(\S+)", "path", None),
    (r"how\s+(?:does|is)\s+(\S+)\s+(?:connected|related|linked)\s+to\s+(\S+)", "path", None),

    # Search
    (r"(?:search|find|look\s+for)\s+(?:entities?\s+)?(?:matching\s+|named?\s+)?['\"]?(\S+?)['\"]?$", "search", 1),
    (r"(?:entities?|functions?|classes?)\s+(?:matching|like|named)\s+['\"]?(\S+?)['\"]?$", "search", 1),

    # Summary
    (r"(?:summary|overview|architecture|stats|statistics)", "summary", None),

    # Visualize
    (r"(?:visuali[zs]e|diagram|show\s+graph)\s*(?:of\s+)?(\S+)?", "visualize", 1),

    # Entity detail
    (r"(?:detail|info|about)\s+(?:of\s+|for\s+|on\s+)?(\S+)", "entity", 1),
    (r"(?:show|describe|explain)\s+(?:me\s+)?(?:the\s+)?(?:details?\s+(?:of|for|about)\s+)?(\S+)", "entity", 1),

    # Exports
    (r"(?:exports?|public\s+API)\s+(?:of\s+|for\s+|from\s+)?(\S+)", "exports", 1),
    (r"what\s+does\s+(\S+)\s+export", "exports", 1),
]


_STOP_WORDS = {"me", "the", "a", "an", "this", "that", "my", "your", "it", "its"}


def parse_query(query: str) -> Optional[Tuple[str, List[str]]]:
    """Parse a natural language query into a command + args.

    Returns (command_name, [args]) or None if no pattern matches.
    """
    original = query.strip().rstrip("?")
    query_lower = original.lower()

    for pattern, command, arg_group in NL_PATTERNS:
        # Match against lowercased query for case-insensitive keyword matching
        m = re.search(pattern, query_lower, re.IGNORECASE)
        if m:
            # Extract args from the ORIGINAL query to preserve entity name casing
            m_orig = re.search(pattern, original, re.IGNORECASE)
            if m_orig is None:
                m_orig = m  # fallback
            args = []
            if command == "path":
                # Path needs two args from groups 1 and 2
                if m_orig.lastindex and m_orig.lastindex >= 2:
                    args = [m_orig.group(1), m_orig.group(2)]
                else:
                    continue
            elif arg_group is not None:
                val = m_orig.group(arg_group)
                if val:
                    # Skip stop words captured as entity names
                    if val.lower() in _STOP_WORDS:
                        continue
                    args = [val]
            return (command, args)

    return None


def execute_query(bridge, query: str) -> str:
    """Execute a natural language query against the bridge.

    Returns the formatted result string.
    """
    parsed = parse_query(query)
    if parsed is None:
        return (
            f"Could not understand query: '{query}'\n\n"
            "Try questions like:\n"
            "  - 'what calls process_change'\n"
            "  - 'what depends on bridge.py'\n"
            "  - 'impact of models.py'\n"
            "  - 'find dead code'\n"
            "  - 'path from foo to bar'\n"
            "  - 'search test_.*'\n"
            "  - 'summary'\n"
            "  - 'visualize bridge.py'\n"
        )

    command, args = parsed

    # Import the command functions from query_graph
    import importlib
    import os
    import sys

    # Ensure query_graph is importable
    scripts_dir = os.path.join(
        os.environ.get("CLAUDE_PLUGIN_ROOT",
                       os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
    )
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from io import StringIO
    import contextlib

    # Capture stdout from the command
    buf = StringIO()

    try:
        # Import query_graph module
        if 'query_graph' in sys.modules:
            qg = sys.modules['query_graph']
        else:
            import query_graph as qg

        cmd_fn = qg.COMMANDS.get(command)
        if cmd_fn is None:
            # Handle summary and visualize which are new
            if command == "summary":
                return _run_summary(bridge)
            elif command == "visualize":
                return _run_visualize(bridge, args)
            return f"Unknown command: {command}"

        with contextlib.redirect_stdout(buf):
            cmd_fn(bridge, args)

        return buf.getvalue().strip()

    except Exception as e:
        return f"Error executing '{command}': {e}"


def _run_summary(bridge) -> str:
    """Generate architecture summary."""
    # Try cmd_summary from query_graph first
    from io import StringIO
    import contextlib
    import sys

    scripts_dir = os.path.join(
        os.environ.get("CLAUDE_PLUGIN_ROOT",
                       os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
    )
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    if 'query_graph' in sys.modules:
        qg = sys.modules['query_graph']
    else:
        import query_graph as qg

    if hasattr(qg, 'cmd_summary'):
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            qg.cmd_summary(bridge, [])
        return buf.getvalue().strip()

    # Fallback: basic summary
    from streamrag.agent.context_builder import format_graph_summary
    return format_graph_summary(bridge)


def _run_visualize(bridge, args) -> str:
    """Generate visualization."""
    from io import StringIO
    import contextlib
    import sys

    scripts_dir = os.path.join(
        os.environ.get("CLAUDE_PLUGIN_ROOT",
                       os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
    )
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    if 'query_graph' in sys.modules:
        qg = sys.modules['query_graph']
    else:
        import query_graph as qg

    if hasattr(qg, 'cmd_visualize'):
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            qg.cmd_visualize(bridge, args)
        return buf.getvalue().strip()

    return "Visualization not available."


# Needed for _run_summary/_run_visualize
import os
