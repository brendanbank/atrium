# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Password-policy validation backed by ``AuthConfig``.

A single entry point — :func:`validate_password_against_policy` — reads
the live ``auth`` namespace and raises
:class:`fastapi_users.exceptions.InvalidPasswordException` for any
violated rule. Re-using the fastapi-users exception keeps the failure
surface consistent with the existing register / accept-invite flows
(both already render the exception's ``reason`` verbatim).

The HIBP check uses the k-anonymity range API: we send the first 5
chars of the SHA-1 hash and look for the suffix in the response. The
suffix is what marks a password as breached, never the full hash.

Network outages on HIBP are treated as fail-open — the alternative
would mean an upstream incident at HIBP locks every user out of
registration, which is worse than a transient policy gap.

Caching is in-memory and per-prefix with a 5-minute TTL. A burst of
registrations sharing the same SHA-1 prefix (rare, 1 / 16^5 chance)
won't hammer HIBP. Process restarts wipe it, which is fine — HIBP is
itself rate-limited and a fresh cache is correct on cold start.
"""
from __future__ import annotations

import hashlib
import string
import time

import httpx
from fastapi_users.exceptions import InvalidPasswordException
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import log
from app.services.app_config import AuthConfig, get_namespace

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
_HIBP_TIMEOUT_SECONDS = 3.0
_HIBP_CACHE_TTL_SECONDS = 300

# prefix -> (expires_at_monotonic, set_of_suffix:count_lines_upper)
_hibp_cache: dict[str, tuple[float, set[str]]] = {}


def _has_upper_and_lower(password: str) -> bool:
    return any(c.isupper() for c in password) and any(c.islower() for c in password)


def _has_digit(password: str) -> bool:
    return any(c.isdigit() for c in password)


def _has_symbol(password: str) -> bool:
    # ``string.punctuation`` is the conservative ASCII baseline; any
    # non-alnum codepoint also counts so passphrases with unicode
    # separators don't get rejected.
    return any(
        (c in string.punctuation) or (not c.isalnum() and not c.isspace())
        for c in password
    )


async def _hibp_suffixes_for_prefix(prefix: str) -> set[str] | None:
    """Return the suffix set for ``prefix`` from HIBP, or ``None`` on
    network failure (caller treats None as fail-open)."""
    now = time.monotonic()
    cached = _hibp_cache.get(prefix)
    if cached is not None and cached[0] > now:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=_HIBP_TIMEOUT_SECONDS) as client:
            resp = await client.get(_HIBP_RANGE_URL.format(prefix=prefix))
            resp.raise_for_status()
    except Exception as exc:
        # Fail-open: log so an operator can spot a sustained outage,
        # but don't block password creation on an external dependency.
        log.warning("password_policy.hibp_unreachable", error=str(exc))
        return None

    suffixes: set[str] = set()
    for line in resp.text.splitlines():
        # Each line is "SUFFIX:count" — we only care about the suffix,
        # uppercased to match ``hexdigest().upper()``.
        suffix = line.split(":", 1)[0].strip().upper()
        if suffix:
            suffixes.add(suffix)
    _hibp_cache[prefix] = (now + _HIBP_CACHE_TTL_SECONDS, suffixes)
    return suffixes


async def _password_is_breached(password: str) -> bool:
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    suffixes = await _hibp_suffixes_for_prefix(prefix)
    if suffixes is None:
        return False  # fail-open
    return suffix in suffixes


async def validate_password_against_policy(
    session: AsyncSession, password: str
) -> None:
    """Check ``password`` against the live auth-policy config.

    Raises :class:`InvalidPasswordException` with a human-readable
    ``reason`` for the first failed rule. The order is deliberate:
    cheap structural checks first, breach lookup last so a malformed
    password doesn't trigger a network round-trip.
    """
    cfg = await get_namespace(session, "auth")
    if not isinstance(cfg, AuthConfig):
        # Defensive — get_namespace always returns the registered model
        # but a future refactor could change that.
        return

    if len(password) < cfg.password_min_length:
        raise InvalidPasswordException(
            reason=(
                f"password must be at least {cfg.password_min_length} "
                "characters"
            )
        )

    if cfg.password_require_mixed_case and not _has_upper_and_lower(password):
        raise InvalidPasswordException(
            reason="password must contain both upper and lower case letters"
        )

    if cfg.password_require_digit and not _has_digit(password):
        raise InvalidPasswordException(
            reason="password must contain at least one digit"
        )

    if cfg.password_require_symbol and not _has_symbol(password):
        raise InvalidPasswordException(
            reason="password must contain at least one symbol"
        )

    if cfg.password_check_breach and await _password_is_breached(password):
        raise InvalidPasswordException(
            reason="password appears in known breach data; choose another"
        )


def _reset_hibp_cache_for_tests() -> None:
    """Test hook — wipe the in-memory cache so a monkeypatch in one
    test doesn't bleed into another."""
    _hibp_cache.clear()
