"""Demo HTTP surface.

- ``GET /api/__HOST_PKG__/state`` — read-only, auth required.
- ``POST /api/__HOST_PKG__/bump`` — gated by ``__HOST_PKG__.write``,
  increments the demo counter and writes an audit row.

Replace these with your real routes. Atrium mounts every JSON route
under ``/api/...`` so the SPA owns un-prefixed URL space (atrium
issue #89); host routes follow the same contract. The auth
dependencies and the audit/notify helpers (imported from ``app.*``)
are the surface a host calls atrium through.
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

from .models import __BRAND_PASCAL__State

router = APIRouter(prefix="/api/__HOST_PKG__", tags=["__HOST_PKG__"])


class StateOut(BaseModel):
    message: str
    counter: int


async def _load_state(session: AsyncSession) -> __BRAND_PASCAL__State:
    state = (
        await session.execute(
            select(__BRAND_PASCAL__State).where(__BRAND_PASCAL__State.id == 1)
        )
    ).scalar_one_or_none()
    if state is None:
        raise RuntimeError(
            "__HOST_PKG___state row id=1 missing — run the host alembic upgrade",
        )
    return state


@router.get("/state", response_model=StateOut)
async def get_state(
    _user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StateOut:
    state = await _load_state(session)
    return StateOut(message=state.message, counter=state.counter)


@router.post("/bump", response_model=StateOut)
async def bump(
    user: User = Depends(require_perm("__HOST_PKG__.write")),
    session: AsyncSession = Depends(get_session),
) -> StateOut:
    state = await _load_state(session)
    before = state.counter
    state.counter += 1
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="__HOST_PKG___state",
        entity_id=state.id,
        action="bump",
        diff={"counter": {"before": before, "after": state.counter}},
    )
    await session.commit()
    return StateOut(message=state.message, counter=state.counter)
