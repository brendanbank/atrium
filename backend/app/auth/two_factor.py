# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Shared 2FA-gate helpers.

``write_token`` (in ``backend.py``) and ``current_user`` (in ``users.py``)
both need to decide whether a user must clear a second factor. Splitting
the logic out avoids a circular import (``users.py`` already imports
``auth_backend`` from ``backend.py``).

The contract:

* A user with at least one confirmed factor must challenge before they
  reach domain endpoints.
* A user whose role set intersects ``auth.require_2fa_for_roles`` must
  enrol a factor (and then challenge) before they reach domain
  endpoints.
* Everyone else — no factor, not enforced — gets a full session at
  login. ``require_2fa_for_roles=[]`` (the default) therefore makes 2FA
  truly opt-in: users can enrol from their profile page if they want to,
  but it isn't forced on them.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_otp import UserEmailOTP
from app.models.rbac import Role, user_roles
from app.models.user_totp import UserTOTP
from app.models.webauthn import WebAuthnCredential


async def user_has_any_2fa(session: AsyncSession, user_id: int) -> bool:
    """Return True if the user holds any confirmed second factor.

    "Confirmed" matters for TOTP / email-OTP — an in-progress enrollment
    row exists with ``confirmed_at IS NULL`` and shouldn't satisfy the
    enforcement check. WebAuthn credentials are only persisted after a
    successful registration ceremony, so any row counts.
    """
    row = (
        await session.execute(
            select(UserTOTP.user_id)
            .where(
                UserTOTP.user_id == user_id,
                UserTOTP.confirmed_at.is_not(None),
            )
            .limit(1)
        )
    ).first()
    if row is not None:
        return True
    row = (
        await session.execute(
            select(UserEmailOTP.user_id)
            .where(
                UserEmailOTP.user_id == user_id,
                UserEmailOTP.confirmed_at.is_not(None),
            )
            .limit(1)
        )
    ).first()
    if row is not None:
        return True
    row = (
        await session.execute(
            select(WebAuthnCredential.id)
            .where(WebAuthnCredential.user_id == user_id)
            .limit(1)
        )
    ).first()
    return row is not None


async def user_role_codes(session: AsyncSession, user_id: int) -> set[str]:
    rows = (
        await session.execute(
            select(Role.code)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
        )
    ).scalars().all()
    return set(rows)


async def user_has_enforced_role(
    session: AsyncSession, user_id: int, enforced: list[str]
) -> bool:
    if not enforced:
        return False
    return bool((await user_role_codes(session, user_id)) & set(enforced))


async def login_grants_full_session(
    session: AsyncSession, user_id: int
) -> bool:
    """Decide whether a fresh login should be marked ``totp_passed=True``.

    Returns True only when the user has no confirmed factor AND no role
    on the enforcement list — i.e. nothing to challenge and nothing to
    enrol. Read errors on the auth namespace fall back to the safe
    default (False) so a transient DB hiccup can't accidentally open
    accounts that should require 2FA.
    """
    if await user_has_any_2fa(session, user_id):
        return False
    try:
        from app.services.app_config import AuthConfig, get_namespace

        cfg = await get_namespace(session, "auth")
        if isinstance(cfg, AuthConfig) and await user_has_enforced_role(
            session, user_id, cfg.require_2fa_for_roles
        ):
            return False
    except Exception:
        return False
    return True
