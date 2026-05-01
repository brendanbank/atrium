# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests for ``app.logging.redact_pat_tokens``.

A leaked PAT is a credential leak. The structlog processor scrubs
``atr_pat_*`` substrings from every field in the event dict so a
request body or ``Authorization`` header that ends up in a log line
doesn't carry a usable token. The 12-char lookup prefix is preserved
because it matches ``auth_tokens.token_prefix`` — the operator can
correlate a redacted log line to a row, but cannot recover the
secret.
"""
from __future__ import annotations

import json

import structlog

from app.auth.pat_format import generate_token
from app.logging import (
    _PAT_TOKEN_RE,
    _REDACTION_TAG,
    redact_pat_tokens,
)

# ---- the regex itself ---------------------------------------------------


def test_regex_matches_full_token():
    full, _ = generate_token()
    assert _PAT_TOKEN_RE.fullmatch(full) is not None


def test_regex_does_not_match_unrelated_strings():
    assert _PAT_TOKEN_RE.search("hello world") is None
    assert _PAT_TOKEN_RE.search("atrium_audit_log") is None
    # Bare prefix without any secret body is not a token.
    assert _PAT_TOKEN_RE.search("atr_pat_") is None


# ---- redaction processor ------------------------------------------------


def test_redacts_bare_token_in_string_field():
    full, prefix = generate_token()
    event = {"event": f"saw token {full}", "level": "info"}

    result = redact_pat_tokens(None, "info", event)

    assert full not in result["event"]
    assert _REDACTION_TAG in result["event"]
    # Lookup prefix preserved for correlation with auth_tokens.token_prefix.
    assert prefix in result["event"]


def test_redacts_authorization_header_value():
    full, prefix = generate_token()
    event = {
        "event": "request",
        "headers": {"Authorization": f"Bearer {full}", "X-Other": "ok"},
    }

    result = redact_pat_tokens(None, "info", event)

    assert full not in result["headers"]["Authorization"]
    assert prefix in result["headers"]["Authorization"]
    assert result["headers"]["Authorization"].startswith("Bearer atr_pat_")
    # Untouched fields survive untouched.
    assert result["headers"]["X-Other"] == "ok"
    assert result["event"] == "request"


def test_redacts_inside_nested_lists_and_tuples():
    full, _ = generate_token()
    event = {
        "items": [f"prefix {full} suffix", "no token here"],
        "pair": (full, "ok"),
    }

    result = redact_pat_tokens(None, "info", event)

    assert full not in result["items"][0]
    assert _REDACTION_TAG in result["items"][0]
    assert result["items"][1] == "no token here"
    # Tuple shape preserved.
    assert isinstance(result["pair"], tuple)
    assert full not in result["pair"][0]
    assert result["pair"][1] == "ok"


def test_redacts_multiple_tokens_in_one_string():
    full_a, _ = generate_token()
    full_b, _ = generate_token()
    event = {"event": f"a={full_a} b={full_b}"}

    result = redact_pat_tokens(None, "info", event)

    assert full_a not in result["event"]
    assert full_b not in result["event"]
    assert result["event"].count(_REDACTION_TAG) == 2


def test_passes_non_string_values_through():
    event = {"count": 42, "active": True, "extra": None}
    assert redact_pat_tokens(None, "info", event) == event


def test_short_prefix_only_match_is_collapsed_entirely():
    # ``atr_pat_`` + 1 secret char isn't long enough to contain a
    # useful 12-char correlation prefix; collapse it completely so
    # nothing leaks.
    event = {"event": "atr_pat_x"}

    result = redact_pat_tokens(None, "info", event)

    assert result["event"] == _REDACTION_TAG


# ---- integration with the structlog renderer ----------------------------


def test_processor_chain_redacts_through_json_renderer():
    """Wire the processor up like ``configure_logging`` does and
    confirm the rendered JSON line carries no plaintext token."""
    full, prefix = generate_token()
    structlog.configure(
        processors=[
            redact_pat_tokens,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        cache_logger_on_first_use=False,
    )
    try:
        captured: list[str] = []

        class _Capture:
            def msg(self, message: str) -> None:
                captured.append(message)

            info = msg

        logger = structlog.wrap_logger(_Capture())
        logger.info("inbound", auth=f"Bearer {full}")
    finally:
        structlog.reset_defaults()

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert full not in captured[0]
    assert _REDACTION_TAG in payload["auth"]
    assert prefix in payload["auth"]
