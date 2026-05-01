# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

import logging
import re
import sys
from typing import Any

import structlog

from app.settings import get_settings

# A PAT is ``atr_pat_<32 base64url>_<6 base32>`` — see
# ``app.auth.pat_format``. We match the prefix plus any run of the
# alphabet either body half uses (base64url + ``_`` separator + base32);
# this is intentionally generous so a single regex catches both the
# full 47-char token and any truncated/concatenated form an operator
# might have logged by accident.
_PAT_TOKEN_RE = re.compile(r"atr_pat_[A-Za-z0-9_-]+")
_REDACTION_TAG = "***REDACTED***"


def _redact_pat_match(match: re.Match[str]) -> str:
    """Keep the 12-char lookup prefix (``atr_pat_`` + 4 secret chars)
    when the captured run is long enough to contain it. The lookup
    prefix is also what ``auth_tokens.token_prefix`` stores, so a
    redacted log line still correlates to a row in the DB. Anything
    shorter is collapsed entirely — there's no useful identifier
    left."""
    full = match.group(0)
    if len(full) > 12:
        return f"{full[:12]}{_REDACTION_TAG}"
    return _REDACTION_TAG


def _redact_value(value: Any) -> Any:
    """Walk ``value`` and replace every ``atr_pat_*`` substring with
    a redaction tag. Strings get an in-place regex sub; mappings and
    sequences are recursed; everything else passes through.

    The recursion preserves the container type (``dict``, ``list``,
    ``tuple``) so structured headers / payloads survive intact —
    only the secret is masked. ``set`` and ``frozenset`` are also
    walked, but they're unusual in log payloads."""
    if isinstance(value, str):
        return _PAT_TOKEN_RE.sub(_redact_pat_match, value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(v) for v in value)
    return value


def redact_pat_tokens(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor that strips ``atr_pat_*`` from every field.

    Catches the obvious leak channels (a stray ``Authorization``
    header, a request body printed in a debug log, a token spliced
    into an exception message) without forcing each call site to
    remember to scrub. The processor is keyed on the token prefix
    only — it doesn't try to recognise password fields or other
    secrets, since those have no stable wire shape to match on."""
    return {key: _redact_value(value) for key, value in event_dict.items()}


def configure_logging() -> None:
    settings = get_settings()
    level = logging.DEBUG if settings.environment == "dev" else logging.INFO

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_pat_tokens,
    ]
    if settings.environment == "dev":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
