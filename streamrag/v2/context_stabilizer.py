"""Context stabilizer: prevents AI suggestion flickering during typing."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# Built-in tokens with confidence 1.0
BUILTINS: Set[str] = {
    "self", "cls", "None", "True", "False", "print", "len", "range",
    "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "type", "isinstance", "issubclass", "super", "property",
    "staticmethod", "classmethod", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "any", "all", "min", "max", "sum", "abs",
    "open", "input", "repr", "hash", "id", "dir", "vars", "getattr",
    "setattr", "hasattr", "delattr", "callable",
}

# Suffixes that indicate stable identifiers
STABLE_SUFFIXES = {"_id", "_name", "_list", "_map", "_set", "_dict", "_type", "_count", "_path", "_file"}


@dataclass
class StableContext:
    """Context that doesn't change during typing (cached)."""
    file_path: str = ""
    enclosing_function: str = ""
    enclosing_class: str = ""
    imports: List[str] = field(default_factory=list)
    available_symbols: List[str] = field(default_factory=list)


@dataclass
class VolatileContext:
    """Context that updates each call."""
    line: int = 0
    column: int = 0
    current_token: str = ""
    token_confidence: float = 0.0


@dataclass
class FullContext:
    """Combined stable + volatile context."""
    stable: StableContext = field(default_factory=StableContext)
    volatile: VolatileContext = field(default_factory=VolatileContext)
    is_within_stability_window: bool = False


def assess_token_confidence(token: str) -> float:
    """Assess the confidence/stability of a token.

    Builtins -> 1.0
    Ends with stable suffix (_id, _name, etc.) -> 0.95
    Ends with _ -> 0.3
    Length < 2 -> 0.2
    Contains _ (not ending) -> 0.85
    ALL CAPS (len >= 2) -> 0.9
    Has internal uppercase (CamelCase) -> 0.85
    Default -> 0.6
    """
    if not token:
        return 0.0

    if token in BUILTINS:
        return 1.0

    if any(token.endswith(suffix) for suffix in STABLE_SUFFIXES):
        return 0.95

    if token.endswith("_"):
        return 0.3

    if len(token) < 2:
        return 0.2

    if "_" in token:
        return 0.85

    if token.isupper() and len(token) >= 2:
        return 0.9

    # CamelCase detection
    if any(c.isupper() for c in token[1:]):
        return 0.85

    return 0.6


class ContextStabilizer:
    """Prevents AI context flickering during typing.

    Within the stability window (default 300ms), returns cached structural
    context with reduced confidence. After window expires, rebuilds fresh.
    """

    def __init__(self, stability_window_ms: float = 300.0) -> None:
        self.stability_window_ms = stability_window_ms
        self._cached_stable: Optional[StableContext] = None
        self._last_rebuild_time: float = 0.0
        self._min_token_length: int = 2

    def get_context(
        self,
        file_path: str,
        line: int,
        column: int,
        current_token: str,
        stable_builder: Optional[Any] = None,
    ) -> FullContext:
        """Get context, using cache within the stability window."""
        now = time.monotonic() * 1000  # ms
        elapsed = now - self._last_rebuild_time

        in_window = elapsed < self.stability_window_ms and self._cached_stable is not None

        if in_window:
            stable = self._cached_stable
        else:
            # Rebuild stable context
            if stable_builder and callable(stable_builder):
                stable = stable_builder(file_path)
            else:
                stable = StableContext(file_path=file_path)
            self._cached_stable = stable
            self._last_rebuild_time = now

        # Volatile context always computed fresh
        confidence = assess_token_confidence(current_token)
        if in_window:
            confidence *= 0.5  # Halve confidence during stability window

        volatile = VolatileContext(
            line=line,
            column=column,
            current_token=current_token,
            token_confidence=confidence,
        )

        return FullContext(
            stable=stable,
            volatile=volatile,
            is_within_stability_window=in_window,
        )

    def invalidate(self) -> None:
        """Force rebuild on next call."""
        self._cached_stable = None
        self._last_rebuild_time = 0.0


class AdaptiveContextStabilizer(ContextStabilizer):
    """Adjusts stability window based on typing speed.

    Fast (<100ms gaps) = min window
    Slow (>500ms gaps) = max window
    Linear interpolation between.
    """

    def __init__(
        self,
        min_window_ms: float = 100.0,
        max_window_ms: float = 500.0,
        fast_threshold_ms: float = 100.0,
        slow_threshold_ms: float = 500.0,
    ) -> None:
        super().__init__(stability_window_ms=min_window_ms)
        self._min_window = min_window_ms
        self._max_window = max_window_ms
        self._fast_threshold = fast_threshold_ms
        self._slow_threshold = slow_threshold_ms
        self._last_keystroke_time: float = 0.0

    def record_keystroke(self, timestamp_ms: Optional[float] = None) -> None:
        """Record a keystroke and adjust the stability window."""
        now = timestamp_ms or (time.monotonic() * 1000)
        if self._last_keystroke_time > 0:
            gap = now - self._last_keystroke_time
            self._adjust_window(gap)
        self._last_keystroke_time = now

    def _adjust_window(self, gap_ms: float) -> None:
        """Linearly interpolate window based on gap."""
        if gap_ms <= self._fast_threshold:
            self.stability_window_ms = self._min_window
        elif gap_ms >= self._slow_threshold:
            self.stability_window_ms = self._max_window
        else:
            ratio = (gap_ms - self._fast_threshold) / (self._slow_threshold - self._fast_threshold)
            self.stability_window_ms = self._min_window + ratio * (self._max_window - self._min_window)
