# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime

from pydantic import BaseModel


class EmailOutboxRow(BaseModel):
    """Admin view of one ``email_outbox`` row.

    The ``context`` JSON the worker re-renders against is intentionally
    omitted — it can be large and may contain user PII a viewer with
    only ``email_outbox.manage`` shouldn't see incidentally. The Email
    log + audit log together are the source of truth for "what was sent".
    """

    id: int
    template: str
    to_addr: str
    locale: str
    status: str
    attempts: int
    last_error: str | None
    next_attempt_at: datetime
    created_at: datetime
    updated_at: datetime
    entity_type: str | None
    entity_id: int | None

    model_config = {"from_attributes": True}


class EmailOutboxPage(BaseModel):
    items: list[EmailOutboxRow]
    total: int


class DrainResult(BaseModel):
    """Returned by ``POST /admin/email-outbox/{id}/drain``.

    ``status`` reflects the row's terminal state after the synchronous
    send attempt: ``sent`` (delivered), ``pending`` (transient failure
    — backoff retry scheduled), or ``dead`` (exhausted retries — moved
    to dead-letter)."""

    id: int
    status: str
    attempts: int
    last_error: str | None
    next_attempt_at: datetime
