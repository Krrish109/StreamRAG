"""Tests for V2 context stabilizer."""

import time

from streamrag.v2.context_stabilizer import (
    assess_token_confidence,
    ContextStabilizer,
    AdaptiveContextStabilizer,
    BUILTINS,
)


def test_builtins_confidence_1():
    for token in ["self", "None", "True", "print", "len"]:
        assert assess_token_confidence(token) == 1.0


def test_stable_suffix_confidence():
    assert assess_token_confidence("user_id") == 0.95
    assert assess_token_confidence("file_name") == 0.95
    assert assess_token_confidence("item_list") == 0.95


def test_trailing_underscore_low_confidence():
    assert assess_token_confidence("temp_") == 0.3


def test_short_token_low_confidence():
    assert assess_token_confidence("x") == 0.2


def test_snake_case_confidence():
    assert assess_token_confidence("my_variable") == 0.85


def test_all_caps_confidence():
    # MAX_SIZE contains _ so hits snake_case rule (0.85) before ALL_CAPS
    assert assess_token_confidence("MAX_SIZE") == 0.85
    assert assess_token_confidence("PI") == 0.9


def test_camel_case_confidence():
    assert assess_token_confidence("myVariable") == 0.85
    assert assess_token_confidence("UserService") == 0.85


def test_default_confidence():
    assert assess_token_confidence("hello") == 0.6


def test_empty_token():
    assert assess_token_confidence("") == 0.0


def test_context_stabilizer_fresh_context():
    cs = ContextStabilizer(stability_window_ms=300)
    ctx = cs.get_context("test.py", 10, 5, "self")
    assert ctx.stable.file_path == "test.py"
    assert ctx.volatile.current_token == "self"
    assert ctx.volatile.token_confidence == 1.0  # Builtin
    assert ctx.is_within_stability_window is False


def test_context_stabilizer_within_window():
    cs = ContextStabilizer(stability_window_ms=10000)  # Long window
    # First call: fresh
    ctx1 = cs.get_context("test.py", 10, 5, "self")
    assert ctx1.is_within_stability_window is False

    # Immediate second call: within window
    ctx2 = cs.get_context("test.py", 11, 3, "foo")
    assert ctx2.is_within_stability_window is True
    # Confidence should be halved during window
    assert ctx2.volatile.token_confidence == assess_token_confidence("foo") * 0.5


def test_context_stabilizer_invalidate():
    cs = ContextStabilizer(stability_window_ms=10000)
    cs.get_context("test.py", 1, 1, "x")
    cs.invalidate()
    ctx = cs.get_context("test.py", 1, 1, "x")
    assert ctx.is_within_stability_window is False


def test_adaptive_stabilizer_fast_typing():
    acs = AdaptiveContextStabilizer(
        min_window_ms=100, max_window_ms=500,
        fast_threshold_ms=100, slow_threshold_ms=500,
    )
    # Simulate fast typing (50ms gaps)
    acs.record_keystroke(0)
    acs.record_keystroke(50)
    assert acs.stability_window_ms == 100  # Min window


def test_adaptive_stabilizer_slow_typing():
    acs = AdaptiveContextStabilizer(
        min_window_ms=100, max_window_ms=500,
        fast_threshold_ms=100, slow_threshold_ms=500,
    )
    # Simulate slow typing (600ms gaps) with explicit timestamps
    acs.record_keystroke(1000)
    acs.record_keystroke(1600)
    assert acs.stability_window_ms == 500  # Max window


def test_adaptive_stabilizer_interpolation():
    acs = AdaptiveContextStabilizer(
        min_window_ms=100, max_window_ms=500,
        fast_threshold_ms=100, slow_threshold_ms=500,
    )
    # Simulate medium typing (300ms gap = midpoint) with explicit timestamps
    acs.record_keystroke(1000)
    acs.record_keystroke(1300)
    # (300-100)/(500-100) = 0.5 -> 100 + 0.5*400 = 300
    assert abs(acs.stability_window_ms - 300) < 1
