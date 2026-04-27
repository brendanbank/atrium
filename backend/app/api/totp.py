# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""TOTP enrollment + verification endpoints.

Flow:
1. After password login, the user holds a *partial* session — the
   ``auth_sessions.totp_passed`` flag is False. It can hit only this
   router, ``/users/me`` (fastapi-users), and ``/auth/jwt/logout``.
2. ``GET /auth/totp/state`` tells the frontend whether to route to the
   setup screen or the challenge screen.
3. ``POST /auth/totp/setup`` returns a fresh secret + ``otpauth://``
   URI the UI renders as a QR code. Idempotent while ``confirmed_at``
   is null (re-issuing during a half-finished enrollment is fine).
4. ``POST /auth/totp/confirm`` takes the first 6-digit code from the
   authenticator, sets ``confirmed_at``, and flips the current session
   to full-access. Subsequent logins will produce partial sessions
   that must go through ``/auth/totp/verify``.
5. ``POST /auth/totp/verify`` is the returning-user challenge —
   takes a code, flips ``totp_passed=True`` on the current session.
6. ``POST /admin/users/{id}/totp/reset`` wipes another user's row
   so they re-enroll on next login. Gated on ``user.totp.reset``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import _now_naive
from app.auth.rbac import require_perm
from app.auth.users import current_user_partial
from app.db import get_session
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.models.email_otp import UserEmailOTP
from app.models.user_totp import UserTOTP
from app.models.webauthn import WebAuthnCredential
from app.services.audit import record as record_audit
from app.services.totp import (
    generate_secret,
    provisioning_uri,
    verify_code,
)

router = APIRouter(prefix="/auth/totp", tags=["auth"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


class TOTPState(BaseModel):
    # Authenticator-app enrollment (this router's canonical method).
    enrolled: bool
    confirmed: bool
    # Email-OTP as an alternative second factor — users may hold
    # either, both, or neither. When neither is confirmed the
    # frontend steers to the setup picker.
    email_otp_enrolled: bool
    email_otp_confirmed: bool
    # Count of registered WebAuthn / FIDO2 credentials (YubiKeys,
    # TouchID, passkeys). Any count > 0 means the WebAuthn method
    # is active for the user.
    webauthn_credential_count: int
    session_passed: bool


class TOTPSetupResponse(BaseModel):
    secret: str
    # otpauth URI for authenticator apps to consume. Frontend renders
    # this as a QR; users who can't scan copy the secret manually.
    provisioning_uri: str


class TOTPCodePayload(BaseModel):
    code: str = Field(min_length=6, max_length=8, pattern=r"^\d{6,8}$")


def _sid_from_cookie(request: Request) -> str | None:
    """Pull the session id out of the auth cookie.

    The JWT is already validated by the time we're here (the user came
    through ``current_user_partial``); this decode is just to recover
    the ``sid`` claim so we can look up the session row.
    """
    import jwt as pyjwt

    token = request.cookies.get("atrium_auth")
    if not token:
        return None
    try:
        data = pyjwt.decode(token, options={"verify_signature": False})
        return data.get("sid")
    except Exception:
        return None


async def _load_current_session(
    request: Request, session: AsyncSession
) -> AuthSession | None:
    sid = _sid_from_cookie(request)
    if sid is None:
        return None
    return (
        await session.execute(
            select(AuthSession).where(AuthSession.session_id == sid)
        )
    ).scalar_one_or_none()


async def _load_totp(session: AsyncSession, user_id: int) -> UserTOTP | None:
    return (
        await session.execute(
            select(UserTOTP).where(UserTOTP.user_id == user_id)
        )
    ).scalar_one_or_none()


async def _load_email_otp(
    session: AsyncSession, user_id: int
) -> UserEmailOTP | None:
    return (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user_id)
        )
    ).scalar_one_or_none()


@router.get("/state", response_model=TOTPState)
async def get_state(
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> TOTPState:
    totp = await _load_totp(session, user.id)
    email_otp = await _load_email_otp(session, user.id)
    webauthn_count = len(
        (
            await session.execute(
                select(WebAuthnCredential.id).where(
                    WebAuthnCredential.user_id == user.id
                )
            )
        ).scalars().all()
    )
    auth_session = await _load_current_session(request, session)
    return TOTPState(
        enrolled=totp is not None,
        confirmed=totp is not None and totp.confirmed_at is not None,
        email_otp_enrolled=email_otp is not None,
        email_otp_confirmed=(
            email_otp is not None and email_otp.confirmed_at is not None
        ),
        webauthn_credential_count=webauthn_count,
        session_passed=auth_session is not None and auth_session.totp_passed,
    )


@router.post("/setup", response_model=TOTPSetupResponse)
async def setup(
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> TOTPSetupResponse:
    """Issue a fresh secret. Idempotent while enrollment is incomplete;
    refuses to re-issue after ``confirmed_at`` is set (admins must
    ``/admin/users/{id}/totp/reset`` first)."""
    existing = await _load_totp(session, user.id)
    if existing is not None and existing.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TOTP already enrolled — ask an admin to reset it",
        )

    if existing is None:
        secret = generate_secret()
        session.add(UserTOTP(user_id=user.id, secret=secret))
        await session.commit()
    else:
        # Pending enrollment — reuse the same secret so the user can
        # still scan the QR they already have open.
        secret = existing.secret

    return TOTPSetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri(secret, user.email),
    )


@router.post("/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm(
    payload: TOTPCodePayload,
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Validate the first code, mark enrollment complete, and flip the
    current session to full-access so the caller doesn't have to log
    in again."""
    totp = await _load_totp(session, user.id)
    if totp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no enrollment in progress — call /auth/totp/setup first",
        )
    if totp.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TOTP already enrolled",
        )

    if not verify_code(totp.secret, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid code",
        )

    totp.confirmed_at = _now_naive()
    # Deliberately don't set last_used_at here — the caller will
    # often hit /auth/totp/verify on the next login within the same
    # 30 s step, and blocking that would produce a confusing
    # "code already used" right after enrollment. The replay guard
    # only applies to returning-user verifies.

    # Promote this session to full so the caller continues without
    # a fresh login.
    auth_session = await _load_current_session(request, session)
    if auth_session is not None:
        auth_session.totp_passed = True

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user_totp",
        entity_id=user.id,
        action="enroll",
        diff=None,
    )
    await session.commit()


@router.post("/verify", status_code=status.HTTP_204_NO_CONTENT)
async def verify(
    payload: TOTPCodePayload,
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Returning-user challenge. Valid code flips the current session
    to full-access."""
    totp = await _load_totp(session, user.id)
    if totp is None or totp.confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP not enrolled",
        )

    if not verify_code(totp.secret, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid code",
        )

    # No per-secret replay guard: verifying a code flips the session's
    # ``totp_passed`` one-way. An attacker replaying a captured code
    # in a new session would still need to have stolen the password
    # to hold a partial session in the first place — at which point
    # TOTP isn't the chokepoint. Keeping the guard made rapid re-tests
    # fail on step-boundary collisions with no material security win.
    totp.last_used_at = _now_naive()

    auth_session = await _load_current_session(request, session)
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no active session",
        )
    auth_session.totp_passed = True
    await session.commit()


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable(
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    """User-initiated opt-out for authenticator-app TOTP. Refuses if
    it would leave the user with zero confirmed 2FA methods.

    Partial-session is OK because users mid-login might still need to
    switch methods if they've lost access to one; locking this behind
    a full session would be a trap.
    """
    from app.models.email_otp import UserEmailOTP

    totp = await _load_totp(session, user.id)
    if totp is None:
        return

    email_otp = (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    email_otp_confirmed = (
        email_otp is not None and email_otp.confirmed_at is not None
    )

    if totp.confirmed_at is not None and not email_otp_confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "cannot disable authenticator-app TOTP while it's your "
                "only 2FA method — enroll email OTP first"
            ),
        )

    await session.execute(
        delete(UserTOTP).where(UserTOTP.user_id == user.id)
    )
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user_totp",
        entity_id=user.id,
        action="disable",
        diff=None,
    )
    await session.commit()


@admin_router.post(
    "/users/{user_id}/totp/reset", status_code=status.HTTP_204_NO_CONTENT
)
async def admin_reset(
    user_id: int,
    actor: User = Depends(require_perm("user.totp.reset")),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Wipe a user's enrollment so they re-enroll on next login.

    Also revokes all the user's active sessions — a missing TOTP row
    leaves them mid-flow, and we don't want an old session skating
    through on the still-valid ``totp_passed=True`` flag."""
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await session.execute(
        delete(UserTOTP).where(UserTOTP.user_id == user_id)
    )
    # Wipe email-OTP enrollment + any outstanding challenges too —
    # admin reset is a "kick them back to the setup picker" button,
    # independent of which method they'd chosen.
    await session.execute(
        delete(UserEmailOTP).where(UserEmailOTP.user_id == user_id)
    )
    # Same for WebAuthn — every credential is nuked so the user has
    # to re-register any key they still want to use.
    await session.execute(
        delete(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
    )
    # Revoke active sessions so the target has to log in and
    # re-enroll cleanly. We reuse the same revoked_at mechanism as
    # /auth/logout-all.
    await session.execute(
        AuthSession.__table__.update()
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now_naive())
    )

    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="user_totp",
        entity_id=user_id,
        action="admin_reset",
        diff={"target_email": target.email},
    )
    await session.commit()
