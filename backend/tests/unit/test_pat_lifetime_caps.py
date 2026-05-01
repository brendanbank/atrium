# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests for the lifetime-cap helpers in ``app.api.auth_tokens``.

Pure date arithmetic — no DB, no FastAPI, no fixtures. The integration
tests exercise the same code paths through the real endpoint, but
unit-testing the cap logic in isolation makes the boundary cases
(None inputs, max-lifetime ceiling, naive vs aware datetimes)
faster to read and harder to regress.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.auth_tokens import (
    _cap_absolute_expires_at,
    _cap_expires_at,
    _row_status,
)
from app.models.auth_token import AuthToken


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---- _cap_expires_at ----------------------------------------------------


def test_cap_expires_at_no_input_no_policy_means_never():
    """``None`` in, ``None`` out when there's no policy ceiling."""
    assert _cap_expires_at(None, None) is None


def test_cap_expires_at_no_input_with_policy_lands_at_ceiling():
    """Caller asked for no expiry but operator policy caps at N days
    — token still gets an expiry at ``now + N``."""
    before = _utcnow()
    result = _cap_expires_at(None, max_lifetime_days=30)
    assert result is not None
    delta = result - before
    # Allow a generous second of slack for clock advancing during the
    # call without making the test flaky.
    assert timedelta(days=29, hours=23) < delta <= timedelta(days=30, seconds=2)


def test_cap_expires_at_request_below_policy_uses_request():
    """If the caller's request fits inside the policy ceiling, use it
    verbatim — no surprise extension."""
    before = _utcnow()
    result = _cap_expires_at(7, max_lifetime_days=30)
    delta = result - before
    assert timedelta(days=6, hours=23) < delta <= timedelta(days=7, seconds=2)


def test_cap_expires_at_request_above_policy_clamps_silently():
    """A request for 90 days under a 7-day policy lands at 7 days.
    The endpoint refuses overreach loudly elsewhere; here we silently
    clamp because the caller's intent (a long-lived token) is
    honoured to the policy maximum."""
    before = _utcnow()
    result = _cap_expires_at(90, max_lifetime_days=7)
    delta = result - before
    assert timedelta(days=6, hours=23) < delta <= timedelta(days=7, seconds=2)


def test_cap_expires_at_request_with_no_policy_uses_request():
    before = _utcnow()
    result = _cap_expires_at(365, max_lifetime_days=None)
    delta = result - before
    assert timedelta(days=364, hours=23) < delta <= timedelta(days=365, seconds=2)


# ---- _cap_absolute_expires_at ------------------------------------------


def test_cap_absolute_expires_at_passthrough_when_no_policy():
    far = _utcnow() + timedelta(days=365)
    assert _cap_absolute_expires_at(far, None) == far


def test_cap_absolute_expires_at_passthrough_when_below_ceiling():
    """User requests 5 days under a 30-day policy — keep the user's
    value, don't push it out to 30."""
    target = _utcnow() + timedelta(days=5)
    result = _cap_absolute_expires_at(target, max_lifetime_days=30)
    assert result == target


def test_cap_absolute_expires_at_clamps_to_now_plus_max():
    """User requests 365 days under a 30-day policy — land at
    now + 30 (not the user's far-future value)."""
    before = _utcnow()
    target = _utcnow() + timedelta(days=365)
    result = _cap_absolute_expires_at(target, max_lifetime_days=30)
    delta = result - before
    assert timedelta(days=29, hours=23) < delta <= timedelta(days=30, seconds=2)


def test_cap_absolute_expires_at_none_passthrough():
    assert _cap_absolute_expires_at(None, max_lifetime_days=30) is None


# ---- _row_status -------------------------------------------------------


def test_row_status_active_when_no_expiry_no_revoke():
    row = AuthToken(
        token_prefix="atr_pat_aaaa",
        token_hash="x",
        scopes=[],
        created_at=_utcnow(),
    )
    assert _row_status(row) == "active"


def test_row_status_revoked_wins_over_expiry():
    """A token revoked *and* past its expiry is reported as ``revoked``
    — the explicit operator action ranks above the implicit timeout."""
    past = _utcnow() - timedelta(days=10)
    row = AuthToken(
        token_prefix="atr_pat_aaaa",
        token_hash="x",
        scopes=[],
        created_at=past,
        expires_at=past + timedelta(days=1),
        revoked_at=_utcnow(),
    )
    assert _row_status(row) == "revoked"


def test_row_status_expired_when_past_expires_at():
    row = AuthToken(
        token_prefix="atr_pat_aaaa",
        token_hash="x",
        scopes=[],
        created_at=_utcnow() - timedelta(days=10),
        expires_at=_utcnow() - timedelta(seconds=1),
    )
    assert _row_status(row) == "expired"


def test_row_status_active_when_expires_at_in_future():
    row = AuthToken(
        token_prefix="atr_pat_aaaa",
        token_hash="x",
        scopes=[],
        created_at=_utcnow(),
        expires_at=_utcnow() + timedelta(days=1),
    )
    assert _row_status(row) == "active"
