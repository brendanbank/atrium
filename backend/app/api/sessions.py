# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Session-management endpoints that live above fastapi-users.

``/auth/logout-all`` revokes every active session for the current
user in one shot (the "my phone got stolen" button). ``/auth/sessions``
lists the active ones so the profile page can show where you're
signed in. Cookie on the current tab is cleared at the end of
logout-all so the caller is logged out too.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import _now_naive
from app.auth.users import current_user
from app.db import get_session
from app.models.auth import User
from app.models.auth_session import AuthSession

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthSessionRead(BaseModel):
    id: int
    session_id: str
    issued_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip: str | None
    # Derived flag so the UI can mark the row the caller is on.
    is_current: bool


@router.get("/sessions", response_model=list[AuthSessionRead])
async def list_active_sessions(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AuthSessionRead]:
    """Active sessions for the calling user. Ordered newest first."""
    rows = list(
        (
            await session.execute(
                select(AuthSession)
                .where(
                    AuthSession.user_id == user.id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > _now_naive(),
                )
                .order_by(AuthSession.issued_at.desc())
            )
        )
        .scalars()
        .all()
    )

    # Pull the current session_id from the JWT in the cookie so the
    # UI can label "this device". We decode defensively — a stale
    # cookie just leaves is_current=False everywhere.
    current_sid = _current_sid(request)

    return [
        AuthSessionRead(
            id=r.id,
            session_id=r.session_id,
            issued_at=r.issued_at,
            expires_at=r.expires_at,
            user_agent=r.user_agent,
            ip=r.ip,
            is_current=r.session_id == current_sid,
        )
        for r in rows
    ]


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke every active session for the calling user, including
    the one that made this call. Clears the auth cookie so the
    browser is logged out too."""
    await session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now_naive())
    )
    await session.commit()
    # Match the cookie attributes the transport set at login so the
    # browser actually drops it. Using the same cookie name as
    # ``app.auth.backend._cookie_transport``.
    response.delete_cookie(
        key="atrium_auth",
        httponly=True,
        samesite="lax",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _current_sid(request: Request) -> str | None:
    """Best-effort extract of the ``sid`` claim from the auth cookie
    without re-verifying (this endpoint's caller is already
    authenticated via ``current_user`` so the cookie's validity is
    given; we just want the claim to mark one row)."""
    import jwt as pyjwt

    token = request.cookies.get("atrium_auth")
    if not token:
        return None
    try:
        data = pyjwt.decode(token, options={"verify_signature": False})
        return data.get("sid")
    except Exception:
        return None
