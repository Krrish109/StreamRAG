"""Java language extractor using regex-based parsing."""

import re
from typing import Dict, FrozenSet, List, Tuple

from streamrag.languages.builtins import JAVA_BUILTINS, JAVA_COMMON_METHODS
from streamrag.languages.regex_base import RegexExtractor


class JavaExtractor(RegexExtractor):
    """Extract code entities from Java source."""

    @property
    def language_id(self) -> str:
        return "java"

    @property
    def supported_extensions(self) -> List[str]:
        return [".java"]

    def can_handle(self, file_path: str) -> bool:
        return file_path.endswith(".java")

    # ── Comment/string stripping ────────────────────────────────────────

    _JAVA_STRIP_PATTERN = re.compile(
        r'(?:'
        r'//[^\n]*'               # line comment
        r'|/\*[\s\S]*?\*/'        # block comment (includes javadoc)
        r"|'(?:[^'\\]|\\.)*'"     # char literal
        r'|"(?:[^"\\]|\\.)*"'     # string literal
        r'|"""[\s\S]*?"""'         # text blocks (Java 13+)
        r')',
        re.MULTILINE,
    )

    def _strip_comments_and_strings(self, source: str) -> str:
        def _replace(m: re.Match) -> str:
            return re.sub(r'[^\n]', ' ', m.group(0))
        return self._JAVA_STRIP_PATTERN.sub(_replace, source)

    # ── Declaration patterns ────────────────────────────────────────────

    _MODIFIERS = r'(?:(?:public|private|protected|static|final|abstract|synchronized|native|strictfp|sealed|non-sealed|default)\s+)*'

    _CLASS_PATTERN = re.compile(
        _MODIFIERS +
        r'class\s+(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?'
        r'(?:\s+extends\s+(?P<inherits>[A-Za-z_]\w*(?:\s*<[^>]*>)?))?'
        r'(?:\s+implements\s+[A-Za-z_][\w.,<>\s]*)?\s*\{',
        re.MULTILINE,
    )

    _INTERFACE_PATTERN = re.compile(
        _MODIFIERS +
        r'interface\s+(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?'
        r'(?:\s+extends\s+(?P<inherits>[A-Za-z_][\w.,<>\s]*))?'
        r'\s*\{',
        re.MULTILINE,
    )

    _ENUM_PATTERN = re.compile(
        _MODIFIERS +
        r'enum\s+(?P<name>[A-Z]\w*)\s*'
        r'(?:\s+implements\s+(?P<inherits>[A-Za-z_][\w.,<>\s]*))?'
        r'\s*\{',
        re.MULTILINE,
    )

    _RECORD_PATTERN = re.compile(
        _MODIFIERS +
        r'record\s+(?P<name>[A-Z]\w*)\s*(?:<[^>]*>)?\s*\([^)]*\)'
        r'(?:\s+implements\s+(?P<inherits>[A-Za-z_][\w.,<>\s]*))?'
        r'\s*\{',
        re.MULTILINE,
    )

    _ANNOTATION_TYPE_PATTERN = re.compile(
        _MODIFIERS +
        r'@interface\s+(?P<name>[A-Z]\w*)\s*\{',
        re.MULTILINE,
    )

    _METHOD_PATTERN = re.compile(
        _MODIFIERS +
        r'(?:<[^>]*>\s+)?'  # generic type params
        r'(?:[\w<>\[\],.\s]+?\s+)'  # return type
        r'(?P<name>[a-z_]\w*)\s*\([^)]*\)\s*'
        r'(?:throws\s+[\w.,\s]+)?\s*\{',
        re.MULTILINE,
    )

    _CONSTRUCTOR_PATTERN = re.compile(
        _MODIFIERS +
        r'(?P<name>[A-Z]\w*)\s*\([^)]*\)\s*'
        r'(?:throws\s+[\w.,\s]+)?\s*\{',
        re.MULTILINE,
    )

    def _get_declaration_patterns(self) -> Dict[str, List[re.Pattern]]:
        return {
            "function": [self._METHOD_PATTERN, self._CONSTRUCTOR_PATTERN],
            "class": [self._CLASS_PATTERN, self._INTERFACE_PATTERN,
                       self._ENUM_PATTERN, self._RECORD_PATTERN,
                       self._ANNOTATION_TYPE_PATTERN],
        }

    # ── Inheritance extraction ──────────────────────────────────────────

    def _extract_inherits(self, match: re.Match) -> List[str]:
        try:
            inherits_str = match.group("inherits")
        except IndexError:
            return []
        if not inherits_str:
            return []
        bases = []
        for base in inherits_str.split(","):
            base = base.strip()
            base = re.sub(r'<[^>]*>', '', base).strip()
            if base and base[0].isupper() and base not in JAVA_BUILTINS:
                bases.append(base)
        return bases

    # ── Import patterns ─────────────────────────────────────────────────

    _IMPORT_PATTERN = re.compile(
        r'import\s+(?:static\s+)?(?P<path>[\w.]+)\.(?P<name>[A-Za-z_]\w*|\*)\s*;',
        re.MULTILINE,
    )

    def _get_import_patterns(self) -> List[re.Pattern]:
        return [self._IMPORT_PATTERN]

    def _parse_import_match(self, match: re.Match) -> List[Tuple[str, str]]:
        path = match.group("path")
        name = match.group("name")
        return [(path, name)]

    # ── Annotation decorators ───────────────────────────────────────────

    _ANNOTATION_PATTERN = re.compile(r'@(\w+(?:\.\w+)*)')

    def _extract_decorators(self, lines: List[str], decl_line: int) -> List[str]:
        """Extract Java annotations from lines preceding a declaration."""
        decorators = []
        i = decl_line - 1
        while i >= 0:
            line = lines[i].strip()
            m = self._ANNOTATION_PATTERN.match(line)
            if m:
                name = m.group(1)
                if name not in ("Override", "Deprecated", "SuppressWarnings",
                                "FunctionalInterface", "SafeVarargs"):
                    decorators.append(name)
                i -= 1
            elif not line:
                i -= 1
            else:
                break
        decorators.reverse()
        return decorators

    # ── Type reference extraction ───────────────────────────────────────

    _TYPE_REF_PATTERN = re.compile(r'(?::\s*|<\s*|,\s*)([A-Z][A-Za-z0-9_]*)')

    _JAVA_TYPE_BUILTINS = frozenset({
        "String", "Integer", "Long", "Double", "Float", "Boolean",
        "Character", "Byte", "Short", "Object", "Class", "Enum",
        "List", "Map", "Set", "Collection", "Iterable", "Iterator",
        "Optional", "Stream", "Comparable", "Serializable", "Cloneable",
        "Runnable", "Callable", "Future", "CompletableFuture",
        "Consumer", "Supplier", "Function", "Predicate", "BiFunction",
        "Exception", "RuntimeException", "Error", "Throwable",
        "Override", "Deprecated",
        "T", "K", "V", "E", "R",  # Common generic params
    })

    def _extract_type_refs_from_text(self, text: str) -> List[str]:
        refs = []
        seen = set()
        for m in self._TYPE_REF_PATTERN.finditer(text):
            name = m.group(1)
            if name not in seen and name not in self._JAVA_TYPE_BUILTINS and name not in JAVA_BUILTINS:
                seen.add(name)
                refs.append(name)
        return refs

    # ── Builtin filters ─────────────────────────────────────────────────

    def _get_builtin_names(self) -> FrozenSet[str]:
        return JAVA_BUILTINS

    def _get_common_methods(self) -> FrozenSet[str]:
        return JAVA_COMMON_METHODS
