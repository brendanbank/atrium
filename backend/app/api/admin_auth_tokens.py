# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Admin Personal Access Token endpoints.

Four routes under ``/admin/auth/tokens``:

- ``GET    /``                    list every token (filterable)
- ``DELETE /{id}``                admin revoke (non-empty reason)
- ``POST   /revoke_all``          bulk revoke for one user
- ``GET    /{id}/audit``          per-token audit trail

Read endpoints gate on ``auth.pats.admin_read`` (super_admin only by
default; admin role does *not* hold this — same carve-out shape as
``user.impersonate``). Mutating endpoints gate on
``auth.pats.admin_revoke``.

Every route also gates on ``require_cookie_auth`` so a leaked admin
PAT can't bootstrap further token operations.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_tokens import TokenSummary, _to_summary
from app.auth.rbac import require_cookie_auth, require_perm
from app.db import get_session
from app.models.auth import User
from app.models.auth_token import AuthToken
from app.models.ops import AuditLog
from app.services.audit import record as record_audit

router = APIRouter(prefix="/admin/auth/tokens", tags=["admin"])


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminTokenSummary(TokenSummary):
    """Admin view: same shape as the self-service summary, plus the
    holding user's identity columns the admin UI needs to render
    'who owns this token' without a second round-trip."""

    user_id: int
    user_email: str
    user_full_name: str
    revoked_by_user_id: int | None

    model_config = ConfigDict(from_attributes=True)


class TokenPage(BaseModel):
    items: list[AdminTokenSummary]
    total: int


class AdminRevokeBody(BaseModel):
    """Required body for admin revoke. ``reason`` MUST be non-empty —
    leaving it blank would defeat the audit trail's purpose for
    incident response."""

    reason: str = Field(min_length=1, max_length=255)


class AdminRevokeAllBody(BaseModel):
    user_id: int
    reason: str = Field(min_length=1, max_length=255)


class RevokeAllResult(BaseModel):
    user_id: int
    revoked_count: int
    reason: str


class AuditEntry(BaseModel):
    id: int
    actor_user_id: int | None
    impersonator_user_id: int | None
    token_id: int | None
    entity: str
    entity_id: int
    action: str
    diff: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int


def _admin_summary(
    row: AuthToken, user: User, now: datetime | None = None
) -> AdminTokenSummary:
    base = _to_summary(row, now)
    return AdminTokenSummary(
        **base.model_dump(),
        user_id=user.id,
        user_email=user.email,
        user_full_name=user.full_name,
        revoked_by_user_id=row.revoked_by_user_id,
    )


@router.get("", response_model=TokenPage)
async def list_all_tokens(
    _u: User = Depends(require_perm("auth.pats.admin_read")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
    user_id: int | None = Query(default=None),
    status_filter: Literal["active", "expired", "revoked"] | None = Query(
        default=None, alias="status"
    ),
    unused_for_days: int | None = Query(default=None, ge=1, le=3650),
    expiring_within_days: int | None = Query(default=None, ge=1, le=3650),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TokenPage:
    """Cross-user token list for ops + incident response.

    Filters compose with AND. ``status`` is computed at row read time
    (no enum column); we apply the SQL clauses that match the spec
    directly so MySQL filters server-side rather than streaming every
    row to Python first.
    """
    now = _utcnow()
    stmt = select(AuthToken, User).join(User, User.id == AuthToken.user_id)
    count_stmt = select(func.count(AuthToken.id))

    if user_id is not None:
        stmt = stmt.where(AuthToken.user_id == user_id)
        count_stmt = count_stmt.where(AuthToken.user_id == user_id)

    if status_filter == "revoked":
        stmt = stmt.where(AuthToken.revoked_at.isnot(None))
        count_stmt = count_stmt.where(AuthToken.revoked_at.isnot(None))
    elif status_filter == "expired":
        stmt = stmt.where(
            AuthToken.revoked_at.is_(None),
            AuthToken.expires_at.isnot(None),
            AuthToken.expires_at < now,
        )
        count_stmt = count_stmt.where(
            AuthToken.revoked_at.is_(None),
            AuthToken.expires_at.isnot(None),
            AuthToken.expires_at < now,
        )
    elif status_filter == "active":
        active_clause = and_(
            AuthToken.revoked_at.is_(None),
            or_(
                AuthToken.expires_at.is_(None),
                AuthToken.expires_at > now,
            ),
        )
        stmt = stmt.where(active_clause)
        count_stmt = count_stmt.where(active_clause)

    if unused_for_days is not None:
        # "Unused for N days" = either never used OR last used before
        # the cutoff. ``last_used_at IS NULL`` covers freshly-issued
        # tokens that nobody's tried yet — operators want to see those
        # too when sweeping for stale credentials.
        cutoff = now - timedelta(days=unused_for_days)
        unused_clause = or_(
            AuthToken.last_used_at.is_(None),
            AuthToken.last_used_at < cutoff,
        )
        stmt = stmt.where(unused_clause)
        count_stmt = count_stmt.where(unused_clause)

    if expiring_within_days is not None:
        # Tokens that will expire by ``now + N days``. Excludes
        # already-expired ones (caller would use ``status=expired``)
        # and never-expires tokens.
        upper = now + timedelta(days=expiring_within_days)
        expiring_clause = and_(
            AuthToken.expires_at.isnot(None),
            AuthToken.expires_at > now,
            AuthToken.expires_at <= upper,
        )
        stmt = stmt.where(expiring_clause)
        count_stmt = count_stmt.where(expiring_clause)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = list(
        (
            await session.execute(
                stmt.order_by(AuthToken.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    items = [_admin_summary(row, user, now) for row, user in rows]
    return TokenPage(items=items, total=int(total or 0))


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_revoke_token(
    token_id: int,
    body: AdminRevokeBody,
    actor: User = Depends(require_perm("auth.pats.admin_revoke")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(AuthToken, token_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if row.revoked_at is not None:
        # Idempotent admin revoke is a no-op — but we still write an
        # audit row so two simultaneous incident responders both see
        # their action represented in the trail.
        await record_audit(
            session,
            actor_user_id=actor.id,
            entity="auth_token",
            entity_id=row.id,
            action="revoke",
            diff={
                "reason": body.reason,
                "via": "admin",
                "already_revoked": True,
                "target_user_id": row.user_id,
            },
            token_id=row.id,
        )
        await session.commit()
        return None

    now = _utcnow()
    row.revoked_at = now
    row.revoked_by_user_id = actor.id
    row.revoke_reason = body.reason

    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="auth_token",
        entity_id=row.id,
        action="revoke",
        diff={
            "reason": body.reason,
            "via": "admin",
            "target_user_id": row.user_id,
        },
        token_id=row.id,
    )
    await session.commit()
    return None


@router.post("/revoke_all", response_model=RevokeAllResult)
async def admin_revoke_all(
    body: AdminRevokeAllBody,
    actor: User = Depends(require_perm("auth.pats.admin_revoke")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> RevokeAllResult:
    """Bulk-revoke every active token belonging to one user.

    Incident-response shape: a compromised user account gets every
    PAT invalidated in one round-trip. Each row gets its own audit
    entry so the per-token trail is preserved (vs. a single bulk
    audit that would lose the per-token attribution).
    """
    target = await session.get(User, body.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    now = _utcnow()
    rows = list(
        (
            await session.execute(
                select(AuthToken).where(
                    AuthToken.user_id == body.user_id,
                    AuthToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
    )
    for row in rows:
        row.revoked_at = now
        row.revoked_by_user_id = actor.id
        row.revoke_reason = body.reason
        await record_audit(
            session,
            actor_user_id=actor.id,
            entity="auth_token",
            entity_id=row.id,
            action="revoke",
            diff={
                "reason": body.reason,
                "via": "admin_bulk",
                "target_user_id": row.user_id,
            },
            token_id=row.id,
        )

    await session.commit()
    return RevokeAllResult(
        user_id=body.user_id,
        revoked_count=len(rows),
        reason=body.reason,
    )


@router.get("/{token_id}/audit", response_model=AuditPage)
async def admin_token_audit(
    token_id: int,
    _u: User = Depends(require_perm("auth.pats.admin_read")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditPage:
    """Per-token audit trail — single indexed query against
    ``audit_log.token_id``. Includes events fired from inside the
    middleware (``used`` / ``invalid`` / ``rate_limited``) as well as
    user-driven events (``create`` / ``revoke`` / ``rotate``)."""
    # 404 only when the token has never existed *and* there are no
    # audit rows for it. Revoked-and-purged tokens may still have
    # audit rows (token_id FK is SET NULL on delete) — but for the
    # admin API a missing token row is treated as 404 to keep the
    # contract simple.
    row = await session.get(AuthToken, token_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    base = select(AuditLog).where(AuditLog.token_id == token_id)
    total = (
        await session.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.token_id == token_id
            )
        )
    ).scalar_one()

    rows = list(
        (
            await session.execute(
                base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    items = [
        AuditEntry(
            id=r.id,
            actor_user_id=r.actor_user_id,
            impersonator_user_id=r.impersonator_user_id,
            token_id=r.token_id,
            entity=r.entity,
            entity_id=r.entity_id,
            action=r.action,
            diff=r.diff,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AuditPage(items=items, total=int(total or 0))
