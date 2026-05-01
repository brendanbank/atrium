# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit-test the scope-intersection invariant.

The middleware computes ``effective_scopes = stored_scopes ∩ user_perms``
on every request — a token can never do what its issuing user cannot.
Tested directly against the formula here so the invariant doesn't
need a full request-flow harness to verify.
"""
from __future__ import annotations


def _intersect(stored: list[str], user_perms: set[str]) -> frozenset[str]:
    """Replicate the middleware's intersection step for unit testing."""
    return frozenset(stored or []) & user_perms


def test_full_overlap_keeps_all_scopes():
    stored = ["pa.read", "pa.write"]
    user = {"pa.read", "pa.write", "user.manage"}
    assert _intersect(stored, user) == frozenset({"pa.read", "pa.write"})


def test_user_demotion_silently_drops_lost_scopes():
    """The driving safety property: when the user loses a permission,
    every existing token of theirs immediately loses the matching
    scope without any token-side bookkeeping."""
    stored = ["pa.read", "pa.write"]
    # Originally the user had both; now they're demoted and only
    # have ``pa.read``.
    user_after_demotion = {"pa.read"}
    assert _intersect(stored, user_after_demotion) == frozenset({"pa.read"})


def test_scope_not_held_by_user_is_dropped():
    """A scope stored on the token but not currently held by the user
    is never honoured — even if it was held at issue time and then
    revoked. The stored list is a cap, not a freeze."""
    stored = ["pa.read", "pa.write", "audit.read"]
    user = {"pa.read"}
    assert _intersect(stored, user) == frozenset({"pa.read"})


def test_empty_stored_scopes_yields_empty_set():
    assert _intersect([], {"pa.read"}) == frozenset()


def test_empty_user_perms_yields_empty_set():
    assert _intersect(["pa.read"], set()) == frozenset()


def test_intersection_returns_frozenset():
    """Principal.permissions is typed as frozenset[str]; the
    intersection helper must produce one (not a plain set) so the
    Principal can stay frozen/hashable."""
    result = _intersect(["pa.read"], {"pa.read"})
    assert isinstance(result, frozenset)
