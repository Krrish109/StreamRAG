"""TypeScript language extractor using regex-based parsing."""

import re
from typing import Dict, FrozenSet, List, Tuple

from streamrag.languages.builtins import TS_BUILTINS, TS_COMMON_METHODS, TS_TYPE_BUILTINS
from streamrag.languages.regex_base import RegexExtractor


class TypeScriptExtractor(RegexExtractor):
    """Extract code entities from TypeScript/TSX source."""

    @property
    def language_id(self) -> str:
        return "typescript"

    @property
    def supported_extensions(self) -> List[str]:
        return [".ts", ".tsx"]

    def can_handle(self, file_path: str) -> bool:
        return any(file_path.endswith(ext) for ext in self.supported_extensions)

    # ── Declaration patterns ────────────────────────────────────────────

    _FUNC_PATTERN = re.compile(
        r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s+'
        r'(?P<name>[A-Za-z_$]\w*)\s*(?:<[^>]*>)?\s*\(',
        re.MULTILINE,
    )

    _ARROW_PATTERN = re.compile(
        r'(?:export\s+)?(?:const|let|var)\s+'
        r'(?P<name>[A-Za-z_$]\w*)\s*'
        r'(?::\s*[^=]+?)?\s*=\s*(?:async\s+)?'
        r'(?:\([^)]*\)|[A-Za-z_$]\w*)\s*(?::\s*[^=]*?)?\s*=>',
        re.MULTILINE,
    )

    _CLASS_PATTERN = re.compile(
        r'(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+'
        r'(?P<name>[A-Za-z_$]\w*)\s*(?:<[^>]*>)?'
        r'(?:\s+extends\s+(?P<inherits>[A-Za-z_$][\w.]*(?:\s*<[^>]*>)?'
        r'(?:\s*,\s*[A-Za-z_$][\w.]*(?:\s*<[^>]*>)?)*))?'
        r'(?:\s+implements\s+[^{]*?)?\s*\{',
        re.MULTILINE,
    )

    _INTERFACE_PATTERN = re.compile(
        r'(?:export\s+)?(?:default\s+)?interface\s+'
        r'(?P<name>[A-Za-z_$]\w*)\s*(?:<[^>]*>)?'
        r'(?:\s+extends\s+(?P<inherits>[A-Za-z_$][\w.]*(?:\s*<[^>]*>)?'
        r'(?:\s*,\s*[A-Za-z_$][\w.]*(?:\s*<[^>]*>)?)*))?'
        r'\s*\{',
        re.MULTILINE,
    )

    _ENUM_PATTERN = re.compile(
        r'(?:export\s+)?(?:const\s+)?enum\s+'
        r'(?P<name>[A-Za-z_$]\w*)\s*\{',
        re.MULTILINE,
    )

    _TYPE_ALIAS_PATTERN = re.compile(
        r'(?:export\s+)?type\s+'
        r'(?P<name>[A-Za-z_$]\w*)\s*(?:<[^>]*>)?\s*=',
        re.MULTILINE,
    )

    _METHOD_PATTERN = re.compile(
        r'^\s+(?:public\s+|private\s+|protected\s+)?'
        r'(?:static\s+)?(?:readonly\s+)?(?:async\s+)?(?:get\s+|set\s+)?'
        r'(?P<name>[A-Za-z_$]\w*)\s*(?:<[^>]*>)?\s*\(',
        re.MULTILINE,
    )

    def _get_declaration_patterns(self) -> Dict[str, List[re.Pattern]]:
        return {
            "function": [self._FUNC_PATTERN, self._ARROW_PATTERN, self._METHOD_PATTERN],
            "class": [self._CLASS_PATTERN, self._INTERFACE_PATTERN, self._ENUM_PATTERN],
            "variable": [self._TYPE_ALIAS_PATTERN],
        }

    # ── Import patterns ─────────────────────────────────────────────────

    _IMPORT_NAMED = re.compile(
        r'import\s+\{([^}]+)\}\s+from\s+[\'"]([^\'"]+)[\'"]',
        re.MULTILINE,
    )
    _IMPORT_DEFAULT = re.compile(
        r'import\s+([A-Za-z_$]\w*)\s+from\s+[\'"]([^\'"]+)[\'"]',
        re.MULTILINE,
    )
    _IMPORT_STAR = re.compile(
        r'import\s+\*\s+as\s+([A-Za-z_$]\w*)\s+from\s+[\'"]([^\'"]+)[\'"]',
        re.MULTILINE,
    )
    _REQUIRE = re.compile(
        r'(?:const|let|var)\s+(?:\{([^}]+)\}|([A-Za-z_$]\w*))\s*=\s*require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        re.MULTILINE,
    )

    def _get_import_patterns(self) -> List[re.Pattern]:
        return [self._IMPORT_NAMED, self._IMPORT_DEFAULT, self._IMPORT_STAR, self._REQUIRE]

    def _parse_import_match(self, match: re.Match) -> List[Tuple[str, str]]:
        pattern = match.re
        if pattern is self._IMPORT_NAMED:
            names_str = match.group(1)
            module = match.group(2)
            pairs = []
            for part in names_str.split(","):
                part = part.strip()
                if not part:
                    continue
                # Handle "Name as Alias"
                if " as " in part:
                    _original, alias = part.split(" as ", 1)
                    pairs.append((module, alias.strip()))
                else:
                    pairs.append((module, part))
            return pairs
        elif pattern is self._IMPORT_DEFAULT:
            return [(match.group(2), match.group(1))]
        elif pattern is self._IMPORT_STAR:
            return [(match.group(2), match.group(1))]
        elif pattern is self._REQUIRE:
            destructured = match.group(1)
            default_name = match.group(2)
            module = match.group(3)
            if destructured:
                pairs = []
                for part in destructured.split(","):
                    part = part.strip()
                    if part:
                        if " as " in part:
                            _orig, alias = part.split(" as ", 1)
                            pairs.append((module, alias.strip()))
                        else:
                            pairs.append((module, part))
                return pairs
            elif default_name:
                return [(module, default_name)]
        return []

    # ── Builtin filters ─────────────────────────────────────────────────

    def _get_builtin_names(self) -> FrozenSet[str]:
        return TS_BUILTINS

    def _get_common_methods(self) -> FrozenSet[str]:
        return TS_COMMON_METHODS

    # ── Type reference extraction ───────────────────────────────────────

    _TYPE_REF_PATTERN = re.compile(r':\s*([A-Z][A-Za-z0-9_]*)')
    _GENERIC_REF_PATTERN = re.compile(r'<\s*([A-Z][A-Za-z0-9_]*)')

    def _extract_type_refs_from_text(self, text: str) -> List[str]:
        refs = []
        seen = set()
        for pattern in (self._TYPE_REF_PATTERN, self._GENERIC_REF_PATTERN):
            for m in pattern.finditer(text):
                name = m.group(1)
                if name not in seen and name not in TS_TYPE_BUILTINS:
                    seen.add(name)
                    refs.append(name)
        return refs

    # ── JSX component extraction ────────────────────────────────────────

    _JSX_PATTERN = re.compile(r'<\s*([A-Z][A-Za-z0-9_]*)')

    def _extract_jsx_components(self, body: str) -> List[str]:
        components = []
        seen = set()
        for m in self._JSX_PATTERN.finditer(body):
            name = m.group(1)
            if name not in seen and name not in TS_BUILTINS and name not in TS_TYPE_BUILTINS:
                seen.add(name)
                components.append(name)
        return components
