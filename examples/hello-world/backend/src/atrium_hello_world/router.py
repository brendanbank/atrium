# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""HTTP surface for the Hello World demo.

- ``GET /hello/state`` — read-only state. Auth required so the widget
  has a real user identity, but no special permission.
- ``POST /hello/toggle`` — gated by the ``hello.toggle`` permission
  (seeded by the alembic migration). Writes an audit row.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_perm
from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User
from app.services.audit import record as record_audit

from .models import HelloState

router = APIRouter(prefix="/hello", tags=["hello-world"])


class StateOut(BaseModel):
    message: str
    counter: int
    enabled: bool


class ToggleIn(BaseModel):
    enabled: bool


async def _load_state(session: AsyncSession) -> HelloState:
    state = (
        await session.execute(select(HelloState).where(HelloState.id == 1))
    ).scalar_one_or_none()
    if state is None:
        # The migration seeds row id=1; a missing row means the host
        # alembic wasn't run. Surface it loudly rather than silently
        # creating a row that bypasses the seed defaults.
        raise RuntimeError(
            "hello_state row id=1 missing — run the host alembic upgrade",
        )
    return state


@router.get("/state", response_model=StateOut)
async def get_state(
    _user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StateOut:
    state = await _load_state(session)
    return StateOut(
        message=state.message,
        counter=state.counter,
        enabled=state.enabled,
    )


@router.post("/toggle", response_model=StateOut)
async def toggle(
    body: ToggleIn,
    user: User = Depends(require_perm("hello.toggle")),
    session: AsyncSession = Depends(get_session),
) -> StateOut:
    state = await _load_state(session)
    before = state.enabled
    state.enabled = body.enabled
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="hello_state",
        entity_id=state.id,
        action="toggle",
        diff={"enabled": {"before": before, "after": body.enabled}},
    )
    await session.commit()
    return StateOut(
        message=state.message,
        counter=state.counter,
        enabled=state.enabled,
    )
