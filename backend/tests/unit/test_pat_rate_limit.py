# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests for the per-token sliding-window rate limiter.

Pure data-structure tests — no DB, no FastAPI. Time is patched via
``time.monotonic`` so a 60-second window can be advanced in zero
wall-clock time.
"""
from __future__ import annotations

import pytest

from app.services import pat_rate_limit
from app.services.pat_rate_limit import PatSlidingWindow


@pytest.fixture
def fake_clock(monkeypatch):
    """Replace ``time.monotonic`` inside ``pat_rate_limit`` with a
    settable value so the tests can step through the window without
    sleeping."""
    state = {"now": 1_000_000.0}

    def _now() -> float:
        return state["now"]

    monkeypatch.setattr(pat_rate_limit.time, "monotonic", _now)
    return state


def test_first_n_requests_allowed_then_429(fake_clock):
    win = PatSlidingWindow()
    for _ in range(3):
        allowed, retry = win.check(token_id=1, limit=3)
        assert allowed is True
        assert retry == 0
    allowed, retry = win.check(token_id=1, limit=3)
    assert allowed is False
    assert retry >= 1


def test_window_slides_after_60_seconds(fake_clock):
    """Hits older than 60 s drop out of the window — the bucket
    refills automatically as time advances."""
    win = PatSlidingWindow()
    for _ in range(2):
        assert win.check(token_id=1, limit=2)[0] is True
    assert win.check(token_id=1, limit=2)[0] is False

    # Advance past the window — both prior hits age out.
    fake_clock["now"] += 61
    assert win.check(token_id=1, limit=2)[0] is True
    assert win.check(token_id=1, limit=2)[0] is True
    assert win.check(token_id=1, limit=2)[0] is False


def test_partial_window_slide_only_drops_old_hits(fake_clock):
    """Two hits at t=0, two more at t=30. At t=70 the first two are
    out of window, the second two still count."""
    win = PatSlidingWindow()
    win.check(token_id=1, limit=4)
    win.check(token_id=1, limit=4)
    fake_clock["now"] += 30
    win.check(token_id=1, limit=4)
    win.check(token_id=1, limit=4)
    # Cap at 4 — bucket full.
    assert win.check(token_id=1, limit=4)[0] is False

    # Advance to t=70: first two hits aged out; bucket has 2/4.
    fake_clock["now"] += 40
    assert win.check(token_id=1, limit=4)[0] is True
    assert win.check(token_id=1, limit=4)[0] is True
    # 4/4 again.
    assert win.check(token_id=1, limit=4)[0] is False


def test_separate_token_ids_have_independent_buckets(fake_clock):
    """Rate limiting is per-token — one token's burst must not
    starve another's budget."""
    win = PatSlidingWindow()
    for _ in range(3):
        assert win.check(token_id=1, limit=3)[0] is True
    assert win.check(token_id=1, limit=3)[0] is False

    # Token 2 is unaffected.
    assert win.check(token_id=2, limit=3)[0] is True


def test_retry_after_at_least_one_second(fake_clock):
    """Even when the oldest hit is < 1 s from ageing out, Retry-After
    must be at least 1 — clients shouldn't retry on a 0-s header."""
    win = PatSlidingWindow()
    win.check(token_id=1, limit=1)
    # 59.5 s later: the oldest hit ages out in 0.5 s.
    fake_clock["now"] += 59.5
    allowed, retry = win.check(token_id=1, limit=1)
    assert allowed is False
    assert retry >= 1


def test_reset_specific_token_clears_only_its_bucket(fake_clock):
    win = PatSlidingWindow()
    win.check(token_id=1, limit=1)
    win.check(token_id=2, limit=1)
    win.reset(token_id=1)
    assert win.check(token_id=1, limit=1)[0] is True   # bucket fresh
    assert win.check(token_id=2, limit=1)[0] is False  # untouched


def test_reset_all_clears_every_bucket(fake_clock):
    win = PatSlidingWindow()
    win.check(token_id=1, limit=1)
    win.check(token_id=2, limit=1)
    win.reset()
    assert win.check(token_id=1, limit=1)[0] is True
    assert win.check(token_id=2, limit=1)[0] is True


def test_module_level_check_rate_limit_uses_singleton(fake_clock):
    """``check_rate_limit`` is what ``PATAuthMiddleware`` calls. It
    delegates to a process-wide ``PatSlidingWindow``; ``reset_for_tests``
    clears it. Verify both."""
    pat_rate_limit.reset_for_tests()
    assert pat_rate_limit.check_rate_limit(token_id=42, limit_per_minute=2) == (
        True,
        0,
    )
    assert pat_rate_limit.check_rate_limit(token_id=42, limit_per_minute=2) == (
        True,
        0,
    )
    allowed, retry = pat_rate_limit.check_rate_limit(
        token_id=42, limit_per_minute=2
    )
    assert allowed is False
    assert retry >= 1

    pat_rate_limit.reset_for_tests(token_id=42)
    assert pat_rate_limit.check_rate_limit(token_id=42, limit_per_minute=2)[0] is True
