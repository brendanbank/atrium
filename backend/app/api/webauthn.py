# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""WebAuthn / FIDO2 second-factor — alongside TOTP and email OTP.

A user can register multiple authenticators at once (primary YubiKey
+ backup, TouchID + phone passkey, ...). Each ceremony has two steps:

* ``POST /auth/webauthn/register/begin`` (partial-session) — returns
  the options the browser's ``navigator.credentials.create`` wants.
  The challenge is stored server-side keyed on (user_id, purpose)
  so the browser's echo can be verified later.
* ``POST /auth/webauthn/register/finish`` (partial-session) —
  verifies the attestation, writes a new credential row, and if the
  user has no prior 2FA, promotes the session to full-access.
* ``POST /auth/webauthn/authenticate/begin`` (partial-session) —
  returns the ``navigator.credentials.get`` options, narrowed to
  the user's registered credentials.
* ``POST /auth/webauthn/authenticate/finish`` (partial-session) —
  verifies the assertion, bumps ``sign_count`` + ``last_used_at``,
  flips ``totp_passed``.
* ``GET  /auth/webauthn/credentials`` (full-session) — list.
* ``DELETE /auth/webauthn/credentials/{id}`` (full-session) —
  remove one. Refuses if it would leave the user with zero 2FA
  methods at all.

Challenge rows live for 5 minutes; stale ones are filtered out
rather than deleted eagerly (a cron tick wipes them).
"""
from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.auth.backend import _now_naive
from app.auth.users import current_user, current_user_partial
from app.db import get_session
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.models.email_otp import UserEmailOTP
from app.models.user_totp import UserTOTP
from app.models.webauthn import WebAuthnChallenge, WebAuthnCredential
from app.services.audit import record as record_audit
from app.settings import get_settings

router = APIRouter(prefix="/auth/webauthn", tags=["auth"])

CHALLENGE_TTL = timedelta(minutes=5)
PURPOSE_REGISTER = "register"
PURPOSE_AUTHENTICATE = "authenticate"


def _b64url(b: bytes) -> str:
    return urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return urlsafe_b64decode(s + padding)


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


async def _store_challenge(
    session: AsyncSession,
    *,
    user_id: int,
    purpose: str,
    challenge: bytes,
) -> None:
    """Replace any existing challenge for (user, purpose) with this
    fresh one. Scoping by purpose keeps a mid-flight registration
    from accidentally completing an authentication ceremony."""
    await session.execute(
        delete(WebAuthnChallenge).where(
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.purpose == purpose,
        )
    )
    session.add(
        WebAuthnChallenge(
            user_id=user_id,
            purpose=purpose,
            challenge=challenge,
            expires_at=_now_naive() + CHALLENGE_TTL,
        )
    )


async def _consume_challenge(
    session: AsyncSession, *, user_id: int, purpose: str
) -> bytes | None:
    row = (
        await session.execute(
            select(WebAuthnChallenge).where(
                WebAuthnChallenge.user_id == user_id,
                WebAuthnChallenge.purpose == purpose,
                WebAuthnChallenge.expires_at > _now_naive(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    raw = row.challenge
    await session.execute(
        delete(WebAuthnChallenge).where(WebAuthnChallenge.id == row.id)
    )
    return raw


async def _promote_session(
    request: Request, session: AsyncSession
) -> None:
    sid = _sid_from_cookie(request)
    if sid is None:
        return
    row = (
        await session.execute(
            select(AuthSession).where(AuthSession.session_id == sid)
        )
    ).scalar_one_or_none()
    if row is not None:
        row.totp_passed = True


# ---------- registration ----------

class RegisterBeginResponse(BaseModel):
    # Opaque JSON the browser passes to navigator.credentials.create.
    # Pre-serialised by py_webauthn's options_to_json so the
    # frontend can hand it straight to the WebAuthn API (no ad-hoc
    # base64url juggling).
    options: dict


class RegisterFinishPayload(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    # The attestation response from ``navigator.credentials.create``,
    # serialised with ``PublicKeyCredential.toJSON()``.
    credential: dict


@router.post("/register/begin", response_model=RegisterBeginResponse)
async def register_begin(
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> RegisterBeginResponse:
    settings = get_settings()

    # exclude_credentials prevents the user from accidentally
    # re-registering an already-known authenticator (the browser
    # will say "this key is already registered").
    existing = (
        await session.execute(
            select(WebAuthnCredential).where(
                WebAuthnCredential.user_id == user.id
            )
        )
    ).scalars().all()

    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.email,
        user_display_name=user.full_name,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=_b64url_decode(c.credential_id))
            for c in existing
        ],
        authenticator_selection=_authenticator_selection(),
    )

    await _store_challenge(
        session,
        user_id=user.id,
        purpose=PURPOSE_REGISTER,
        challenge=options.challenge,
    )
    await session.commit()

    import json

    return RegisterBeginResponse(options=json.loads(options_to_json(options)))


def _authenticator_selection() -> AuthenticatorSelectionCriteria:
    """2FA profile — password is the "something you know" factor;
    the key is just the "something you have". We therefore:

    * ``user_verification=DISCOURAGED`` — don't ask the authenticator
      to verify the user. YubiKey users get touch-only instead of
      touch + PIN; TouchID users get the biometric without an extra
      prompt. Matches AWS's 2FA flow.
    * ``resident_key=DISCOURAGED`` — the credential lives in the
      server's DB, not on the token. No PIN is required to create
      one, and the token's (limited) resident-credential slots stay
      free for passwordless use elsewhere.
    """
    return AuthenticatorSelectionCriteria(
        resident_key=ResidentKeyRequirement.DISCOURAGED,
        user_verification=UserVerificationRequirement.DISCOURAGED,
    )


@router.post("/register/finish", status_code=status.HTTP_204_NO_CONTENT)
async def register_finish(
    payload: RegisterFinishPayload,
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    challenge = await _consume_challenge(
        session, user_id=user.id, purpose=PURPOSE_REGISTER
    )
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no registration in progress — call /register/begin first",
        )

    settings = get_settings()
    try:
        verified = verify_registration_response(
            credential=payload.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
        )
    except InvalidRegistrationResponse as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"registration failed: {exc}",
        ) from exc

    # ``credential_id`` and ``credential_public_key`` on the verified
    # response are raw bytes; we store the id as url-safe base64 so
    # it doubles as a natural-key column.
    transports_raw = payload.credential.get("response", {}).get("transports")
    transports = (
        ",".join(transports_raw)
        if isinstance(transports_raw, list) and transports_raw
        else None
    )

    session.add(
        WebAuthnCredential(
            user_id=user.id,
            credential_id=_b64url(verified.credential_id),
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            label=payload.label.strip(),
            transports=transports,
        )
    )

    # First-time 2FA: promote to full session so the caller doesn't
    # have to log back in. Matches the TOTP / email-OTP confirm flow.
    await _promote_session(request, session)

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user_webauthn_credential",
        entity_id=user.id,
        action="register",
        diff={"label": payload.label.strip()},
    )
    await session.commit()


# ---------- authentication ----------

class AuthenticateBeginResponse(BaseModel):
    options: dict


class AuthenticateFinishPayload(BaseModel):
    credential: dict


@router.post("/authenticate/begin", response_model=AuthenticateBeginResponse)
async def authenticate_begin(
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> AuthenticateBeginResponse:
    settings = get_settings()
    credentials = (
        await session.execute(
            select(WebAuthnCredential).where(
                WebAuthnCredential.user_id == user.id
            )
        )
    ).scalars().all()
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no WebAuthn credentials registered",
        )

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(
                id=_b64url_decode(c.credential_id)
            )
            for c in credentials
        ],
        # Same rationale as registration: touch-only, no PIN prompt.
        user_verification=UserVerificationRequirement.DISCOURAGED,
    )

    await _store_challenge(
        session,
        user_id=user.id,
        purpose=PURPOSE_AUTHENTICATE,
        challenge=options.challenge,
    )
    await session.commit()

    import json

    return AuthenticateBeginResponse(
        options=json.loads(options_to_json(options))
    )


@router.post(
    "/authenticate/finish", status_code=status.HTTP_204_NO_CONTENT
)
async def authenticate_finish(
    payload: AuthenticateFinishPayload,
    request: Request,
    user: User = Depends(current_user_partial),
    session: AsyncSession = Depends(get_session),
) -> None:
    challenge = await _consume_challenge(
        session, user_id=user.id, purpose=PURPOSE_AUTHENTICATE
    )
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no authentication in progress — call /authenticate/begin first",
        )

    # Look up the credential by its ID so we can hand the stored
    # public key + counter to the verifier.
    raw_cred_id = payload.credential.get("rawId") or payload.credential.get("id")
    if not raw_cred_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing credential id",
        )
    cred = (
        await session.execute(
            select(WebAuthnCredential).where(
                WebAuthnCredential.credential_id == raw_cred_id,
                WebAuthnCredential.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown credential",
        )

    settings = get_settings()
    try:
        verified = verify_authentication_response(
            credential=payload.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=cred.public_key,
            credential_current_sign_count=cred.sign_count,
        )
    except InvalidAuthenticationResponse as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"authentication failed: {exc}",
        ) from exc

    cred.sign_count = verified.new_sign_count
    cred.last_used_at = _now_naive()

    await _promote_session(request, session)
    await session.commit()


# ---------- management ----------

class CredentialRead(BaseModel):
    id: int
    label: str
    transports: str | None
    last_used_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


@router.get("/credentials", response_model=list[CredentialRead])
async def list_credentials(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[CredentialRead]:
    rows = (
        await session.execute(
            select(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user.id)
            .order_by(WebAuthnCredential.created_at.asc())
        )
    ).scalars().all()
    return [
        CredentialRead(
            id=r.id,
            label=r.label,
            transports=r.transports,
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.delete(
    "/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_credential(
    credential_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = (
        await session.execute(
            select(WebAuthnCredential).where(
                WebAuthnCredential.id == credential_id,
                WebAuthnCredential.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Count remaining methods across ALL three factor types. Refuse
    # if this delete would leave the user with zero confirmed ways
    # to authenticate.
    remaining_webauthn = (
        await session.execute(
            select(WebAuthnCredential).where(
                WebAuthnCredential.user_id == user.id,
                WebAuthnCredential.id != credential_id,
            )
        )
    ).scalars().all()
    totp = (
        await session.execute(
            select(UserTOTP).where(UserTOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    totp_confirmed = totp is not None and totp.confirmed_at is not None
    email_otp = (
        await session.execute(
            select(UserEmailOTP).where(UserEmailOTP.user_id == user.id)
        )
    ).scalar_one_or_none()
    email_otp_confirmed = (
        email_otp is not None and email_otp.confirmed_at is not None
    )
    if not remaining_webauthn and not totp_confirmed and not email_otp_confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "can't remove the last 2FA credential — enable another "
                "method first"
            ),
        )

    await session.execute(
        delete(WebAuthnCredential).where(WebAuthnCredential.id == credential_id)
    )
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user_webauthn_credential",
        entity_id=credential_id,
        action="delete",
        diff={"label": row.label},
    )
    await session.commit()
