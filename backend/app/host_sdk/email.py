# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side email helpers.

A thin re-export of the platform's outbox primitives so a host bundle
that wants to surface its own "send now" button on a domain-side outbox
view can call the same code path the cron worker uses, without
copy-pasting the render-and-send-and-update-status logic from
``app.jobs.builtin_handlers``.

Example::

    from fastapi import APIRouter, Depends, HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db import get_session
    from app.host_sdk.email import drain_outbox_row

    @router.post("/bookings/{booking_id}/resend-confirmation")
    async def resend(booking_id: int, session: AsyncSession = Depends(get_session)):
        outbox_id = ...  # look up the queued row for this booking
        row = await drain_outbox_row(session, outbox_id)
        if row is None:
            raise HTTPException(404)
        await session.commit()
        return {"status": row.status}

The caller owns the transaction — ``drain_outbox_row`` flushes but
does not commit.
"""

from __future__ import annotations

from app.jobs.builtin_handlers import drain_outbox_row

__all__ = ["drain_outbox_row"]
