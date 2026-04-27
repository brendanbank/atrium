# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""GDPR-aligned soft-delete for user accounts.

The flow is three-stage:

1. ``soft_delete_user`` — caller-initiated. Anonymises the row's PII
   in place (so a stolen DB dump no longer ties the row to a person),
   revokes every active ``auth_sessions`` row, sets ``deleted_at`` and
   ``scheduled_hard_delete_at = now + grace_days``. The user row stays
   so audit_log foreign keys keep resolving during the grace window.
2. The user can request reinstatement during the grace window (operator
   intervention — there is no self-serve un-delete; once the password
   has been wiped the user can't authenticate to undo it).
3. The ``account_hard_delete`` worker handler scans for users whose
   ``scheduled_hard_delete_at`` has elapsed and removes them outright.

Caller controls the transaction. The audit row + email travel inside
it so a failure rolls all of them back together.
"""
from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.email.sender import send_and_log
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.services.app_config import AuthConfig, get_namespace
from app.services.audit import record as record_audit


def _anonymised_email(user_id: int) -> str:
    # ``.invalid`` is a reserved TLD (RFC 2606) — guaranteed not to
    # resolve. Use ``deleted.invalid`` rather than bare ``invalid`` so
    # the address still parses as a valid email per the EmailStr
    # validator (which requires a dot in the domain). Otherwise
    # ``GET /admin/users`` 500s as soon as it tries to serialize a
    # soft-deleted row.
    return f"deleted+{user_id}@deleted.invalid"


async def soft_delete_user(
    session: AsyncSession,
    *,
    user_id: int,
    actor_user_id: int,
    reason: str = "self",
) -> User:
    """Mark ``user_id`` as soft-deleted, anonymise PII, revoke sessions,
    and email the original address with the hard-delete date.

    Returns the mutated User row. Caller commits.

    Re-running on an already soft-deleted user raises ``ValueError`` —
    nothing meaningful left to anonymise and the audit row would be
    misleading.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise LookupError(f"user {user_id} not found")
    if user.deleted_at is not None:
        raise ValueError("account is already scheduled for deletion")

    auth_cfg_model = await get_namespace(session, "auth")
    assert isinstance(auth_cfg_model, AuthConfig)
    grace_days = auth_cfg_model.delete_grace_days

    original_email = user.email
    original_full_name = user.full_name

    now = datetime.now(UTC).replace(tzinfo=None)
    hard_delete_at = now + timedelta(days=grace_days)

    user.deleted_at = func.now()
    user.scheduled_hard_delete_at = hard_delete_at
    user.email = _anonymised_email(user.id)
    user.full_name = "Deleted user"
    user.phone = None
    # Empty hash never validates against any password — locks login.
    user.hashed_password = ""
    user.is_active = False

    await session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    brand = await get_namespace(session, "brand")
    support_email = getattr(brand, "support_email", None) or ""

    # The deletion is the user's primary intent — a flaky SMTP relay
    # must not block it. send_and_log already records the failure to
    # email_log so the admin mail log surfaces it.
    with contextlib.suppress(Exception):
        await send_and_log(
            session,
            template="account_delete_confirm",
            to=[original_email],
            entity_type="user",
            entity_id=user.id,
            context={
                "recipient": {
                    "email": original_email.lower(),
                    "full_name": original_full_name,
                },
                "user": {
                    "email": original_email.lower(),
                    "full_name": original_full_name,
                },
                "date": hard_delete_at.date().isoformat(),
                "support_email": support_email,
            },
            locale=user.preferred_language or "en",
        )

    await record_audit(
        session,
        actor_user_id=actor_user_id,
        entity="user",
        entity_id=user.id,
        action="soft_delete",
        diff={
            "reason": reason,
            "original_email": original_email,
            "scheduled_hard_delete_at": hard_delete_at.isoformat(),
        },
    )

    return user
