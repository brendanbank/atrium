# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests for the PAT argon2 wrapper.

Argon2 verification is intentionally slow (~50-150 ms). These tests
keep the count low so the suite isn't dominated by hashing time.
"""
from __future__ import annotations

from app.auth.pat_format import generate_token
from app.auth.pat_hashing import hash_token, verify_token


def test_hash_round_trip():
    token, _ = generate_token()
    encoded = hash_token(token)
    assert verify_token(token, encoded) is True


def test_distinct_tokens_yield_distinct_hashes():
    """argon2's salt randomisation means even identical inputs hash
    to different encoded forms; distinct inputs definitely should."""
    a, _ = generate_token()
    b, _ = generate_token()
    assert hash_token(a) != hash_token(b)


def test_same_token_yields_distinct_hashes_per_call():
    """Salt-per-call: calling ``hash_token`` twice with the same token
    must NOT produce the same encoded form. If it did, the salt would
    be deterministic, defeating the rainbow-table protection that's
    the whole point of using argon2id."""
    token, _ = generate_token()
    assert hash_token(token) != hash_token(token)


def test_verify_rejects_wrong_token():
    a, _ = generate_token()
    b, _ = generate_token()
    assert verify_token(a, hash_token(b)) is False


def test_verify_rejects_garbage_hash():
    """A malformed hash must not raise — the auth middleware would
    propagate that as a 500 instead of a clean 401."""
    token, _ = generate_token()
    assert verify_token(token, "not-an-argon2-hash") is False
    assert verify_token(token, "") is False


def test_verify_rejects_empty_token():
    token, _ = generate_token()
    encoded = hash_token(token)
    assert verify_token("", encoded) is False
