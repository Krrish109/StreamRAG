"""Shadow AST: handles broken/incomplete code via binary search + regex fallback."""

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from streamrag.models import ASTEntity


class ParseStatus:
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass
class ParseRegion:
    """A region of source code with parse status."""
    start_line: int  # 1-indexed
    end_line: int    # 1-indexed
    status: str      # 'VALID' | 'INVALID'
    entities: List[ASTEntity] = field(default_factory=list)
    confidence: float = 1.0
    source: str = ""


# Regex patterns for fallback extraction on invalid regions
FUNCTION_PATTERN = re.compile(r"^\s*(async\s+)?def\s+(\w+)\s*\(([^)]*)\)?:?", re.MULTILINE)
CLASS_PATTERN = re.compile(r"^\s*class\s+(\w+)\s*(\([^)]*\))?:?", re.MULTILINE)
IMPORT_PATTERN = re.compile(r"^\s*(from\s+[\w.]+\s+)?import\s+", re.MULTILINE)


class ShadowAST:
    """Parse source code with fallback for broken/incomplete code.

    Strategy:
    1. Try full parse. If works -> single VALID region.
    2. If SyntaxError: binary search for valid regions.
    3. Regex extraction on invalid regions with confidence scores.
    """

    def parse(self, source: str) -> List[ParseRegion]:
        """Parse source into a list of ParseRegions."""
        if not source.strip():
            return []

        lines = source.splitlines(keepends=True)
        total_lines = len(lines)

        # Try full parse first
        try:
            tree = ast.parse(source)
            from streamrag.extractor import ASTExtractor
            entities = ASTExtractor().extract(source)
            return [ParseRegion(
                start_line=1, end_line=total_lines,
                status=ParseStatus.VALID, entities=entities,
                confidence=1.0, source=source,
            )]
        except SyntaxError:
            pass

        # Binary search for valid regions
        return self._binary_search_regions(lines, 1, total_lines)

    def _binary_search_regions(
        self, lines: List[str], start: int, end: int
    ) -> List[ParseRegion]:
        """Recursively split and parse to find valid/invalid regions."""
        if start > end:
            return []

        chunk = "".join(lines[start - 1:end])

        # Try parsing this chunk
        try:
            ast.parse(chunk)
            from streamrag.extractor import ASTExtractor
            entities = ASTExtractor().extract(chunk)
            # Adjust line numbers to absolute positions
            for e in entities:
                e.line_start += start - 1
                e.line_end += start - 1
            return [ParseRegion(
                start_line=start, end_line=end,
                status=ParseStatus.VALID, entities=entities,
                confidence=1.0, source=chunk,
            )]
        except SyntaxError:
            pass

        # Base case: single line
        if start == end:
            entities = self._regex_extract(chunk, start)
            return [ParseRegion(
                start_line=start, end_line=end,
                status=ParseStatus.INVALID,
                entities=entities,
                confidence=max((e.confidence if hasattr(e, 'confidence') else 0.5 for e in entities), default=0.0) if entities else 0.0,
                source=chunk,
            )]

        # Split in half and recurse
        mid = (start + end) // 2
        left = self._binary_search_regions(lines, start, mid)
        right = self._binary_search_regions(lines, mid + 1, end)
        return left + right

    def _regex_extract(self, text: str, line_num: int) -> List[ASTEntity]:
        """Extract entities from invalid regions using regex."""
        entities: List[ASTEntity] = []

        # Function pattern
        match = FUNCTION_PATTERN.match(text)
        if match:
            has_colon = ":" in text.split("def", 1)[-1]
            has_close_paren = ")" in text
            if has_colon and has_close_paren:
                confidence = 0.9
            elif has_close_paren:
                confidence = 0.7
            else:
                confidence = 0.5

            name = match.group(2)
            args = match.group(3) or ""
            entities.append(ASTEntity(
                entity_type="function", name=name,
                line_start=line_num, line_end=line_num,
                signature_hash=f"shadow:{name}({args})",
                structure_hash=f"shadow_func:{args}",
                calls=[], uses=[], inherits=[], imports=[],
            ))
            # Store confidence as attribute
            entities[-1].__dict__["confidence"] = confidence
            return entities

        # Class pattern
        match = CLASS_PATTERN.match(text)
        if match:
            has_colon = text.rstrip().endswith(":")
            confidence = 0.9 if has_colon else 0.6

            name = match.group(1)
            entities.append(ASTEntity(
                entity_type="class", name=name,
                line_start=line_num, line_end=line_num,
                signature_hash=f"shadow:{name}",
                structure_hash=f"shadow_class",
                calls=[], uses=[], inherits=[], imports=[],
            ))
            entities[-1].__dict__["confidence"] = confidence
            return entities

        # Import pattern
        match = IMPORT_PATTERN.match(text)
        if match:
            entities.append(ASTEntity(
                entity_type="import", name=f"__import_{line_num}__",
                line_start=line_num, line_end=line_num,
                signature_hash=f"shadow:import:{line_num}",
                structure_hash="shadow_import",
                calls=[], uses=[], inherits=[], imports=[],
            ))
            entities[-1].__dict__["confidence"] = 0.7
            return entities

        return entities


class IncrementalShadowAST(ShadowAST):
    """Shadow AST with incremental caching."""

    def __init__(self) -> None:
        self._region_cache: Dict[Tuple[int, int], ParseRegion] = {}
        self._last_source: Optional[str] = None

    def update(self, source: str, changed_lines: Optional[range] = None) -> List[ParseRegion]:
        """Re-parse only affected regions, merge with cache.

        If changed_lines is None, re-parses everything.
        """
        if changed_lines is None or self._last_source is None:
            regions = self.parse(source)
            self._update_cache(regions)
            self._last_source = source
            return regions

        lines = source.splitlines(keepends=True)
        total_lines = len(lines)

        # Find regions that overlap with changed lines
        affected_start = changed_lines.start + 1  # Convert to 1-indexed
        affected_end = min(changed_lines.stop, total_lines)

        # Keep unaffected cached regions
        new_regions: List[ParseRegion] = []
        for (start, end), region in sorted(self._region_cache.items()):
            if end < affected_start or start > affected_end:
                # No overlap, keep cached
                new_regions.append(region)

        # Re-parse affected range
        if affected_start <= total_lines:
            reparsed = self._binary_search_regions(
                lines, affected_start, min(affected_end, total_lines)
            )
            new_regions.extend(reparsed)

        # Sort by start line
        new_regions.sort(key=lambda r: r.start_line)
        self._update_cache(new_regions)
        self._last_source = source
        return new_regions

    def _update_cache(self, regions: List[ParseRegion]) -> None:
        """Update the region cache."""
        self._region_cache = {
            (r.start_line, r.end_line): r for r in regions
        }
