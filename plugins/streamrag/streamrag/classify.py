"""Shared classification logic for Explore/Grep relationship query detection.

Used by both pre_explore_redirect.py (fallback path) and daemon.py (fast path)
to avoid duplicating patterns and helpers.
"""

import re
from typing import List, Optional, Tuple

try:
    from streamrag.smart_query import parse_query
except ImportError:
    parse_query = None


RELATIONSHIP_COMMANDS = {"callers", "callees", "rdeps", "deps", "impact", "dead", "cycles", "path"}

EXPLORE_PATTERNS = [
    (r"(?:find|search\s+for)\s+(?:all\s+)?(?:usages?|references?|uses?)\s+(?:of\s+)?(\S+)", "callers"),
    (r"(?:trace|follow|understand)\s+(?:the\s+)?(?:call|dependency|dep)\s+(?:chain|graph|tree)\s+(?:of\s+|for\s+|from\s+)?(\S+)", "callers"),
    (r"(?:all\s+)?files?\s+that\s+(?:import|use|call|depend\s+on)\s+(\S+)", "rdeps"),
    (r"(?:how|where)\s+is\s+(\S+)\s+(?:used|called|imported|referenced)", "callers"),
    (r"(?:impact|ripple|blast\s+radius)\s+(?:of\s+)?(?:changing|modifying|editing)\s+(\S+)", "impact"),
    (r"(?:want|going|need)\s+to\s+(?:modify|change|edit)\s+(\S+).*?(?:affect|impact)", "impact"),
    (r"(?:files?|modules?)\s+(?:would|will|could|are|get)\s+(?:be\s+)?(?:affected|impacted).*?(?:modify|change|edit)\w*\s+(\S+)", "impact"),
    (r"(?:find|detect|check\s+for)\s+(?:circular|cyclic)\s+(?:dep|import)", "cycles"),
    (r"(?:find|detect|check\s+for)\s+(?:dead|unused|orphan)\s+(?:code|function|class)", "dead"),
]

GREP_CLASSIFIERS = [
    (r"^(\w+)\s*\\?\(", "callers"),
    (r"(?:from|import)\s+(\S+)", "rdeps"),
    (r"(?:def|class)\s+(\w+)", "entity"),
]


def _clean_arg(arg: str) -> str:
    """Strip trailing punctuation from a captured argument."""
    return arg.rstrip('.,;:!?\'")')


def classify_explore_prompt(text: str) -> Optional[Tuple[str, List[str]]]:
    """Classify an Explore prompt as a relationship query.

    Returns (command, args) tuple or None.
    """
    if parse_query is not None:
        result = parse_query(text)
        if result is not None and result[0] in RELATIONSHIP_COMMANDS:
            return (result[0], [_clean_arg(a) for a in result[1]])

    text_lower = text.lower()
    for pattern, command in EXPLORE_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            args: List[str] = []
            if m.lastindex and m.lastindex >= 1:
                args = [_clean_arg(m.group(1))]
            return (command, args)

    return None


def classify_grep_pattern(pattern: str) -> Optional[Tuple[str, str]]:
    """Classify a Grep pattern as a potential relationship query.

    Returns (command, name) tuple or None.
    """
    for regex, command in GREP_CLASSIFIERS:
        m = re.match(regex, pattern)
        if m:
            name = m.group(1)
            if len(name) < 2:
                continue
            if name.upper() == name and len(name) > 2:
                continue
            return (command, name)
    return None


def build_command_str(command: str, args: list) -> str:
    """Build a StreamRAG query command string."""
    plugin_root = "${CLAUDE_PLUGIN_ROOT}"
    parts = [f"python3 {plugin_root}/scripts/query_graph.py", command]
    parts.extend(args)
    return " ".join(parts)


def command_description(command: str) -> str:
    """Human-readable description for a command."""
    return {
        "callers": "callers of", "callees": "callees of",
        "rdeps": "reverse dependencies of", "deps": "dependencies of",
        "impact": "impact of", "entity": "details about", "exports": "exports of",
    }.get(command, command)
