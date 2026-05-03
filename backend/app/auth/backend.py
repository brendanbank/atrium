# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""JWT auth backend with httpOnly cookie transport, backed by a
server-side ``auth_sessions`` row.

Difference from stock fastapi-users: the JWT carries a ``sid`` claim
in addition to ``sub``. On login we open a session row; on read we
look it up and reject if missing / revoked / expired; on logout we
flip ``revoked_at`` on that row. The strategy therefore honours
``POST /auth/jwt/logout`` for real, and a new ``/auth/logout-all``
endpoint (see ``app.api.sessions``) can revoke every session for a
user at once.

Frontend never sees the token in JS — browser carries it for
same-origin requests; CORS dev uses ``withCredentials``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

import jwt
from fastapi import Depends
from fastapi_users import exceptions
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.jwt import decode_jwt, generate_jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import log
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.settings import get_settings


def _cookie_transport() -> CookieTransport:
    settings = get_settings()
    return CookieTransport(
        cookie_name="atrium_auth",
        cookie_max_age=settings.jwt_access_token_expire_minutes * 60,
        cookie_secure=settings.environment == "prod",
        cookie_httponly=True,
        cookie_samesite="lax",
    )


def _now_naive() -> datetime:
    # DB columns are naive DATETIME(0) in UTC — strip tz here so
    # comparisons in SQL are straightforward.
    return datetime.utcnow()


async def _idle_timeout_seconds(session: AsyncSession) -> int:
    """Resolve ``auth.idle_timeout_seconds`` from app_settings.

    Imported lazily to dodge a startup import cycle (``app_config``
    pulls in pydantic models that reference ``app.models``, which is
    fine, but keeping the indirection here means the auth backend can
    be unit-imported without dragging the namespace registry along).
    Returns ``0`` (disabled) on any read error so a transient DB
    blip never locks every session out — fail-open mirrors the HIBP /
    captcha middlewares.
    """
    from app.services.app_config import get_namespace

    try:
        cfg = await get_namespace(session, "auth")
    except Exception:
        return 0
    return int(getattr(cfg, "idle_timeout_seconds", 0) or 0)


class DBSessionJWTStrategy(JWTStrategy[User, int]):
    """``JWTStrategy`` that writes a row per issued token and rejects
    tokens whose row is missing / revoked / expired.

    The SQLAlchemy session comes in via FastAPI's DI so that
    ``dependency_overrides[get_session]`` in tests is honoured
    transparently — and so we share the same engine/pool/event loop as
    the rest of the request.

    Load cost: one indexed SELECT per authenticated request. For a
    two-user app this is noise; if it ever becomes hot, a tiny
    per-worker LRU keyed on ``session_id`` gets us most of the way
    back to stateless at a tunable staleness.
    """

    def __init__(self, *, session: AsyncSession, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session = session

    async def write_token(self, user: User) -> str:
        session_id = str(uuid4())
        issued_at = _now_naive()
        expires_at = issued_at + timedelta(seconds=self.lifetime_seconds)

        # 2FA is opt-in: a user with no confirmed factor and no role on
        # ``auth.require_2fa_for_roles`` gets a full session straight
        # out of password login. Anyone with a confirmed factor must
        # challenge (``current_user`` raises ``totp_required`` →
        # frontend routes to /2fa); anyone holding an enforced role
        # without a factor must enrol (``2fa_enrollment_required``).
        # Operators who want the legacy "everyone must enrol" posture
        # populate ``require_2fa_for_roles`` with every role code.
        from app.auth.two_factor import login_grants_full_session

        full = await login_grants_full_session(self._session, user.id)
        self._session.add(
            AuthSession(
                session_id=session_id,
                user_id=user.id,
                issued_at=issued_at,
                expires_at=expires_at,
                totp_passed=full,
            )
        )
        await self._session.commit()

        data = {
            "sub": str(user.id),
            "sid": session_id,
            "aud": self.token_audience,
        }
        return generate_jwt(
            data,
            self.encode_key,
            self.lifetime_seconds,
            algorithm=self.algorithm,
        )

    async def read_token(
        self, token: str | None, user_manager
    ) -> User | None:
        if token is None:
            return None

        try:
            data = decode_jwt(
                token,
                self.decode_key,
                self.token_audience,
                algorithms=[self.algorithm],
            )
            user_id = data.get("sub")
            session_id = data.get("sid")
            if user_id is None or session_id is None:
                # Either a pre-DB-session JWT (legacy) or a forged
                # token without ``sid`` — refuse.
                return None
        except jwt.PyJWTError:
            return None

        row = (
            await self._session.execute(
                select(AuthSession).where(AuthSession.session_id == session_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.revoked_at is not None:
            return None
        now = _now_naive()
        if row.expires_at <= now:
            return None

        # Idle-session timeout. ``auth.idle_timeout_seconds == 0`` is the
        # disable sentinel; any positive value rejects sessions whose
        # ``last_seen_at`` watermark is older than the threshold. Read
        # the namespace inline — one extra cached SELECT on the hot
        # path, but it keeps the gate honest when the admin flips the
        # knob mid-session.
        idle_limit = await _idle_timeout_seconds(self._session)
        if idle_limit > 0 and row.last_seen_at is not None:
            idle_for = (now - row.last_seen_at).total_seconds()
            if idle_for > idle_limit:
                # Mark the row revoked so a follow-up logout-all /
                # active-sessions list doesn't keep showing it as
                # alive. Self-heals state without waiting for a
                # background sweep.
                await self._session.execute(
                    update(AuthSession)
                    .where(AuthSession.id == row.id)
                    .values(revoked_at=now)
                )
                await self._session.commit()
                return None

        # Touch the watermark so the next request resets the idle clock.
        # Done unconditionally (even when the timeout is disabled) so an
        # operator who flips the knob on later starts with a fresh,
        # accurate watermark on every active session.
        await self._session.execute(
            update(AuthSession)
            .where(AuthSession.id == row.id)
            .values(last_seen_at=now)
        )
        await self._session.commit()

        try:
            parsed_id = user_manager.parse_id(user_id)
            return await user_manager.get(parsed_id)
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None

    async def destroy_token(self, token: str, user: User) -> None:
        """Called by fastapi-users on ``POST /auth/jwt/logout``.

        Stock JWTStrategy raises here ("stateless tokens can't be
        destroyed"); we use the sid claim to flip the session's
        ``revoked_at`` instead so the logout is real.
        """
        try:
            data = decode_jwt(
                token,
                self.decode_key,
                self.token_audience,
                algorithms=[self.algorithm],
            )
            session_id = data.get("sid")
        except jwt.PyJWTError:
            return
        if not session_id:
            return

        await self._session.execute(
            update(AuthSession)
            .where(
                AuthSession.session_id == session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=_now_naive())
        )
        await self._session.commit()
        log.info("auth.session.revoked", session_id=session_id, user_id=user.id)


def _jwt_strategy(
    session: AsyncSession = Depends(get_session),
) -> DBSessionJWTStrategy:
    settings = get_settings()
    return DBSessionJWTStrategy(
        session=session,
        secret=settings.jwt_secret,
        lifetime_seconds=settings.jwt_access_token_expire_minutes * 60,
    )


auth_backend = AuthenticationBackend(
    name="jwt_cookie",
    transport=_cookie_transport(),
    get_strategy=cast("type[JWTStrategy[User, int]]", _jwt_strategy),
)
