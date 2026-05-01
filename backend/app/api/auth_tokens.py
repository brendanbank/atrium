# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Self-service Personal Access Token endpoints.

Five routes under ``/auth/tokens``:

- ``POST   ``                   create
- ``GET    ``                   list self
- ``PATCH  /{id}``              update name / description / scopes / expires
- ``POST   /{id}/rotate``       new token, same shape, old revoked
- ``DELETE /{id}``              revoke self

All gated by ``auth.pats.read_self`` (every system role auto-holds it)
plus ``require_cookie_auth`` — a PAT cannot manage other PATs even if
it carries the matching admin scope. ``current_user`` already enforces
``auth_sessions.totp_passed=True`` on cookie callers, so the v1 step-up
gate is implicit. A real fresh-challenge primitive is descoped per
spec §13.

The plaintext token leaves this router exactly twice: in the response
body of ``POST /`` and ``POST /{id}/rotate``. Every other shape returns
``TokenSummary`` (no plaintext, ever).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.pat_format import generate_token
from app.auth.pat_hashing import hash_token
from app.auth.rbac import (
    get_user_permissions,
    require_cookie_auth,
    require_perm,
)
from app.db import get_session
from app.models.auth import User
from app.models.auth_token import AuthToken
from app.services.app_config import PatsConfig, get_namespace
from app.services.audit import record as record_audit

router = APIRouter(prefix="/auth/tokens", tags=["auth"])


def _utcnow() -> datetime:
    """Naive UTC — matches the schema (``DateTime`` columns have no
    timezone) without tripping the deprecated ``utcnow()``."""
    return datetime.now(UTC).replace(tzinfo=None)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    scopes: list[str] = Field(min_length=1)
    # ``None`` = no expiry. Capped at ``pats.max_lifetime_days`` if set.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class TokenUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    scopes: list[str] | None = None
    # Absolute new expiry, naive UTC. ``None`` doesn't clear the
    # field — pass it explicitly via ``expires_at: null`` to remove
    # the cap (subject to ``pats.max_lifetime_days``).
    expires_at: datetime | None = None
    # Sentinel that lets the caller distinguish "leave alone" from
    # "remove expiry" — Pydantic can't tell the two apart on its own.
    # When True, ``expires_at`` is set to NULL regardless of its value.
    clear_expiry: bool = False


class TokenSummary(BaseModel):
    id: int
    name: str
    description: str | None
    token_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    last_used_ip: str | None
    use_count: int
    created_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None
    # Derived: ``active`` / ``expired`` / ``revoked``. Always one of the
    # three, computed at read time so the row state survives schema
    # drift.
    status: Literal["active", "expired", "revoked"]

    model_config = ConfigDict(from_attributes=True)


class TokenCreated(TokenSummary):
    """Returned only from POST and rotate. Carries the plaintext token —
    the only place it ever lives outside argon2 hashing."""

    token: str


class TokenRevokeBody(BaseModel):
    """Optional body for ``DELETE /{id}``. Not having a body is fine
    too — ``revoke_reason`` defaults to ``"self"`` to keep the audit
    column populated."""

    reason: str | None = Field(default=None, max_length=255)


def _row_status(row: AuthToken, now: datetime | None = None) -> str:
    if row.revoked_at is not None:
        return "revoked"
    n = now or _utcnow()
    if row.expires_at is not None and row.expires_at < n:
        return "expired"
    return "active"


def _to_summary(row: AuthToken, now: datetime | None = None) -> TokenSummary:
    return TokenSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        token_prefix=row.token_prefix,
        scopes=list(row.scopes or []),
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        last_used_ip=row.last_used_ip,
        use_count=row.use_count,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
        status=_row_status(row, now),
    )


def _validate_scopes_against_user(
    requested: list[str], user_perms: set[str]
) -> None:
    overreach = set(requested) - user_perms
    if overreach:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "scope_overreach",
                "missing_permissions": sorted(overreach),
            },
        )


def _cap_expires_at(
    expires_in_days: int | None, max_lifetime_days: int | None
) -> datetime | None:
    """Resolve an ``expires_in_days`` to an absolute ``expires_at`` and
    cap it at the operator's policy. ``None`` in / ``None`` out means
    'no expiry'.
    """
    if expires_in_days is None:
        # Caller asked for no expiry. Honour the policy cap if set.
        if max_lifetime_days is not None:
            return _utcnow() + timedelta(days=max_lifetime_days)
        return None
    capped = expires_in_days
    if max_lifetime_days is not None:
        capped = min(capped, max_lifetime_days)
    return _utcnow() + timedelta(days=capped)


def _cap_absolute_expires_at(
    expires_at: datetime | None, max_lifetime_days: int | None
) -> datetime | None:
    """Cap a caller-supplied absolute expiry against ``max_lifetime_days``
    measured from *now* (the spec wording: "cannot extend beyond
    max_lifetime_days from now"). Updates can therefore re-extend a
    token but never beyond the policy ceiling.
    """
    if expires_at is None or max_lifetime_days is None:
        return expires_at
    ceiling = _utcnow() + timedelta(days=max_lifetime_days)
    return min(expires_at, ceiling)


async def _count_active_for_user(
    session: AsyncSession, user_id: int, now: datetime
) -> int:
    return (
        await session.execute(
            select(func.count(AuthToken.id)).where(
                AuthToken.user_id == user_id,
                AuthToken.revoked_at.is_(None),
                # NULL expires_at is "never expires" — counts as active.
                (AuthToken.expires_at.is_(None))
                | (AuthToken.expires_at > now),
            )
        )
    ).scalar_one()


@router.post(
    "",
    response_model=TokenCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_token(
    payload: TokenCreate,
    user: User = Depends(require_perm("auth.pats.read_self")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> TokenCreated:
    """Mint a fresh PAT.

    Returns the plaintext token *exactly once*. The hash and prefix
    are stored; the plaintext is never persisted, never logged.
    Refuses if any requested scope isn't currently held by the user
    (intersection-at-issue prevents a stale-but-still-elevated user
    from seeding a token with extra reach), and refuses if the user
    is already at ``pats.max_per_user`` active tokens.
    """
    cfg = await get_namespace(session, "pats")
    assert isinstance(cfg, PatsConfig)

    user_perms = await get_user_permissions(session, user.id)
    _validate_scopes_against_user(payload.scopes, user_perms)

    now = _utcnow()
    active = await _count_active_for_user(session, user.id, now)
    if active >= cfg.max_per_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "max_per_user_exceeded",
                "active_tokens": active,
                "max_per_user": cfg.max_per_user,
            },
        )

    expires_at = _cap_expires_at(payload.expires_in_days, cfg.max_lifetime_days)

    plaintext, prefix = generate_token()
    row = AuthToken(
        user_id=user.id,
        created_by_user_id=user.id,
        name=payload.name,
        description=payload.description,
        token_prefix=prefix,
        token_hash=hash_token(plaintext),
        scopes=list(payload.scopes),
        expires_at=expires_at,
        created_at=now,
    )
    session.add(row)
    await session.flush()

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="auth_token",
        entity_id=row.id,
        action="create",
        diff={
            "name": row.name,
            "scopes": list(row.scopes),
            "expires_at": row.expires_at,
            "target_user_id": row.user_id,
        },
        token_id=row.id,
    )
    await session.commit()
    await session.refresh(row)

    summary = _to_summary(row, now)
    return TokenCreated(token=plaintext, **summary.model_dump())


@router.get("", response_model=list[TokenSummary])
async def list_tokens(
    user: User = Depends(require_perm("auth.pats.read_self")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
    status_filter: Literal["active", "expired", "revoked"] | None = Query(
        default=None, alias="status"
    ),
) -> list[TokenSummary]:
    """List the calling user's tokens, newest first.

    Plaintext is never included. Status filter is computed at read
    time (no enum column) — clients can also filter client-side from
    the unfiltered list when juggling multiple states is rare.
    """
    rows = list(
        (
            await session.execute(
                select(AuthToken)
                .where(AuthToken.user_id == user.id)
                .order_by(AuthToken.created_at.desc())
            )
        ).scalars().all()
    )
    now = _utcnow()
    summaries = [_to_summary(r, now) for r in rows]
    if status_filter is not None:
        summaries = [s for s in summaries if s.status == status_filter]
    return summaries


@router.patch("/{token_id}", response_model=TokenSummary)
async def update_token(
    token_id: int,
    payload: TokenUpdate,
    user: User = Depends(require_perm("auth.pats.read_self")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> TokenSummary:
    """Edit name / description / scopes / expires_at on one's own token.

    Scope reduction is unrestricted. Adding scopes is allowed when the
    user currently holds them — same intersection check as create.
    Expiry can be extended but only up to ``max_lifetime_days`` from
    now (so a token never lives past the policy ceiling regardless of
    how many extensions it receives).
    """
    row = await session.get(AuthToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "token_revoked"},
        )

    cfg = await get_namespace(session, "pats")
    assert isinstance(cfg, PatsConfig)

    diff: dict = {}
    if payload.name is not None and payload.name != row.name:
        diff["name"] = {"from": row.name, "to": payload.name}
        row.name = payload.name
    if payload.description != row.description and (
        payload.description is not None
        or "description" in payload.model_fields_set
    ):
        diff["description"] = {"from": row.description, "to": payload.description}
        row.description = payload.description

    if payload.scopes is not None:
        new_scopes = list(payload.scopes)
        old_scopes = list(row.scopes or [])
        if set(new_scopes) != set(old_scopes):
            user_perms = await get_user_permissions(session, user.id)
            _validate_scopes_against_user(new_scopes, user_perms)
            diff["scopes"] = {"from": old_scopes, "to": new_scopes}
            row.scopes = new_scopes

    if payload.clear_expiry:
        if row.expires_at is not None:
            diff["expires_at"] = {
                "from": row.expires_at,
                "to": None,
            }
            row.expires_at = None
    elif payload.expires_at is not None:
        capped = _cap_absolute_expires_at(
            payload.expires_at, cfg.max_lifetime_days
        )
        # Strip tzinfo for the naive DateTime column. The user-facing
        # field is timezone-aware so callers can be explicit.
        if capped is not None and capped.tzinfo is not None:
            capped = capped.astimezone(UTC).replace(tzinfo=None)
        if capped != row.expires_at:
            diff["expires_at"] = {"from": row.expires_at, "to": capped}
            row.expires_at = capped

    if diff:
        await record_audit(
            session,
            actor_user_id=user.id,
            entity="auth_token",
            entity_id=row.id,
            action="update",
            diff=diff,
            token_id=row.id,
        )

    await session.commit()
    await session.refresh(row)
    return _to_summary(row)


@router.post(
    "/{token_id}/rotate",
    response_model=TokenCreated,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_token(
    token_id: int,
    user: User = Depends(require_perm("auth.pats.read_self")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> TokenCreated:
    """Issue a new token with the same name / scopes / expires_at,
    revoke the old.

    Useful for routine rotation in long-lived deployments. The new
    token's audit row links to the old via ``diff.previous_token_id``;
    the old token's revoke audit links to the new via
    ``diff.replaced_by_token_id``. Both rows carry ``action='rotate'``.
    """
    old = await session.get(AuthToken, token_id)
    if old is None or old.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if old.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "token_revoked"},
        )

    now = _utcnow()
    plaintext, prefix = generate_token()
    new_row = AuthToken(
        user_id=user.id,
        created_by_user_id=user.id,
        name=old.name,
        description=old.description,
        token_prefix=prefix,
        token_hash=hash_token(plaintext),
        scopes=list(old.scopes or []),
        expires_at=old.expires_at,
        created_at=now,
    )
    session.add(new_row)
    await session.flush()

    old.revoked_at = now
    old.revoked_by_user_id = user.id
    old.revoke_reason = "rotated"

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="auth_token",
        entity_id=new_row.id,
        action="rotate",
        diff={
            "previous_token_id": old.id,
            "scopes": list(new_row.scopes),
            "expires_at": new_row.expires_at,
        },
        token_id=new_row.id,
    )
    await record_audit(
        session,
        actor_user_id=user.id,
        entity="auth_token",
        entity_id=old.id,
        action="rotate",
        diff={
            "replaced_by_token_id": new_row.id,
            "reason": "rotated",
        },
        token_id=old.id,
    )

    await session.commit()
    await session.refresh(new_row)

    summary = _to_summary(new_row, now)
    return TokenCreated(token=plaintext, **summary.model_dump())


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: int,
    body: TokenRevokeBody = Body(default_factory=TokenRevokeBody),
    user: User = Depends(require_perm("auth.pats.read_self")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Mark a token revoked. Idempotent — a re-revoke is a no-op (404
    only when the row doesn't exist or belongs to someone else).

    Self-revoke fills ``revoke_reason`` with the caller-supplied
    string or ``"self"``; admin revoke goes through the sibling
    router and requires the field explicitly.
    """
    row = await session.get(AuthToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if row.revoked_at is not None:
        return None

    now = _utcnow()
    reason = body.reason or "self"
    row.revoked_at = now
    row.revoked_by_user_id = user.id
    row.revoke_reason = reason

    await record_audit(
        session,
        actor_user_id=user.id,
        entity="auth_token",
        entity_id=row.id,
        action="revoke",
        diff={"reason": reason, "via": "self"},
        token_id=row.id,
    )
    await session.commit()
    return None
