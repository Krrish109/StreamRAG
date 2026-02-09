"""Adaptive debouncer with tier-based keystroke classification."""

from collections import deque
from enum import IntEnum
from typing import Deque, Dict, List, Optional, Tuple


class DebounceTier(IntEnum):
    """Debounce tiers from lowest to highest priority."""
    BUFFER_ONLY = -1  # Just accumulate, no action
    CHARACTER = 0     # Unused
    TOKEN = 1         # Structural char typed
    STATEMENT = 2     # Complete statement detected
    SEMANTIC = 3      # Long pause or save


# Tier thresholds in milliseconds
TIER_THRESHOLDS = {
    DebounceTier.TOKEN: 50,
    DebounceTier.STATEMENT: 200,
    DebounceTier.SEMANTIC: 500,
}

STRUCTURAL_CHARS = set(":()[]{}=,;")
OPENING_BRACKETS = set("([{")
CLOSING_BRACKETS = set(")]}")
STRING_CHARS = set("'\"")
CONTINUATION_ENDINGS = set("\\,([{")


class AdaptiveDebouncer:
    """Classifies keystrokes into debounce tiers.

    Tier determination logic (highest priority first):
    1. Gap > 500ms -> SEMANTIC
    2. Closing bracket at depth==0 -> STATEMENT
    3. ':' outside string -> STATEMENT
    4. Other structural char -> TOKEN
    5. Newline after non-empty line not ending with continuation -> STATEMENT
    6. Newline otherwise -> TOKEN
    7. Gap > 200ms -> STATEMENT
    8. Gap > 50ms -> TOKEN
    9. Default -> BUFFER_ONLY
    """

    def __init__(self, max_buffer_size: int = 1000) -> None:
        self._buffer: Deque[str] = deque(maxlen=max_buffer_size)
        self._bracket_depth: int = 0
        self._in_string: bool = False
        self._string_char: Optional[str] = None
        self._last_char_time: Optional[float] = None
        self._current_line: str = ""

        # Stats
        self.total_keystrokes: int = 0
        self.tier_triggers: Dict[DebounceTier, int] = {t: 0 for t in DebounceTier}
        self.batches_emitted: int = 0

    def process_keystroke(self, char: str, timestamp_ms: float) -> DebounceTier:
        """Process a keystroke and return its tier classification."""
        self.total_keystrokes += 1
        gap_ms = timestamp_ms - self._last_char_time if self._last_char_time is not None else 0
        self._last_char_time = timestamp_ms

        # Track string state
        if char in STRING_CHARS and not self._in_string:
            self._in_string = True
            self._string_char = char
        elif self._in_string and char == self._string_char:
            self._in_string = False
            self._string_char = None

        # Track bracket depth (only outside strings)
        if not self._in_string:
            if char in OPENING_BRACKETS:
                self._bracket_depth += 1
            elif char in CLOSING_BRACKETS:
                self._bracket_depth = max(0, self._bracket_depth - 1)

        # Buffer the character
        self._buffer.append(char)
        force_flush = len(self._buffer) >= self._buffer.maxlen

        # Determine tier
        tier = self._determine_tier(char, gap_ms)

        # Track newlines for line tracking
        if char == "\n":
            self._current_line = ""
        else:
            self._current_line += char

        self.tier_triggers[tier] += 1

        if force_flush and tier == DebounceTier.BUFFER_ONLY:
            tier = DebounceTier.TOKEN

        return tier

    def _determine_tier(self, char: str, gap_ms: float) -> DebounceTier:
        """Apply the 9-rule tier determination logic."""
        # Rule 1: Long gap -> SEMANTIC
        if gap_ms > TIER_THRESHOLDS[DebounceTier.SEMANTIC]:
            return DebounceTier.SEMANTIC

        if not self._in_string:
            # Rule 2: Closing bracket at depth 0 -> STATEMENT
            if char in CLOSING_BRACKETS and self._bracket_depth == 0:
                return DebounceTier.STATEMENT

            # Rule 3: Colon outside string -> STATEMENT
            if char == ":":
                return DebounceTier.STATEMENT

            # Rule 4: Other structural char -> TOKEN
            if char in STRUCTURAL_CHARS:
                return DebounceTier.TOKEN

        # Rule 5 & 6: Newline handling
        if char == "\n":
            line = self._current_line.rstrip()
            if line and not any(line.endswith(c) for c in CONTINUATION_ENDINGS):
                return DebounceTier.STATEMENT  # Rule 5
            return DebounceTier.TOKEN  # Rule 6

        # Rule 7: Medium gap -> STATEMENT
        if gap_ms > TIER_THRESHOLDS[DebounceTier.STATEMENT]:
            return DebounceTier.STATEMENT

        # Rule 8: Short gap -> TOKEN
        if gap_ms > TIER_THRESHOLDS[DebounceTier.TOKEN]:
            return DebounceTier.TOKEN

        # Rule 9: Default -> BUFFER_ONLY
        return DebounceTier.BUFFER_ONLY

    def flush(self) -> str:
        """Return buffered content and clear the buffer."""
        content = "".join(self._buffer)
        self._buffer.clear()
        self.batches_emitted += 1
        return content

    def peek(self) -> str:
        """Return buffered content without clearing."""
        return "".join(self._buffer)

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def semantic_update_rate(self) -> float:
        """Fraction of keystrokes that triggered >= STATEMENT tier."""
        if self.total_keystrokes == 0:
            return 0.0
        semantic = sum(
            self.tier_triggers[t]
            for t in (DebounceTier.STATEMENT, DebounceTier.SEMANTIC)
        )
        return semantic / self.total_keystrokes

    def get_stats(self) -> Dict:
        return {
            "total_keystrokes": self.total_keystrokes,
            "tier_triggers": {t.name: c for t, c in self.tier_triggers.items()},
            "batches_emitted": self.batches_emitted,
            "semantic_update_rate": self.semantic_update_rate,
            "buffer_size": self.buffer_size,
            "bracket_depth": self._bracket_depth,
            "in_string": self._in_string,
        }
