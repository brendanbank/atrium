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

        # Every login starts partial. ``current_user_full`` rejects
        # partial sessions with a 403 ``totp_required``, which the
        # frontend turns into a redirect to /2fa. From there:
        #   * Users who already have a confirmed TOTP or email-OTP
        #     land on the challenge screen → ``/auth/*/verify``
        #     flips ``totp_passed`` to True.
        #   * Users with no confirmed method land on the setup picker
        #     → ``/auth/*/confirm`` does the same flip after enrollment.
        # We never grant a full session straight out of password login
        # — that bypass let unenrolled users skip 2FA entirely.
        self._session.add(
            AuthSession(
                session_id=session_id,
                user_id=user.id,
                issued_at=issued_at,
                expires_at=expires_at,
                totp_passed=False,
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
        if row.expires_at <= _now_naive():
            return None

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
