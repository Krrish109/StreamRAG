"""Rust language extractor using regex-based parsing."""

import re
from typing import Dict, FrozenSet, List, Tuple

from streamrag.languages.builtins import RUST_BUILTINS, RUST_COMMON_METHODS
from streamrag.languages.regex_base import RegexExtractor


class RustExtractor(RegexExtractor):
    """Extract code entities from Rust source."""

    @property
    def language_id(self) -> str:
        return "rust"

    @property
    def supported_extensions(self) -> List[str]:
        return [".rs"]

    def can_handle(self, file_path: str) -> bool:
        return file_path.endswith(".rs")

    # ── Comment/string stripping override for Rust raw strings ──────────

    _RUST_STRIP_PATTERN = re.compile(
        r'(?:'
        r'//[^\n]*'                   # line comment
        r'|/\*[\s\S]*?\*/'            # block comment
        r'|r#+"[\s\S]*?"#+\s'         # raw string r#"..."#
        r'|r"[^"]*"'                  # raw string r"..."
        r"|b?'(?:[^'\\]|\\.)*'"       # char literal / byte char
        r'|b?"(?:[^"\\]|\\.)*"'       # string / byte string
        r')',
        re.MULTILINE,
    )

    def _strip_comments_and_strings(self, source: str) -> str:
        def _replace(m: re.Match) -> str:
            return re.sub(r'[^\n]', ' ', m.group(0))
        return self._RUST_STRIP_PATTERN.sub(_replace, source)

    # ── Declaration patterns ────────────────────────────────────────────

    _FN_PATTERN = re.compile(
        r'(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+"[^"]*"\s+)?'
        r'fn\s+(?P<name>[a-z_]\w*)\s*(?:<[^>]*>)?\s*\(',
        re.MULTILINE,
    )

    _STRUCT_PATTERN = re.compile(
        r'(?:pub(?:\([^)]*\))?\s+)?struct\s+'
        r'(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?',
        re.MULTILINE,
    )

    _ENUM_PATTERN = re.compile(
        r'(?:pub(?:\([^)]*\))?\s+)?enum\s+'
        r'(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?',
        re.MULTILINE,
    )

    _TRAIT_PATTERN = re.compile(
        r'(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?trait\s+'
        r'(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?'
        r'(?:\s*:\s*(?P<inherits>[A-Za-z_]\w*(?:\s*\+\s*[A-Za-z_]\w*)*))?',
        re.MULTILINE,
    )

    _IMPL_PATTERN = re.compile(
        r'impl\s*(?:<[^>]*>)?\s+'
        r'(?:(?P<trait>[A-Z]\w*)\s+for\s+)?'
        r'(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?\s*\{',
        re.MULTILINE,
    )

    _TYPE_ALIAS_PATTERN = re.compile(
        r'(?:pub(?:\([^)]*\))?\s+)?type\s+'
        r'(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?\s*=',
        re.MULTILINE,
    )

    _CONST_STATIC_PATTERN = re.compile(
        r'(?:pub(?:\([^)]*\))?\s+)?(?:const|static)\s+'
        r'(?P<name>[A-Z_]\w*)\s*:',
        re.MULTILINE,
    )

    _MOD_PATTERN = re.compile(
        r'(?:pub(?:\([^)]*\))?\s+)?mod\s+'
        r'(?P<name>[a-z_]\w*)\s*[{;]',
        re.MULTILINE,
    )

    _MACRO_RULES_PATTERN = re.compile(
        r'macro_rules!\s+(?P<name>[a-z_]\w*)',
        re.MULTILINE,
    )

    def _get_declaration_patterns(self) -> Dict[str, List[re.Pattern]]:
        return {
            "function": [self._FN_PATTERN, self._MACRO_RULES_PATTERN],
            "class": [self._STRUCT_PATTERN, self._ENUM_PATTERN,
                       self._TRAIT_PATTERN, self._IMPL_PATTERN],
            "variable": [self._TYPE_ALIAS_PATTERN, self._CONST_STATIC_PATTERN],
            "module_code": [self._MOD_PATTERN],
        }

    # ── Inheritance extraction for traits and impl blocks ───────────────

    def _extract_inherits(self, match: re.Match) -> List[str]:
        """Handle trait bounds (`:` separated by `+`) and impl-for."""
        # Check for impl-for pattern
        try:
            trait = match.group("trait")
            if trait:
                return [trait]
        except IndexError:
            pass

        # Check for trait bounds
        try:
            inherits_str = match.group("inherits")
        except IndexError:
            return []
        if not inherits_str:
            return []

        bases = []
        for part in inherits_str.split("+"):
            name = part.strip()
            name = re.sub(r'<[^>]*>', '', name).strip()
            if name and name[0].isupper() and name not in RUST_BUILTINS:
                bases.append(name)
        return bases

    # ── Import patterns ─────────────────────────────────────────────────

    _USE_SIMPLE = re.compile(
        r'use\s+(?:(?:crate|super|self)::)?(?P<path>[\w:]+)::(?P<name>[A-Za-z_]\w*)\s*;',
        re.MULTILINE,
    )
    _USE_BRACED = re.compile(
        r'use\s+(?:(?:crate|super|self)::)?(?P<path>[\w:]+)::\{(?P<names>[^}]+)\}\s*;',
        re.MULTILINE,
    )
    _USE_GLOB = re.compile(
        r'use\s+(?:(?:crate|super|self)::)?(?P<path>[\w:]+)::\*\s*;',
        re.MULTILINE,
    )
    _USE_RENAME = re.compile(
        r'use\s+(?:(?:crate|super|self)::)?(?P<path>[\w:]+)::(?P<orig>[A-Za-z_]\w*)\s+as\s+(?P<name>[A-Za-z_]\w*)\s*;',
        re.MULTILINE,
    )

    def _get_import_patterns(self) -> List[re.Pattern]:
        return [self._USE_RENAME, self._USE_BRACED, self._USE_SIMPLE, self._USE_GLOB]

    def _parse_import_match(self, match: re.Match) -> List[Tuple[str, str]]:
        pattern = match.re
        if pattern is self._USE_RENAME:
            path = match.group("path")
            name = match.group("name")
            return [(path, name)]
        elif pattern is self._USE_SIMPLE:
            path = match.group("path")
            name = match.group("name")
            return [(path, name)]
        elif pattern is self._USE_BRACED:
            path = match.group("path")
            names_str = match.group("names")
            pairs = []
            for part in names_str.split(","):
                part = part.strip()
                if not part:
                    continue
                if " as " in part:
                    _orig, alias = part.split(" as ", 1)
                    pairs.append((path, alias.strip()))
                else:
                    pairs.append((path, part))
            return pairs
        elif pattern is self._USE_GLOB:
            path = match.group("path")
            return [(path, "*")]
        return []

    # ── Attributes as decorators ────────────────────────────────────────

    _ATTRIBUTE_PATTERN = re.compile(r'#\[(\w+(?:::\w+)*)')

    def _extract_decorators(self, lines: List[str], decl_line: int) -> List[str]:
        """Extract Rust attributes #[...] from lines preceding a declaration."""
        decorators = []
        i = decl_line - 1
        while i >= 0:
            line = lines[i].strip()
            if line.startswith("#[") or line.startswith("#!["):
                m = self._ATTRIBUTE_PATTERN.search(line)
                if m:
                    decorators.append(m.group(1))
                i -= 1
            elif not line:
                i -= 1
            else:
                break
        decorators.reverse()
        return decorators

    # ── Builtin filters ─────────────────────────────────────────────────

    def _get_builtin_names(self) -> FrozenSet[str]:
        return RUST_BUILTINS

    def _get_common_methods(self) -> FrozenSet[str]:
        return RUST_COMMON_METHODS
