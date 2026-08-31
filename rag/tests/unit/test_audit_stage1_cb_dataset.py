#!/usr/bin/env python3
"""
Stage 1 audit bugfix tests — B4 (circuit breaker) + B5 (append_cases data loss).

B4: CircuitBreakerConfig.success_threshold says "Successes to close from
half-open". But _on_success compares against the cumulative successful_calls
counter (never reset), so after warmup a SINGLE half-open success closes the
circuit — defeating success_threshold > 1.

B5: append_cases writes a fresh top-level `cases:` mapping on every call
(append mode). PyYAML safe_load keeps only the LAST duplicate top-level key, so
every previously-promoted golden case is silently lost on the next promotion.

Run: pytest tests/unit/test_audit_stage1_cb_dataset.py -v
"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# B4 — circuit breaker success_threshold is respected
# ---------------------------------------------------------------------------


def _make_breaker(success_threshold=2, recovery_timeout=0.05):
    from core.fallback.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerConfig,
    )

    cfg = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout=recovery_timeout,
        half_open_max_calls=10,
        success_threshold=success_threshold,
    )
    return CircuitBreaker("test", cfg)


def _force_open(cb):
    def _boom():
        raise RuntimeError("down")

    for _ in range(cb.config.failure_threshold):
        with pytest.raises(RuntimeError):
            cb.call_sync(_boom)
    assert cb.state.name == "OPEN"


def test_b4_single_half_open_success_does_not_close():
    """With success_threshold=2, one HALF_OPEN success MUST keep the breaker
    in HALF_OPEN (not flip to CLOSED)."""
    cb = _make_breaker(success_threshold=2)
    # Warm up so the cumulative successful_calls counter is large (this is
    # what the buggy code compares against).
    for _ in range(5):
        cb.call_sync(lambda: "ok")
    _force_open(cb)
    time.sleep(cb.config.recovery_timeout + 0.02)
    assert cb.state.name == "HALF_OPEN", f"expected HALF_OPEN, got {cb.state.name}"

    # First success — must NOT close yet (threshold is 2).
    cb.call_sync(lambda: "ok")
    assert cb.state.name == "HALF_OPEN", (
        f"after ONE half-open success state={cb.state.name}, expected HALF_OPEN "
        f"(success_threshold=2 not yet met)"
    )


def test_b4_two_half_open_successes_close():
    """The SECOND consecutive half-open success MUST close the breaker."""
    cb = _make_breaker(success_threshold=2)
    _force_open(cb)
    time.sleep(cb.config.recovery_timeout + 0.02)
    cb.call_sync(lambda: "ok")
    cb.call_sync(lambda: "ok")
    assert cb.state.name == "CLOSED", (
        f"after TWO half-open successes state={cb.state.name}, expected CLOSED"
    )


def test_b4_half_open_successes_reset_on_reentry():
    """If the breaker drops back to OPEN from HALF_OPEN (a failure) and later
    re-enters HALF_OPEN, the success counter MUST reset so the full threshold
    is required again."""
    cb = _make_breaker(success_threshold=2)
    _force_open(cb)
    time.sleep(cb.config.recovery_timeout + 0.02)
    # One success (not enough), then a failure re-opens.
    cb.call_sync(lambda: "ok")
    with pytest.raises(RuntimeError):
        cb.call_sync(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert cb.state.name == "OPEN"
    # Re-enter HALF_OPEN; one success must again NOT close (counter reset).
    time.sleep(cb.config.recovery_timeout + 0.02)
    cb.call_sync(lambda: "ok")
    assert cb.state.name == "HALF_OPEN", (
        "success counter not reset across HALF_OPEN re-entry; one success closed the breaker"
    )


# ---------------------------------------------------------------------------
# B5 — append_cases preserves all promoted cases
# ---------------------------------------------------------------------------


def _case(cid):
    from agent.eval.types import EvalCase

    return EvalCase(
        id=cid,
        query=f"q-{cid}",
        expected_sections=[],
        expected_keywords=[],
        expected_intent="general",
        expected_min_sources=0,
        difficulty="easy",
    )


def test_b5_append_preserves_all_cases(tmp_path):
    """Promoting three candidates one-by-one MUST leave all three in the
    dataset after reload (the bug kept only the last one)."""
    from agent.eval.dataset import append_cases, load_dataset

    path = str(tmp_path / "golden.yaml")
    append_cases(path, [_case("c1")])
    append_cases(path, [_case("c2")])
    append_cases(path, [_case("c3")])

    loaded = load_dataset(path)
    ids = sorted(c.id for c in loaded)
    assert ids == ["c1", "c2", "c3"], f"data lost! loaded ids={ids}"


def test_b5_append_dedups_by_id(tmp_path):
    """Re-promoting an existing id MUST be a no-op (not a duplicate)."""
    from agent.eval.dataset import append_cases, load_dataset

    path = str(tmp_path / "golden.yaml")
    append_cases(path, [_case("c1")])
    append_cases(path, [_case("c1")])  # duplicate
    append_cases(path, [_case("c2")])

    loaded = load_dataset(path)
    ids = sorted(c.id for c in loaded)
    assert ids == ["c1", "c2"], f"dedup broken, ids={ids}"


def test_b5_single_cases_key(tmp_path):
    """The file MUST contain exactly ONE top-level `cases:` key after multiple
    appends (duplicate keys are what caused the silent data loss)."""
    import yaml

    from agent.eval.dataset import append_cases

    path = str(tmp_path / "golden.yaml")
    append_cases(path, [_case("c1")])
    append_cases(path, [_case("c2")])

    # PyYAML load_all over a stream with duplicate top-level keys yields one
    # document per `---`; but duplicate keys within one document are silently
    # collapsed. Count raw occurrences of the key token instead.
    with open(path, encoding="utf-8") as f:
        text = f.read()
    n = text.count("cases:")
    assert n == 1, f"expected 1 top-level `cases:` key, found {n}\n---\n{text}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
