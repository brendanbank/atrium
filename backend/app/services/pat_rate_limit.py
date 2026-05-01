# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Per-token sliding-window rate limit.

Sized for a single-worker deployment, same posture as
``app.services.rate_limit.AuthRateLimitMiddleware``. Per-token-id deque
of monotonic timestamps; on each successful PAT auth the window is
trimmed and the count compared against the configured per-minute cap.

Limit comes from ``app_settings['pats'].default_rate_limit_per_minute``
(default 600). Read on the hot path through the same ``PatsConfig``
the middleware already loads, so this module never hits the DB itself.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

_WINDOW_SECONDS = 60


class PatSlidingWindow:
    """Bare per-key deque trimmed lazily on each ``check``."""

    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, token_id: int, limit: int) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``.

        ``retry_after`` is when the oldest hit in the window will age
        out — that's the earliest moment a new request would be
        admitted. Always at least 1 s so a Retry-After header makes
        sense.
        """
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        q = self._hits[token_id]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            retry_after = q[0] + _WINDOW_SECONDS - now
            return False, max(int(retry_after) + 1, 1)
        q.append(now)
        return True, 0

    def reset(self, token_id: int | None = None) -> None:
        if token_id is None:
            self._hits.clear()
        else:
            self._hits.pop(token_id, None)


_window = PatSlidingWindow()


def check_rate_limit(token_id: int, limit_per_minute: int) -> tuple[bool, int]:
    """Single entry-point used by ``PATAuthMiddleware``.

    Returns ``(True, 0)`` if the request fits inside the bucket and the
    timestamp was recorded; ``(False, retry_after)`` if the bucket is
    full. The middleware turns the False case into a 429 + Retry-After
    response and an audit row.
    """
    return _window.check(token_id, limit_per_minute)


def reset_for_tests(token_id: int | None = None) -> None:
    """Drop in-memory state so tests can verify the next call clean."""
    _window.reset(token_id)
