"""Tests for V2 adaptive debouncer."""

from streamrag.v2.debouncer import AdaptiveDebouncer, DebounceTier


def test_semantic_on_long_gap():
    d = AdaptiveDebouncer()
    d.process_keystroke("a", 1000)
    tier = d.process_keystroke("b", 1600)  # 600ms gap
    assert tier == DebounceTier.SEMANTIC


def test_statement_on_closing_bracket_at_depth_0():
    d = AdaptiveDebouncer()
    d.process_keystroke("(", 10)  # depth 1
    d.process_keystroke("x", 20)
    d.process_keystroke(")", 30)  # back to depth 0
    assert d._bracket_depth == 0
    # The closing bracket at depth 0 should have been STATEMENT
    # (since after decrement it becomes 0)


def test_colon_outside_string_is_statement():
    d = AdaptiveDebouncer()
    tier = d.process_keystroke(":", 10)
    assert tier == DebounceTier.STATEMENT


def test_structural_char_is_token():
    d = AdaptiveDebouncer()
    for char in "()[]{}=,;":
        d2 = AdaptiveDebouncer()
        tier = d2.process_keystroke(char, 10)
        if char == ":":
            assert tier == DebounceTier.STATEMENT
        elif char in ")]}":
            assert tier == DebounceTier.STATEMENT  # closing at depth 0
        else:
            assert tier in (DebounceTier.TOKEN, DebounceTier.STATEMENT), f"Failed for {char}"


def test_newline_after_complete_line_is_statement():
    d = AdaptiveDebouncer()
    for c in "x = 1":
        d.process_keystroke(c, 10)
    tier = d.process_keystroke("\n", 20)
    assert tier == DebounceTier.STATEMENT


def test_newline_after_continuation_is_token():
    d = AdaptiveDebouncer()
    for c in "def foo(":
        d.process_keystroke(c, 10)
    tier = d.process_keystroke("\n", 20)
    assert tier == DebounceTier.TOKEN


def test_medium_gap_is_statement():
    d = AdaptiveDebouncer()
    d.process_keystroke("a", 1000)
    tier = d.process_keystroke("b", 1250)  # 250ms > 200ms
    assert tier == DebounceTier.STATEMENT


def test_short_gap_is_token():
    d = AdaptiveDebouncer()
    d.process_keystroke("a", 1000)
    tier = d.process_keystroke("b", 1075)  # 75ms > 50ms
    assert tier == DebounceTier.TOKEN


def test_default_is_buffer_only():
    d = AdaptiveDebouncer()
    d.process_keystroke("a", 1000)
    tier = d.process_keystroke("b", 1010)  # 10ms < 50ms
    assert tier == DebounceTier.BUFFER_ONLY


def test_string_state_tracking():
    d = AdaptiveDebouncer()
    d.process_keystroke("'", 10)
    assert d._in_string is True
    # Colon inside string should NOT be STATEMENT
    tier = d.process_keystroke(":", 20)
    assert tier != DebounceTier.STATEMENT  # Inside string
    d.process_keystroke("'", 30)
    assert d._in_string is False


def test_bracket_depth_tracking():
    d = AdaptiveDebouncer()
    d.process_keystroke("(", 10)
    assert d._bracket_depth == 1
    d.process_keystroke("(", 20)
    assert d._bracket_depth == 2
    d.process_keystroke(")", 30)
    assert d._bracket_depth == 1
    d.process_keystroke(")", 40)
    assert d._bracket_depth == 0


def test_bracket_depth_clamps_to_zero():
    d = AdaptiveDebouncer()
    d.process_keystroke(")", 10)
    assert d._bracket_depth == 0  # Clamped, not -1


def test_flush():
    d = AdaptiveDebouncer()
    d.process_keystroke("h", 10)
    d.process_keystroke("i", 20)
    content = d.flush()
    assert content == "hi"
    assert d.buffer_size == 0
    assert d.batches_emitted == 1


def test_buffer_force_flush():
    d = AdaptiveDebouncer(max_buffer_size=5)
    for i, c in enumerate("abcde"):
        d.process_keystroke(c, i * 10)
    # Buffer is full, next keystroke should be at least TOKEN
    tier = d.process_keystroke("f", 60)
    assert tier >= DebounceTier.TOKEN


def test_stats():
    d = AdaptiveDebouncer()
    d.process_keystroke("a", 0)
    d.process_keystroke(":", 10)
    stats = d.get_stats()
    assert stats["total_keystrokes"] == 2
    assert stats["buffer_size"] == 2


def test_semantic_update_rate():
    d = AdaptiveDebouncer()
    # 3 keystrokes: 1 buffer, 1 statement (colon), 1 buffer
    d.process_keystroke("a", 0)
    d.process_keystroke(":", 10)  # STATEMENT
    d.process_keystroke("b", 20)
    rate = d.semantic_update_rate
    assert 0 < rate < 1
