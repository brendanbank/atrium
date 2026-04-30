# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime

from pydantic import BaseModel, Field

# ``kind`` and ``anchor`` are free-form strings: atrium ships only the
# storage + admin UI; the host app decides what valid anchors / kinds
# are and writes the logic that turns a rule into a scheduled job.
# (CLAUDE.md, "Scheduled jobs" section.)
#
# Earlier revisions of this file constrained both fields with
# ``Literal[...]`` enums baked from one specific host app's domain
# (booking_arrival / down_payment / etc.). That broke the documented
# free-form contract and 422'd every create from the admin UI.


class ReminderRuleRead(BaseModel):
    id: int
    name: str
    template_key: str
    kind: str
    anchor: str
    days_offset: int
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReminderRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template_key: str
    kind: str = Field(default="", max_length=50)
    anchor: str = Field(min_length=1, max_length=50)
    days_offset: int = Field(ge=-365, le=365)
    active: bool = True


class ReminderRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    template_key: str | None = None
    kind: str | None = Field(default=None, max_length=50)
    anchor: str | None = Field(default=None, min_length=1, max_length=50)
    days_offset: int | None = Field(default=None, ge=-365, le=365)
    active: bool | None = None
