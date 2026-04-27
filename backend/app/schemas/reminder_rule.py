# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReminderKind = Literal["down_payment", "final_payment", "option_expiry", "other"]
ReminderAnchor = Literal[
    "booking_creation",
    "booking_arrival",
    "booking_departure",
    "option_expiry",
]


class ReminderRuleRead(BaseModel):
    id: int
    name: str
    template_key: str
    kind: ReminderKind
    anchor: ReminderAnchor
    days_offset: int
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReminderRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template_key: str
    kind: ReminderKind
    anchor: ReminderAnchor
    days_offset: int = Field(ge=-365, le=365)
    active: bool = True


class ReminderRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    template_key: str | None = None
    kind: ReminderKind | None = None
    anchor: ReminderAnchor | None = None
    days_offset: int | None = Field(default=None, ge=-365, le=365)
    active: bool | None = None
