# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""In-process pub/sub for server-sent notification events.

One asyncio.Queue per connection, keyed by user id. Multiple open
tabs for the same user each get their own queue, so all of them see
the event.

Single-process only: publishes go to subscribers in the same Python
process. With more than one API worker (or a horizontal deploy) this
needs Redis pub/sub as the transport. For our single-worker setup it
is enough and adds no external dependencies.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.logging import log


class _Hub:
    def __init__(self) -> None:
        self._subs: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, user_id: int) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subs[user_id].add(q)
        return q

    def unsubscribe(self, user_id: int, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q in self._subs.get(user_id, ()):
            self._subs[user_id].discard(q)
        if user_id in self._subs and not self._subs[user_id]:
            del self._subs[user_id]

    def publish(self, user_id: int, event: dict[str, Any]) -> None:
        """Fan-out. Drop the event on any queue that is full instead of
        blocking — the client will catch up on its next refetch."""
        queues = list(self._subs.get(user_id, ()))
        log.info(
            "event_hub.publish", user_id=user_id, subscribers=len(queues)
        )
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - best-effort
                continue


hub = _Hub()
