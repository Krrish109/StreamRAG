"""Shared base class for regex-based language extractors.

Provides comment/string stripping, brace-counting, call extraction,
hash computation, and scope tracking. Language-specific subclasses
provide declaration patterns, import patterns, and builtin sets.
"""

import hashlib
import re
from abc import abstractmethod
from typing import Dict, FrozenSet, List, Optional, Tuple

from streamrag.languages.base import LanguageExtractor
from streamrag.models import ASTEntity


def _sha256_short(text: str, length: int = 12) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


class RegexExtractor(LanguageExtractor):
    """Abstract regex-based extractor.

    Subclasses must implement:
    - _get_declaration_patterns() -> Dict[str, List[re.Pattern]]
    - _get_import_patterns() -> List[re.Pattern]
    - _parse_import_match(match) -> List[Tuple[str, str]]
    - _get_builtin_names() -> frozenset
    - _get_common_methods() -> frozenset
    """

    # ── Comment / string stripping ──────────────────────────────────────

    # Regex to match comments and strings while preserving line structure.
    # Order matters: longest match first to avoid partial matches.
    _STRIP_PATTERN = re.compile(
        r'(?:'
        r'//[^\n]*'               # single-line comment //
        r'|/\*[\s\S]*?\*/'        # block comment /* ... */
        r"|'''[\s\S]*?'''"        # Python triple-single
        r'|"""[\s\S]*?"""'        # Python triple-double
        r"|'(?:[^'\\]|\\.)*'"     # single-quoted string
        r'|"(?:[^"\\]|\\.)*"'     # double-quoted string
        r'|`(?:[^`\\]|\\.)*`'     # backtick template literal
        r')',
        re.MULTILINE,
    )

    def _strip_comments_and_strings(self, source: str) -> str:
        """Replace comments and string contents with spaces, preserving line numbers."""
        def _replace(m: re.Match) -> str:
            text = m.group(0)
            # Preserve newlines so line numbers stay correct
            return re.sub(r'[^\n]', ' ', text)
        return self._STRIP_PATTERN.sub(_replace, source)

    # ── Brace counting ──────────────────────────────────────────────────

    def _find_body_end(self, stripped_lines: List[str], start_line: int) -> int:
        """Find the closing brace line for a declaration starting at start_line.

        start_line is 0-indexed into stripped_lines.
        Returns 0-indexed line number of closing brace.
        """
        depth = 0
        found_open = False
        for i in range(start_line, len(stripped_lines)):
            line = stripped_lines[i]
            for ch in line:
                if ch == '{':
                    depth += 1
                    found_open = True
                elif ch == '}':
                    depth -= 1
                    if found_open and depth == 0:
                        return i
        # No closing brace found — return last line
        return len(stripped_lines) - 1

    # ── Call extraction ─────────────────────────────────────────────────

    _CALL_PATTERN = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
    _QUALIFIED_CALL_PATTERN = re.compile(r'\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(')

    def _extract_calls_from_body(self, body: str) -> List[str]:
        """Extract function/method calls from a body of code."""
        builtins = self._get_builtin_names()
        common = self._get_common_methods()
        calls = []
        seen = set()
        for m in self._QUALIFIED_CALL_PATTERN.finditer(body):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            # Filter builtins and common methods
            bare = name.split(".")[-1] if "." in name else name
            if bare in builtins or name in builtins:
                continue
            if "." not in name and bare in common:
                continue
            # For qualified names, only filter if the bare part is common
            # AND the receiver is a builtin
            if "." in name:
                receiver = name.split(".")[0]
                if receiver in builtins:
                    continue
                if bare in common:
                    continue
            calls.append(name)
        return calls

    # ── Hash computation ────────────────────────────────────────────────

    def _compute_signature_hash(self, text: str) -> str:
        """Hash the full text (signature + body) for change detection."""
        return _sha256_short(text)

    def _compute_structure_hash(self, text: str, name: str) -> str:
        """Hash text with name removed for rename detection."""
        nameless = text.replace(name, "___", 1)
        return _sha256_short(nameless)

    # ── Scope tracking ──────────────────────────────────────────────────

    def _apply_scoping(self, entities: List[ASTEntity]) -> List[ASTEntity]:
        """Apply hierarchical scoping: nested entities get 'Parent.child' names.

        Sorts by line_start, uses a stack of (name, line_end) to track nesting.
        """
        entities.sort(key=lambda e: (e.line_start, -(e.line_end - e.line_start)))
        scope_stack: List[Tuple[str, int]] = []  # (name, line_end)
        result = []

        for entity in entities:
            # Pop scopes that have ended before this entity
            while scope_stack and entity.line_start > scope_stack[-1][1]:
                scope_stack.pop()

            if scope_stack and entity.entity_type != "import":
                parent_name = scope_stack[-1][0]
                entity.name = f"{parent_name}.{entity.name}"

            # Push classes as scope containers
            if entity.entity_type == "class":
                scope_stack.append((entity.name, entity.line_end))

            result.append(entity)

        return result

    # ── Type reference extraction (override in subclasses) ──────────────

    _TYPE_ANNOTATION_PATTERN = re.compile(r':\s*([A-Z][A-Za-z0-9_]*)')

    def _extract_type_refs_from_text(self, text: str) -> List[str]:
        """Extract type annotation references from declaration text."""
        return []  # Default: no type refs. Override in subclasses.

    # ── Decorator extraction ────────────────────────────────────────────

    _DECORATOR_PATTERN = re.compile(r'@(\w+(?:\.\w+)*)')

    def _extract_decorators(self, lines: List[str], decl_line: int) -> List[str]:
        """Extract decorator names from lines preceding a declaration."""
        decorators = []
        i = decl_line - 1
        while i >= 0:
            line = lines[i].strip()
            m = self._DECORATOR_PATTERN.match(line)
            if m:
                decorators.append(m.group(1))
                i -= 1
            else:
                break
        decorators.reverse()
        return decorators

    # ── Inheritance extraction ──────────────────────────────────────────

    def _extract_inherits(self, match: re.Match) -> List[str]:
        """Extract inheritance list from a declaration match.

        Subclasses should override if their pattern captures an inherits group.
        """
        try:
            inherits_str = match.group("inherits")
        except IndexError:
            return []
        if not inherits_str:
            return []
        # Split on commas, strip generics, whitespace
        bases = []
        for base in inherits_str.split(","):
            base = base.strip()
            # Remove generic params
            base = re.sub(r'<[^>]*>', '', base).strip()
            # Remove keywords like 'public', 'private', etc.
            parts = base.split()
            base = parts[-1] if parts else base
            if base and base[0].isupper():
                bases.append(base)
        return bases

    # ── JSX component extraction (TS/JS only, no-op by default) ────────

    def _extract_jsx_components(self, body: str) -> List[str]:
        """Extract JSX component usage from body text. Override in TS/JS."""
        return []

    # ── Main extract pipeline ───────────────────────────────────────────

    def extract(self, source: str, file_path: str = "") -> List[ASTEntity]:
        """Extract code entities from source code.

        Pipeline: strip -> extract imports -> extract declarations ->
        find bodies -> extract calls/types/inheritance -> apply scoping.
        """
        if not source or not source.strip():
            return []

        lines = source.split("\n")
        stripped = self._strip_comments_and_strings(source)
        stripped_lines = stripped.split("\n")
        entities: List[ASTEntity] = []

        # 1. Extract imports (use original source so string literals are intact)
        entities.extend(self._extract_imports(source, lines))

        # 2. Extract declarations
        entities.extend(self._extract_declarations(
            source, lines, stripped, stripped_lines
        ))

        # 3. Apply scoping
        entities = self._apply_scoping(entities)

        return entities

    def _extract_imports(
        self, stripped: str, stripped_lines: List[str]
    ) -> List[ASTEntity]:
        """Extract import entities using language-specific patterns."""
        entities = []
        for pattern in self._get_import_patterns():
            for m in pattern.finditer(stripped):
                line_num = stripped[:m.start()].count("\n") + 1
                end_line = stripped[:m.end()].count("\n") + 1
                import_pairs = self._parse_import_match(m)
                for module, name in import_pairs:
                    sig = f"import:{module}:{name}"
                    entities.append(ASTEntity(
                        entity_type="import",
                        name=name,
                        line_start=line_num,
                        line_end=end_line,
                        signature_hash=_sha256_short(sig),
                        structure_hash=_sha256_short("other:import"),
                        imports=[(module, name)],
                    ))
        return entities

    def _extract_declarations(
        self, source: str, lines: List[str],
        stripped: str, stripped_lines: List[str],
    ) -> List[ASTEntity]:
        """Extract declaration entities using language-specific patterns."""
        entities = []
        patterns = self._get_declaration_patterns()

        for entity_type, pat_list in patterns.items():
            for pattern in pat_list:
                for m in pattern.finditer(stripped):
                    name = m.group("name")
                    if not name:
                        continue

                    line_start = stripped[:m.start()].count("\n") + 1
                    decl_line_idx = line_start - 1  # 0-indexed

                    # Find body end via brace counting
                    line_end = self._find_body_end(stripped_lines, decl_line_idx) + 1

                    # If no braces found on this line, check if it's a one-liner
                    if line_end == line_start:
                        # For variables/type aliases, just use the match end
                        if entity_type == "variable":
                            line_end = stripped[:m.end()].count("\n") + 1

                    # Extract raw body text for call extraction
                    body_lines = lines[decl_line_idx:line_end]
                    body_text = "\n".join(body_lines)
                    stripped_body = "\n".join(stripped_lines[decl_line_idx:line_end])

                    # Extract calls
                    calls = self._extract_calls_from_body(stripped_body)

                    # Extract JSX components (TS/JS only)
                    jsx = self._extract_jsx_components(stripped_body)
                    calls.extend(c for c in jsx if c not in calls)

                    # Extract type refs
                    type_refs = self._extract_type_refs_from_text(stripped_body)

                    # Extract inherits
                    inherits = self._extract_inherits(m)

                    # Extract decorators from original lines
                    decorators = self._extract_decorators(stripped_lines, decl_line_idx)

                    # Compute hashes from original source
                    sig_text = "\n".join(lines[decl_line_idx:line_end])
                    sig_hash = self._compute_signature_hash(sig_text)
                    struct_hash = self._compute_structure_hash(sig_text, name)

                    entities.append(ASTEntity(
                        entity_type=entity_type,
                        name=name,
                        line_start=line_start,
                        line_end=line_end,
                        signature_hash=sig_hash,
                        structure_hash=struct_hash,
                        calls=calls,
                        inherits=inherits,
                        type_refs=type_refs,
                        decorators=decorators,
                    ))

        return entities

    # ── Abstract hooks for subclasses ───────────────────────────────────

    @abstractmethod
    def _get_declaration_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Return entity_type -> list of compiled regex patterns.

        Each pattern must have a named group `?P<name>` for the entity name.
        Optionally: `?P<inherits>` for inheritance list.
        """
        ...

    @abstractmethod
    def _get_import_patterns(self) -> List[re.Pattern]:
        """Return list of compiled patterns matching import statements."""
        ...

    @abstractmethod
    def _parse_import_match(self, match: re.Match) -> List[Tuple[str, str]]:
        """Parse an import regex match into (module, name) tuples."""
        ...

    @abstractmethod
    def _get_builtin_names(self) -> FrozenSet[str]:
        """Return set of builtin names to filter from calls."""
        ...

    @abstractmethod
    def _get_common_methods(self) -> FrozenSet[str]:
        """Return set of common method names to filter from bare calls."""
        ...
