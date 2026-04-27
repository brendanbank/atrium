# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationRead(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCount(BaseModel):
    count: int
