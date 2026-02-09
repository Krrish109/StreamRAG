"""C++ language extractor using regex-based parsing."""

import re
from typing import Dict, FrozenSet, List, Tuple

from streamrag.languages.builtins import CPP_BUILTINS, CPP_COMMON_METHODS
from streamrag.languages.regex_base import RegexExtractor


class CppExtractor(RegexExtractor):
    """Extract code entities from C++ source."""

    @property
    def language_id(self) -> str:
        return "cpp"

    @property
    def supported_extensions(self) -> List[str]:
        return [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"]

    def can_handle(self, file_path: str) -> bool:
        return any(file_path.endswith(ext) for ext in self.supported_extensions)

    # ── Comment/string stripping (C++ has no backtick strings) ──────────

    _CPP_STRIP_PATTERN = re.compile(
        r'(?:'
        r'//[^\n]*'               # line comment
        r'|/\*[\s\S]*?\*/'        # block comment
        r"|'(?:[^'\\]|\\.)*'"     # char literal
        r'|"(?:[^"\\]|\\.)*"'     # string literal
        r'|R"([^(]*)\([\s\S]*?\)\1"'  # raw string R"delim(...)delim"
        r')',
        re.MULTILINE,
    )

    def _strip_comments_and_strings(self, source: str) -> str:
        def _replace(m: re.Match) -> str:
            return re.sub(r'[^\n]', ' ', m.group(0))
        return self._CPP_STRIP_PATTERN.sub(_replace, source)

    # ── Declaration patterns ────────────────────────────────────────────

    # Function: return_type name(params) { or ;
    _FUNC_PATTERN = re.compile(
        r'(?:template\s*<[^>]*>\s*)?'
        r'(?:(?:static|inline|virtual|explicit|constexpr|consteval|extern)\s+)*'
        r'(?:[\w:*&<>]+\s+)+?'
        r'(?P<name>[a-z_]\w*)\s*\([^)]*\)\s*'
        r'(?:const\s*)?(?:noexcept\s*(?:\([^)]*\))?\s*)?'
        r'(?:override\s*|final\s*)*'
        r'(?:\{|;)',
        re.MULTILINE,
    )

    # Constructor/destructor: ClassName(params) or ~ClassName()
    _CTOR_PATTERN = re.compile(
        r'(?:explicit\s+)?~?(?P<name>[A-Z]\w*)\s*\([^)]*\)\s*'
        r'(?::\s*[^{;]*?)?\s*\{',
        re.MULTILINE,
    )

    _CLASS_PATTERN = re.compile(
        r'(?:template\s*<[^>]*>\s*)?'
        r'class\s+(?P<name>[A-Z]\w*)\s*'
        r'(?:final\s*)?'
        r'(?::\s*(?P<inherits>(?:(?:public|private|protected)\s+)?[A-Za-z_]\w*'
        r'(?:\s*<[^>]*>)?'
        r'(?:\s*,\s*(?:(?:public|private|protected)\s+)?[A-Za-z_]\w*'
        r'(?:\s*<[^>]*>)?)*))?\s*\{',
        re.MULTILINE,
    )

    _STRUCT_PATTERN = re.compile(
        r'(?:template\s*<[^>]*>\s*)?'
        r'struct\s+(?P<name>[A-Z]\w*)\s*'
        r'(?:final\s*)?'
        r'(?::\s*(?P<inherits>(?:(?:public|private|protected)\s+)?[A-Za-z_]\w*'
        r'(?:\s*<[^>]*>)?'
        r'(?:\s*,\s*(?:(?:public|private|protected)\s+)?[A-Za-z_]\w*'
        r'(?:\s*<[^>]*>)?)*))?\s*\{',
        re.MULTILINE,
    )

    _ENUM_PATTERN = re.compile(
        r'enum\s+(?:class\s+)?(?P<name>[A-Z]\w*)\s*'
        r'(?::\s*\w+\s*)?\{',
        re.MULTILINE,
    )

    _NAMESPACE_PATTERN = re.compile(
        r'namespace\s+(?P<name>[A-Za-z_]\w*)\s*\{',
        re.MULTILINE,
    )

    _USING_ALIAS_PATTERN = re.compile(
        r'using\s+(?P<name>[A-Za-z_]\w*)\s*=',
        re.MULTILINE,
    )

    _TYPEDEF_PATTERN = re.compile(
        r'typedef\s+.*?\s+(?P<name>[A-Za-z_]\w*)\s*;',
        re.MULTILINE,
    )

    def _get_declaration_patterns(self) -> Dict[str, List[re.Pattern]]:
        return {
            "function": [self._FUNC_PATTERN, self._CTOR_PATTERN],
            "class": [self._CLASS_PATTERN, self._STRUCT_PATTERN,
                       self._ENUM_PATTERN, self._NAMESPACE_PATTERN],
            "variable": [self._USING_ALIAS_PATTERN, self._TYPEDEF_PATTERN],
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
    _USING_NS = re.compile(
        r'using\s+namespace\s+(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*;',
        re.MULTILINE,
    )

    def _get_import_patterns(self) -> List[re.Pattern]:
        return [self._INCLUDE_LOCAL, self._INCLUDE_SYSTEM, self._USING_NS]

    def _parse_import_match(self, match: re.Match) -> List[Tuple[str, str]]:
        pattern = match.re
        if pattern is self._INCLUDE_LOCAL:
            path = match.group("path")
            # Use the filename as the imported name
            name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            return [(".", path)]
        elif pattern is self._INCLUDE_SYSTEM:
            path = match.group("path")
            name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            return [("", path)]
        elif pattern is self._USING_NS:
            name = match.group("name")
            return [(name, name)]
        return []

    # ── Builtin filters ─────────────────────────────────────────────────

    def _get_builtin_names(self) -> FrozenSet[str]:
        return CPP_BUILTINS

    def _get_common_methods(self) -> FrozenSet[str]:
        return CPP_COMMON_METHODS
