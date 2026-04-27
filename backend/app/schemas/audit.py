# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: int
    actor_user_id: int | None
    actor_email: str | None
    entity: str
    entity_id: int
    action: str
    diff: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
