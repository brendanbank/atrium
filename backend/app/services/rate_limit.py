# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Tiny in-memory sliding-window rate limiter.

Sized for a single-worker deployment. The bucket is a per-key deque of
request timestamps; on each hit we trim anything older than the
window and count what's left. No cross-process coordination (we
don't need it — one uvicorn worker), no persistence across restarts
(fine — limits are short-lived), no Redis.

Keyed by client IP (from ``request.client.host``, with nginx already
rewriting X-Forwarded-For upstream so this is the real client).

Limits live in ``AUTH_LIMITS`` and apply to specific ``(METHOD, path)``
pairs only; every other request is untouched.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.settings import get_settings

# Each entry: (METHOD, path) → (max_requests, window_seconds)
# Keep these strict — the legitimate user-facing cost of a wrong
# password is ~4 retries spread over a minute (typo, caps-lock, wrong
# password manager entry). Five is plenty.
AUTH_LIMITS: dict[tuple[str, str], tuple[int, int]] = {
    ("POST", "/auth/jwt/login"): (5, 60),
    ("POST", "/auth/forgot-password"): (3, 60),
    ("POST", "/auth/reset-password"): (10, 60),
    ("POST", "/invites/accept"): (10, 60),
    # Self-serve signup. Tighter than reset because every successful
    # call creates a User row + sends an email; 3/min is enough for a
    # legitimate retry after a typo.
    ("POST", "/auth/register"): (3, 60),
    ("POST", "/auth/verify-email"): (10, 60),
}


class _SlidingWindow:
    """Per-key request timestamps, trimmed to the active window."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: int) -> bool:
        """Return True if the request is allowed; records it if so.

        False means the caller should respond 429 without processing.
        """
        now = time.monotonic()
        cutoff = now - window
        q = self._hits[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


_window = _SlidingWindow()


def _client_ip(request: Request) -> str:
    # nginx rewrites X-Forwarded-For → client.host upstream via
    # set_real_ip_from, so request.client.host is already the real
    # client IP in prod. In dev (direct hit to uvicorn) it's the
    # docker bridge, which is fine for per-caller limiting.
    return request.client.host if request.client else "unknown"


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit the narrow set of auth endpoints in ``AUTH_LIMITS``.

    Every other request falls through untouched. A limited request
    short-circuits with 429 + a Retry-After header.

    Active only when ``environment='prod'`` — dev iterates too fast
    and tests log in dozens of times per run, both of which would
    trip the limits and not actually reflect the attack scenario the
    limiter exists to stop.
    """

    async def dispatch(self, request: Request, call_next):
        if get_settings().environment != "prod":
            return await call_next(request)

        limit = AUTH_LIMITS.get((request.method, request.url.path))
        if limit is None:
            return await call_next(request)

        max_requests, window = limit
        key = f"{request.method}:{request.url.path}:{_client_ip(request)}"
        if not _window.check(key, max_requests, window):
            return Response(
                content='{"detail":"rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(window)},
            )
        return await call_next(request)
