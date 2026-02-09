"""C language extractor using regex-based parsing.

Simplified version of the C++ extractor: functions, structs, enums,
unions, typedefs, #define macros. No classes, namespaces, or templates.
"""

import re
from typing import Dict, FrozenSet, List, Tuple

from streamrag.languages.builtins import C_BUILTINS, C_COMMON_METHODS
from streamrag.languages.regex_base import RegexExtractor


class CExtractor(RegexExtractor):
    """Extract code entities from C source."""

    @property
    def language_id(self) -> str:
        return "c"

    @property
    def supported_extensions(self) -> List[str]:
        return [".c"]

    def can_handle(self, file_path: str) -> bool:
        return file_path.endswith(".c")

    # ── Comment/string stripping ────────────────────────────────────────

    _C_STRIP_PATTERN = re.compile(
        r'(?:'
        r'//[^\n]*'               # line comment
        r'|/\*[\s\S]*?\*/'        # block comment
        r"|'(?:[^'\\]|\\.)*'"     # char literal
        r'|"(?:[^"\\]|\\.)*"'     # string literal
        r')',
        re.MULTILINE,
    )

    def _strip_comments_and_strings(self, source: str) -> str:
        def _replace(m: re.Match) -> str:
            return re.sub(r'[^\n]', ' ', m.group(0))
        return self._C_STRIP_PATTERN.sub(_replace, source)

    # ── Declaration patterns ────────────────────────────────────────────

    _FUNC_PATTERN = re.compile(
        r'(?:(?:static|inline|extern)\s+)*'
        r'(?:[\w*]+\s+)+?'
        r'(?P<name>[a-z_]\w*)\s*\([^)]*\)\s*\{',
        re.MULTILINE,
    )

    _STRUCT_PATTERN = re.compile(
        r'(?:typedef\s+)?struct\s+(?P<name>[A-Za-z_]\w*)\s*\{',
        re.MULTILINE,
    )

    _ENUM_PATTERN = re.compile(
        r'(?:typedef\s+)?enum\s+(?P<name>[A-Za-z_]\w*)\s*\{',
        re.MULTILINE,
    )

    _UNION_PATTERN = re.compile(
        r'(?:typedef\s+)?union\s+(?P<name>[A-Za-z_]\w*)\s*\{',
        re.MULTILINE,
    )

    _TYPEDEF_PATTERN = re.compile(
        r'typedef\s+.*?\s+(?P<name>[A-Za-z_]\w*)\s*;',
        re.MULTILINE,
    )

    _DEFINE_PATTERN = re.compile(
        r'#\s*define\s+(?P<name>[A-Za-z_]\w*)(?:\s*\([^)]*\))?',
        re.MULTILINE,
    )

    def _get_declaration_patterns(self) -> Dict[str, List[re.Pattern]]:
        return {
            "function": [self._FUNC_PATTERN],
            "class": [self._STRUCT_PATTERN, self._ENUM_PATTERN, self._UNION_PATTERN],
            "variable": [self._TYPEDEF_PATTERN, self._DEFINE_PATTERN],
        }

    # ── Import patterns ─────────────────────────────────────────────────

    _INCLUDE_LOCAL = re.compile(
        r'#\s*include\s+"(?P<path>[^"]+)"',
        re.MULTILINE,
    )
    _INCLUDE_SYSTEM = re.compile(
        r'#\s*include\s+<(?P<path>[^>]+)>',
        re.MULTILINE,
    )

    def _get_import_patterns(self) -> List[re.Pattern]:
        return [self._INCLUDE_LOCAL, self._INCLUDE_SYSTEM]

    def _parse_import_match(self, match: re.Match) -> List[Tuple[str, str]]:
        pattern = match.re
        path = match.group("path")
        if pattern is self._INCLUDE_LOCAL:
            return [(".", path)]
        elif pattern is self._INCLUDE_SYSTEM:
            return [("", path)]
        return []

    # ── Builtin filters ─────────────────────────────────────────────────

    def _get_builtin_names(self) -> FrozenSet[str]:
        return C_BUILTINS

    def _get_common_methods(self) -> FrozenSet[str]:
        return C_COMMON_METHODS
