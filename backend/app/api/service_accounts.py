# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Service-account creation + listing.

Two routes under ``/admin/service_accounts``:

- ``POST /``   create a service account *and* its first PAT
- ``GET  /``   list every service account

Gated by ``auth.service_accounts.manage`` (super_admin only). The
admin role does not hold this permission — issuing a non-human
identity that holds long-lived bearer tokens is operationally
sensitive in the same way ``user.impersonate`` is.

A service account is just a ``users`` row with
``is_service_account=True``: ``email_verified_at`` is set at creation
(no signup flow), ``is_verified=True`` (mirrors the invite-accept
shape), ``hashed_password=""`` as the empty-string sentinel that
bcrypt cannot match. The login refusal in ``UserManager.authenticate``
keys on the boolean flag, not the empty hash, so the flag is the
real gate.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_tokens import TokenCreated, _to_summary
from app.auth.pat_format import generate_token
from app.auth.pat_hashing import hash_token
from app.auth.rbac import (
    assign_role,
    get_user_permissions,
    require_cookie_auth,
    require_perm,
)
from app.db import get_session
from app.models.auth import User
from app.models.auth_token import AuthToken
from app.models.rbac import Role
from app.services.audit import record as record_audit

router = APIRouter(
    prefix="/admin/service_accounts", tags=["admin"]
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ServiceAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    description: str | None = Field(default=None, max_length=500)
    # RBAC roles to assign on creation. Defaults to no roles — the
    # operator picks what the service account is allowed to do.
    # ``initial_scopes`` is then validated against the union of these
    # roles' permissions, same as a regular user issuing their own
    # PAT against their own permission set.
    role_codes: list[str] = Field(default_factory=list)
    # Permission slugs the initial PAT carries. At least one — a
    # zero-scope PAT is useless. Each scope must be in the union of
    # ``role_codes``' permissions (the service account's effective
    # set), and also a subset of the *creator's* permissions
    # (defence-in-depth: a super_admin can't issue tokens scoped to a
    # permission the super_admin doesn't currently hold, even though
    # super_admin holds everything by default).
    initial_scopes: list[str] = Field(min_length=1)
    # ``None`` = the initial PAT never expires. Capped against
    # ``pats.max_lifetime_days`` at issue time, same as a self-service
    # create.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ServiceAccountRead(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    description: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServiceAccountCreated(BaseModel):
    """Response shape for create. Contains the initial PAT's plaintext
    — the only place it appears."""

    account: ServiceAccountRead
    token: TokenCreated


@router.post(
    "",
    response_model=ServiceAccountCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_account(
    payload: ServiceAccountCreate,
    actor: User = Depends(require_perm("auth.service_accounts.manage")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> ServiceAccountCreated:
    """Create a service-account user + its first PAT in one round-trip.

    The PAT's plaintext is in the response body exactly once — same
    contract as ``POST /auth/tokens``. There's no follow-up route
    that could re-emit it; an operator who loses the token rotates
    it through the standard ``/auth/tokens/{id}/rotate`` flow once
    they've cookie-authed *as the service account*… which is
    impossible by design. The realistic recovery is: revoke the lost
    token (admin path) and create a new one (also admin path, future
    work — for now, mint the second PAT manually via the model).
    """
    # Email collision check — same shape as invite create.
    existing = (
        await session.execute(
            select(User).where(User.email == payload.email)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a user with this email already exists",
        )

    actor_perms = await get_user_permissions(session, actor.id)
    overreach = set(payload.initial_scopes) - actor_perms
    if overreach:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "scope_overreach_actor",
                "missing_permissions": sorted(overreach),
            },
        )

    # Verify role_codes exist before creating anything — otherwise the
    # user would land but role assignment would silently no-op.
    if payload.role_codes:
        existing_codes = set(
            (
                await session.execute(
                    select(Role.code).where(Role.code.in_(payload.role_codes))
                )
            ).scalars().all()
        )
        unknown = set(payload.role_codes) - existing_codes
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown role codes: {sorted(unknown)}",
            )

    now = _utcnow()
    # Hash a fresh 32-byte random secret nobody ever knows. The
    # ``is_service_account`` flag is the load-bearing login gate; the
    # hash is here purely so ``pwdlib.verify_and_update`` (which
    # fastapi-users calls before our wrapper's flag check) doesn't
    # raise ``UnknownHashError`` on a malformed value. Migration 0009's
    # docstring discusses an empty-string sentinel — that worked in a
    # bcrypt-only world, but pwdlib's hasher detection refuses ``""``.
    # A random hash is functionally equivalent (no input can ever
    # match) and round-trips cleanly through every login attempt.
    import secrets as _secrets

    from fastapi_users.password import PasswordHelper as _PasswordHelper

    _pw = _PasswordHelper()
    user = User(
        email=payload.email,
        hashed_password=_pw.hash(_secrets.token_urlsafe(32)),
        is_active=True,
        is_verified=True,
        full_name=payload.name,
        preferred_language="en",
        is_service_account=True,
        email_verified_at=now,
    )
    session.add(user)
    await session.flush()

    for role_code in payload.role_codes:
        await assign_role(session, user_id=user.id, role_code=role_code)
    await session.flush()

    # Validate ``initial_scopes`` against the *target's* effective
    # permission set (now that roles are assigned). The actor's
    # check above is defence-in-depth; this one is the load-bearing
    # gate ("a token cannot do what its user cannot").
    target_perms = await get_user_permissions(session, user.id)
    target_overreach = set(payload.initial_scopes) - target_perms
    if target_overreach:
        # Roll back the user creation by raising — the surrounding
        # ``session`` autouse fixture will TRUNCATE between tests, but
        # in production this leaves an aborted transaction that the
        # request-scoped session handles correctly.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "scope_overreach_target",
                "missing_permissions": sorted(target_overreach),
                "hint": (
                    "initial_scopes must be a subset of the union of "
                    "role_codes' permissions"
                ),
            },
        )

    # Mint the first PAT inline. Service accounts hold every PAT they
    # ever use through this admin path — the self-service router
    # refuses non-cookie auth, so the service account itself can never
    # call ``POST /auth/tokens``. Issuing the first PAT here is the
    # only way the account becomes useful.
    from app.services.app_config import PatsConfig, get_namespace

    cfg = await get_namespace(session, "pats")
    assert isinstance(cfg, PatsConfig)

    expires_at: datetime | None = None
    if payload.expires_in_days is not None:
        capped = payload.expires_in_days
        if cfg.max_lifetime_days is not None:
            capped = min(capped, cfg.max_lifetime_days)
        from datetime import timedelta as _td

        expires_at = now + _td(days=capped)
    elif cfg.max_lifetime_days is not None:
        from datetime import timedelta as _td

        expires_at = now + _td(days=cfg.max_lifetime_days)

    plaintext, prefix = generate_token()
    token_row = AuthToken(
        user_id=user.id,
        # Attribute the token to the super-admin who minted it, not to
        # the service account itself. The trail "human X created
        # service-account Y's first PAT" is what auditors need.
        created_by_user_id=actor.id,
        name=f"{payload.name} initial",
        description="Initial service-account PAT",
        token_prefix=prefix,
        token_hash=hash_token(plaintext),
        scopes=list(payload.initial_scopes),
        expires_at=expires_at,
        created_at=now,
    )
    session.add(token_row)
    await session.flush()

    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="user",
        entity_id=user.id,
        action="create",
        diff={
            "email": user.email,
            "via": "service_account",
            "initial_token_id": token_row.id,
        },
    )
    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="auth_token",
        entity_id=token_row.id,
        action="create",
        diff={
            "name": token_row.name,
            "scopes": list(token_row.scopes),
            "expires_at": token_row.expires_at,
            "target_user_id": token_row.user_id,
            "via": "service_account_create",
        },
        token_id=token_row.id,
    )
    await session.commit()
    await session.refresh(user)
    await session.refresh(token_row)

    summary = _to_summary(token_row, now)
    return ServiceAccountCreated(
        account=ServiceAccountRead(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            description=payload.description,
            created_at=user.created_at,
        ),
        token=TokenCreated(token=plaintext, **summary.model_dump()),
    )


@router.get("", response_model=list[ServiceAccountRead])
async def list_service_accounts(
    _u: User = Depends(require_perm("auth.service_accounts.manage")),
    _cookie: User = Depends(require_cookie_auth),
    session: AsyncSession = Depends(get_session),
) -> list[ServiceAccountRead]:
    """Every service account in the system, newest first.

    Plaintext tokens are never included (they don't exist outside
    the create response). To inspect a service account's tokens, use
    the admin token list with ``?user_id=...``.
    """
    rows = list(
        (
            await session.execute(
                select(User)
                .where(User.is_service_account.is_(True))
                .order_by(User.created_at.desc())
            )
        ).scalars().all()
    )
    return [
        ServiceAccountRead(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            description=None,
            created_at=u.created_at,
        )
        for u in rows
    ]
