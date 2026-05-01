# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests for the PAT wire-format module."""
from __future__ import annotations

import pytest

from app.auth.pat_format import (
    LOOKUP_PREFIX_LEN,
    PREFIX,
    TOKEN_LEN,
    generate_token,
    lookup_prefix,
    validate_format,
)


def test_generate_returns_valid_format():
    token, prefix = generate_token()
    assert token.startswith(PREFIX)
    assert len(token) == TOKEN_LEN
    assert len(prefix) == LOOKUP_PREFIX_LEN
    assert token.startswith(prefix)
    assert validate_format(token) is True


def test_generate_returns_unique_tokens():
    """A million-row collision is wildly improbable; even 100 tokens
    sharing a prefix is improbable. This sanity-checks the entropy
    source — if ``secrets.token_bytes`` were misconfigured we'd see
    duplicates fast."""
    tokens = {generate_token()[0] for _ in range(50)}
    assert len(tokens) == 50


def test_lookup_prefix_matches_first_12():
    token, prefix = generate_token()
    assert lookup_prefix(token) == prefix
    assert lookup_prefix(token) == token[:12]


def test_validate_rejects_wrong_prefix():
    assert validate_format("ghp_abc123") is False
    assert validate_format("Bearer atr_pat_…") is False
    assert validate_format("") is False


def test_validate_rejects_wrong_length():
    # Truncate a known-good token by 1 char.
    token, _ = generate_token()
    assert validate_format(token[:-1]) is False
    # Append a char.
    assert validate_format(token + "x") is False


def test_validate_rejects_corrupted_secret():
    """A 1-bit flip in the secret breaks the CRC."""
    token, _ = generate_token()
    # Flip a char in the secret region (between PREFIX and the CRC).
    body, _, crc = token.rpartition("_")
    body_chars = list(body)
    # Pick a char near the end of the secret to mutate; bump the
    # ASCII code by one, wrap around alphabetic range.
    idx = len(body) - 1
    orig = body_chars[idx]
    body_chars[idx] = "A" if orig != "A" else "B"
    bad = "".join(body_chars) + "_" + crc
    assert validate_format(bad) is False


def test_validate_rejects_corrupted_crc():
    token, _ = generate_token()
    body, _, crc = token.rpartition("_")
    # Replace the CRC with a different valid-looking 6-char string.
    bad_crc = "a" * 6 if crc != "a" * 6 else "b" * 6
    assert validate_format(f"{body}_{bad_crc}") is False


@pytest.mark.parametrize(
    "candidate",
    [
        "atr_pat_",  # prefix only
        "atr_pat__abc",  # underscore but no body
        "atr_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx_",  # missing CRC
    ],
)
def test_validate_rejects_malformed(candidate):
    assert validate_format(candidate) is False
