# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Email-OTP second-factor — parallel to authenticator-app TOTP.

Flow mirrors ``/auth/totp/*``:

* ``POST /auth/email-otp/setup`` — partial-session; sends a
  confirmation code to the user's own email so they can finish
  enrolling.
* ``POST /auth/email-otp/confirm`` — partial-session; takes the code,
  flips ``confirmed_at``, and promotes the current session to full.
* ``POST /auth/email-otp/request`` — partial-session; the
  returning-user "send me the code" action. Valid only for users who
  already have ``confirmed_at`` set.
* ``POST /auth/email-otp/verify`` — partial-session; takes the code,
  flips ``totp_passed`` on the current session.
* ``POST /auth/email-otp/disable`` — full-session; user opts out.
  Refuses if it would leave the user with zero enrolled methods
  (closing the only door out of their own account is a great way to
  get paged).

Codes are 6 digits, valid for 10 minutes, single-use. We store only
the sha256 of the code so a DB leak doesn't hand the attacker live
codes.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import _now_naive
from app.auth.users import current_user, current_user_partial
from app.db import get_session
from app.email.sender import send_and_log
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.models.email_otp import EmailOTPChallenge, UserEmailOTP
from app.models.user_totp import UserTOTP
from app.services.audit import record as record_audit

router = APIRouter(prefix="/auth/email-otp", tags=["auth"])

# Codes expire after 10 minutes.
CODE_TTL = timedelta(minutes=10)

# Cooldown between issuing codes to the same user. 1Password (and
# similar autofill flows that see "OTP form → paste") can trigger a
# second setup/request post within the same second, which would
# otherwise spray duplicate emails at the user. Short window keeps
# the UX responsive if the user legitimately reloads after a minute.
ISSUE_COOLDOWN = timedelta(seconds=10)


class EmailOTPCodePayload(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    # 6 digits, zero-padded. ``secrets.randbelow`` is the right-way
    # CSPRNG path — ``random`` would be seedable.
    return f"{secrets.randbelow(1_000_000):06d}"


def _sid_from_cookie(request: Request) -> str | None:
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


async def _recent_challenge_exists(
    session: AsyncSession, user_id: int
) -> bool:
    """Return True if we issued a still-live code to this user inside
    the ``ISSUE_COOLDOWN`` window. Caller skips the send when True so
    autofill-driven duplicate triggers don't spam.

    Scoped to unused challenges on purpose: once the user's code has
    been consumed (``used_at`` set) the next legitimate request is
    almost certainly a fresh login attempt, and blocking it would
    lock them out until the cooldown elapsed.
    """
    cutoff = _now_naive() - ISSUE_COOLDOWN
    row = (
        await session.execute(
            select(EmailOTPChallenge)
            .where(
                EmailOTPChallenge.user_id == user_id,
                EmailOTPChallenge.used_at.is_(None),
                EmailOTPChallenge.created_at >= cutoff,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _issue_code_and_email(
    session: AsyncSession, user: User
) -> None:
    """Generate a code, hash it, store the challenge, email the plain
    code. Older outstanding challenges for this user are cleared so
    ``verify`` only has to consider the freshest one."""
    code = _generate_code()
    # Clear older pending challenges — a user asking for a new code
    # invalidates the previous one, and it keeps the table tidy.
    await session.execute(
        delete(EmailOTPChallenge).where(
            EmailOTPChallenge.user_id == user.id,
            EmailOTPChallenge.used_at.is_(None),
        )
    )
    session.add(
        EmailOTPChallenge(
            user_id=user.id,
            code_hash=_hash_code(code),
            expires_at=_now_naive() + CODE_TTL,
        )
    )
    await send_and_log(
        session,
        template="email_otp_code",
        to=[user.email],
        context={
            "user_name": user.full_name,
            "code": code,
            "recipient": {
                "email": user.email.lower(),
                "full_name": user.full_name or "",
            },
        },
        locale=user.preferred_language or "en",
    )


@router.post("/setup", status_code=status.HTTP_204_NO_CONTENT)
async def setup(
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Start email-OTP enrollment: create the row (unconfirmed) and
    email a code the user must echo back to ``/confirm``."""
    existing = (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email OTP already enrolled",
        )
    if existing is None:
        # ``INSERT IGNORE`` — two concurrent setup calls (e.g. React
        # StrictMode's double-effect in dev) race to insert the same
        # PK. The loser would otherwise crash on the duplicate; this
        # just swallows it and proceeds with the existing row.
        await session.execute(
            UserEmailOTP.__table__.insert().prefix_with("IGNORE").values(
                user_id=user.id
            )
        )

    # Cooldown — autofill/paste-style clients may double-submit; return
    # the same 204 without resending so the caller's own retry logic
    # can't amplify a single user action into multiple emails.
    if not await _recent_challenge_exists(session, user.id):
        await _issue_code_and_email(session, user)
    await session.commit()


@router.post("/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm(
    payload: EmailOTPCodePayload,
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Validate the confirmation code, set ``confirmed_at``, and
    promote the current session to full."""
    enrollment = (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no enrollment in progress — call /auth/email-otp/setup first",
        )
    if enrollment.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email OTP already enrolled",
        )

    if not await _consume_valid_code(session, user.id, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid or expired code",
        )

    enrollment.confirmed_at = _now_naive()

    auth_session = await _load_current_session(request, session)
    if auth_session is not None:
        auth_session.totp_passed = True

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user_email_otp",
        entity_id=user.id,
        action="enroll",
        diff=None,
    )
    await session.commit()


@router.post("/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_code(
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Returning-user "email me a code" button. 400s if the user
    isn't actually enrolled in email OTP."""
    enrollment = (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    if enrollment is None or enrollment.confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email OTP not enrolled",
        )

    if not await _recent_challenge_exists(session, user.id):
        await _issue_code_and_email(session, user)
    await session.commit()


@router.post("/verify", status_code=status.HTTP_204_NO_CONTENT)
async def verify(
    payload: EmailOTPCodePayload,
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Returning-user challenge: valid code flips the current
    session's ``totp_passed`` flag."""
    enrollment = (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    if enrollment is None or enrollment.confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email OTP not enrolled",
        )

    if not await _consume_valid_code(session, user.id, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid or expired code",
        )

    enrollment.last_used_at = _now_naive()

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
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """User-driven opt-out. Refuses if it would leave the account
    with zero confirmed 2FA methods."""
    totp = (
        await session.execute(
            select(UserTOTP).where(UserTOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    totp_confirmed = totp is not None and totp.confirmed_at is not None

    enrollment = (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    if enrollment is None:
        # Nothing to do.
        return

    if enrollment.confirmed_at is not None and not totp_confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "cannot disable email OTP while it's your only 2FA method — "
                "enroll an authenticator app first"
            ),
        )

    await session.execute(
        delete(EmailOTPChallenge).where(EmailOTPChallenge.user_id == user.id)
    )
    await session.execute(
        delete(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
    )
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user_email_otp",
        entity_id=user.id,
        action="disable",
        diff=None,
    )
    await session.commit()


async def _consume_valid_code(
    session: AsyncSession, user_id: int, code: str
) -> bool:
    """Look up the most recent unused, unexpired challenge for this
    user and check it matches. Marks it ``used_at=now`` on success so
    a replay fails. Returns False when no match; caller raises the
    400 with a generic "invalid or expired code" to avoid leaking
    which half was wrong.
    """
    now = _now_naive()
    row = (
        await session.execute(
            select(EmailOTPChallenge)
            .where(
                EmailOTPChallenge.user_id == user_id,
                EmailOTPChallenge.used_at.is_(None),
                EmailOTPChallenge.expires_at > now,
            )
            .order_by(EmailOTPChallenge.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    if not secrets.compare_digest(row.code_hash, _hash_code(code)):
        return False
    row.used_at = now
    return True
