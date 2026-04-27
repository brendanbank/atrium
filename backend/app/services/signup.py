# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Self-serve signup + email verification.

Two operations: ``register_user`` creates a fresh account (when the
``auth.allow_signup`` toggle is on), issues a verification token, and
sends the ``email_verify`` template; ``consume_verification`` flips
``users.email_verified_at`` after the user clicks the link.

Tokens are 32-byte url-safe secrets stored as their sha256 digest.
The plain token only ever exists in the email link and the user's
clipboard — a leaked DB dump cannot replay it.

Caller controls the transaction; nothing commits inside this module.
"""
from __future__ import annotations

import contextlib
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from email_validator import EmailNotValidError, validate_email
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import assign_role
from app.email.sender import send_and_log
from app.logging import log
from app.models.auth import User
from app.models.email_verification import EmailVerification
from app.models.enums import Language
from app.services.app_config import AuthConfig, BrandConfig, get_namespace
from app.services.audit import record as record_audit
from app.settings import get_settings

# 24h verification window. Long enough that a user who clicks "register"
# Friday afternoon and then gets distracted can still verify Monday;
# short enough that a stolen email account doesn't open an indefinite
# attack window.
_VERIFY_TTL = timedelta(hours=24)

_password_helper = PasswordHelper()


class SignupDisabled(Exception):  # noqa: N818
    """Raised when ``auth.allow_signup`` is False. The API turns this
    into a 404 so the route's existence isn't broadcast on tenants
    that haven't opted in."""


class EmailAlreadyRegistered(Exception):  # noqa: N818
    """Raised when an account with that email already exists."""


class InvalidEmail(Exception):  # noqa: N818
    """Raised when the supplied email fails validation."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None,
    language: str = "en",
) -> User:
    """Create a new account and dispatch the verification email.

    Returns the persisted User. Raises ``SignupDisabled`` /
    ``EmailAlreadyRegistered`` / ``InvalidEmail`` for the recoverable
    failure cases the API translates into 404 / 409 / 400.
    """
    auth_cfg = await get_namespace(session, "auth")
    assert isinstance(auth_cfg, AuthConfig)
    if not auth_cfg.allow_signup:
        raise SignupDisabled()

    try:
        # check_deliverability=False — we don't want network calls
        # during a request, and DNS-level validation belongs in a
        # different layer (usually the SMTP relay's bounce handling).
        validated = validate_email(email, check_deliverability=False)
        normalised_email = validated.normalized
    except EmailNotValidError as exc:
        raise InvalidEmail(str(exc)) from exc

    # Run the live password policy. ``register_user`` bypasses
    # ``UserManager.create`` (which would otherwise enforce the same
    # rules) so we invoke the helper directly. The fastapi-users
    # exception's ``reason`` becomes the 400 detail via ``InvalidEmail``.
    from fastapi_users.exceptions import InvalidPasswordException

    from app.services.password_policy import validate_password_against_policy

    if password is None:
        raise InvalidEmail("password is required")
    try:
        await validate_password_against_policy(session, password)
    except InvalidPasswordException as exc:
        raise InvalidEmail(exc.reason) from exc

    existing = (
        await session.execute(
            select(User).where(User.email == normalised_email)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise EmailAlreadyRegistered()

    # Map the language string onto the Language enum, falling back to
    # English for anything we don't ship a locale for. The DB column
    # is a 5-char string so an unknown value would persist; better to
    # store something the app knows how to render.
    try:
        lang_value = Language(language).value
    except ValueError:
        lang_value = Language.EN.value

    user = User(
        email=normalised_email,
        hashed_password=_password_helper.hash(password),
        is_active=True,
        # ``is_verified`` is fastapi-users' own flag — leave it False;
        # ``email_verified_at`` is what the login refusal reads.
        is_verified=False,
        full_name=full_name or "",
        preferred_language=lang_value,
        email_verified_at=None,
    )
    session.add(user)
    await session.flush()

    role_code = auth_cfg.signup_default_role_code
    await assign_role(session, user_id=user.id, role_code=role_code)

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = _now_naive() + _VERIFY_TTL
    session.add(
        EmailVerification(
            user_id=user.id,
            token_sha256=token_hash,
            expires_at=expires_at,
        )
    )

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user",
        entity_id=user.id,
        action="signup",
        diff={
            "email": user.email,
            "role_code": role_code,
            "via": "self_serve",
        },
    )

    settings = get_settings()
    verify_url = (
        f"{settings.app_base_url.rstrip('/')}/verify-email?token={raw_token}"
    )
    brand = await get_namespace(session, "brand")
    brand_name = getattr(brand, "name", None) or "Atrium"
    assert isinstance(brand, BrandConfig)

    # Synchronous send: the user just hit register and is waiting for
    # the "check your email" UI. A flaky SMTP relay can't block the
    # account creation, so swallow the exception — send_and_log already
    # writes a failed email_log row that the admin can retry from.
    with contextlib.suppress(Exception):
        await send_and_log(
            session,
            template="email_verify",
            to=[normalised_email],
            entity_type="user",
            entity_id=user.id,
            context={
                "recipient": {
                    "email": normalised_email.lower(),
                    "full_name": user.full_name or "",
                },
                "user": {
                    "email": normalised_email.lower(),
                    "full_name": user.full_name or "",
                },
                "verify_url": verify_url,
                "brand_name": brand_name,
            },
            # Recipient picked their language at signup time — render
            # the verify-email template against that variant (or EN
            # fallback when the host hasn't translated it).
            locale=lang_value,
        )

    log.info(
        "user.signup",
        user_id=user.id,
        email=normalised_email,
        role_code=role_code,
    )

    return user


async def consume_verification(
    session: AsyncSession, *, token: str
) -> User | None:
    """Mark the verification row consumed and flip
    ``users.email_verified_at``. Returns the verified User or None when
    the token is unknown / expired / already consumed."""
    if not token:
        return None
    token_hash = _hash_token(token)
    row = (
        await session.execute(
            select(EmailVerification).where(
                EmailVerification.token_sha256 == token_hash
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.consumed_at is not None:
        return None
    now = _now_naive()
    if row.expires_at <= now:
        return None

    user = await session.get(User, row.user_id)
    if user is None:
        return None

    row.consumed_at = now
    user.email_verified_at = now
    # ``is_verified`` is fastapi-users' flag; flip it too so any
    # downstream code that reads it sees a coherent state.
    user.is_verified = True

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="user",
        entity_id=user.id,
        action="email_verified",
        diff={"email": user.email},
    )

    log.info("user.email_verified", user_id=user.id, email=user.email)
    return user
