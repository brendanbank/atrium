# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime

from pydantic import BaseModel, Field


class EmailTemplateRead(BaseModel):
    """Single (key, locale) row.

    The flat shape lets the admin UI group by ``key`` client-side
    without a second round-trip. ``description`` is only meaningful on
    the EN row by convention; translated rows leave it null.
    """

    key: str
    locale: str
    subject: str
    body_html: str
    description: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmailTemplateUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    body_html: str | None = Field(default=None, min_length=1)
    description: str | None = None
