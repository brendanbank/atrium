# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Integration tests for ``PATAuthMiddleware``.

These exercise the full request flow: middleware parses the
Authorization header, looks up the row, verifies the argon2 hash,
intersects scopes with the user's current permissions, populates
the request scope slot, and the downstream ``current_user`` /
``current_principal`` deps consume it.

Not every audit and rate-limit code path is covered here — those
land alongside the API endpoints that emit them in Phase 2. The
goal of Phase 1's integration tests is to prove the auth substrate
works.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.pat_format import generate_token
from app.auth.pat_hashing import hash_token
from app.models.auth_token import AuthToken
from app.models.ops import AppSetting
from tests.helpers import seed_admin, seed_user


def _utcnow() -> datetime:
    """Naive UTC datetime — matches the schema (``DateTime`` columns
    have no timezone) without tripping the deprecated ``utcnow()``."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _enable_pats(engine, *, enabled: bool = True) -> None:
    """Materialise the ``pats`` namespace row. The middleware reads
    ``enabled`` on every PAT-presenting request — without this the
    spec-default ``False`` makes every test 401."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSetting(key="pats", value={"enabled": enabled}))
        await s.commit()


async def _create_pat(
    engine,
    *,
    user_id: int,
    scopes: list[str],
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    name: str = "test token",
) -> tuple[str, AuthToken]:
    """Mint a fresh PAT and persist the matching ``auth_tokens`` row.
    Returns ``(plaintext_token, row)``."""
    plain, prefix = generate_token()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = AuthToken(
            user_id=user_id,
            created_by_user_id=user_id,
            name=name,
            token_prefix=prefix,
            token_hash=hash_token(plain),
            scopes=scopes,
            expires_at=expires_at,
            revoked_at=revoked_at,
            created_at=_utcnow(),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
    return plain, row


@pytest_asyncio.fixture
async def admin_pat(client, engine):
    """An admin user holding ``audit.read`` (among others) and a PAT
    scoped to that permission. Used by the happy-path tests."""
    await _enable_pats(engine, enabled=True)
    user = await seed_admin(engine, email="pat-admin@example.com")
    plain, row = await _create_pat(
        engine, user_id=user.id, scopes=["audit.read", "user.manage"]
    )
    return {"user": user, "token": plain, "row": row}


async def test_valid_pat_authenticates_through_audit_endpoint(
    client, admin_pat
):
    """A PAT scoped to ``audit.read`` reaches a route gated by
    ``require_perm("audit.read")``. Confirms the cookie-vs-PAT auth
    path resolves through the Principal and require_perm consults
    ``principal.permissions`` correctly."""
    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {admin_pat['token']}"},
    )
    assert r.status_code == 200, r.text


async def test_pat_without_required_scope_is_403(client, engine):
    """The user holds ``audit.read`` (admin role) but the *token*
    doesn't include it. Scope intersection narrows the effective
    set; ``require_perm("audit.read")`` returns 403."""
    await _enable_pats(engine, enabled=True)
    user = await seed_admin(engine, email="pat-narrow@example.com")
    plain, _ = await _create_pat(
        engine, user_id=user.id, scopes=["user.manage"]  # NOT audit.read
    )
    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 403, r.text


async def test_pat_scope_unheld_by_user_is_dropped(client, engine):
    """A token whose stored scopes the user doesn't currently hold
    intersects to (effectively) empty. Even if the token CLAIMS
    ``audit.read``, a user without ``audit.read`` (the plain ``user``
    role) can't reach an audit-gated route."""
    await _enable_pats(engine, enabled=True)
    user = await seed_user(engine, email="pat-demoted@example.com")
    plain, _ = await _create_pat(
        engine, user_id=user.id, scopes=["audit.read"]
    )
    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 403


async def test_pat_authenticates_users_me_context(client, admin_pat):
    """The simpler end of the auth chain: the PAT is enough to reach
    a route guarded by ``current_user`` (no specific permission).
    Permissions returned by ``/users/me/context`` are the user's
    full set — that endpoint surfaces capability for UI gating, not
    the per-request Principal scope. The PAT-only intersection
    behaviour is verified by the previous tests against
    ``/admin/audit``."""
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": f"Bearer {admin_pat['token']}"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == admin_pat["user"].email


async def test_expired_pat_is_refused(client, engine):
    await _enable_pats(engine, enabled=True)
    user = await seed_admin(engine, email="pat-exp@example.com")
    yesterday = _utcnow() - timedelta(days=1)
    plain, _ = await _create_pat(
        engine,
        user_id=user.id,
        scopes=["audit.read"],
        expires_at=yesterday,
    )
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "token_expired"


async def test_revoked_pat_is_refused(client, engine):
    await _enable_pats(engine, enabled=True)
    user = await seed_admin(engine, email="pat-rev@example.com")
    yesterday = _utcnow() - timedelta(days=1)
    plain, _ = await _create_pat(
        engine,
        user_id=user.id,
        scopes=["audit.read"],
        revoked_at=yesterday,
    )
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": f"Bearer {plain}"},
    )
    # Revoked rows are filtered by the WHERE clause itself —
    # observable as ``invalid_token`` (we don't broadcast that the
    # token used to exist).
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_token"


async def test_invalid_format_pat_is_refused(client, engine):
    await _enable_pats(engine, enabled=True)
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": "Bearer atr_pat_garbage"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_token"


async def test_pats_disabled_refuses_even_valid_token(client, engine):
    """When the operator turns PATs off, even a structurally-valid
    token is refused — no broadcast that the kill switch is on."""
    await _enable_pats(engine, enabled=False)
    user = await seed_admin(engine, email="pat-off@example.com")
    plain, _ = await _create_pat(
        engine, user_id=user.id, scopes=["audit.read"]
    )
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_token"


async def test_non_pat_bearer_falls_through(client, engine):
    """A bearer token that isn't a PAT (e.g. some other format) must
    not be touched by ``PATAuthMiddleware`` — let it fall through to
    the normal cookie-auth chain (which will 401 on its own)."""
    r = await client.get(
        "/users/me/context",
        headers={"Authorization": "Bearer ghp_some_other_token"},
    )
    # No cookie + bearer-not-a-PAT → cookie auth chain rejects.
    # The exact status depends on fastapi-users (401 for missing
    # cookie). What matters: the PAT middleware doesn't return its
    # own 401 with code=invalid_token here.
    assert r.status_code == 401
    body = r.json()
    # Either no ``code`` field at all, or not the PAT-specific one.
    assert body.get("code") != "invalid_token"


async def test_prefix_collision_handled_correctly(client, engine):
    """Two rows sharing a ``token_prefix`` must each authenticate to
    *their own* token (and *their own* scopes). The middleware does
    ``scalars().all()`` + ``verify_token`` per candidate; if it
    were ``scalar()``, the second row would silently 401 because
    ``scalar()`` returns the first match and argon2-verify would
    fail against the wrong hash.

    Probe through ``/admin/audit`` (gated by ``require_perm
    ("audit.read")``): token A grants audit.read; token B does not.
    """
    await _enable_pats(engine, enabled=True)
    user = await seed_admin(engine, email="pat-collision@example.com")
    plain1, row1 = await _create_pat(
        engine, user_id=user.id, scopes=["audit.read"], name="A"
    )
    # Force a *real* prefix collision: build plain2 by replacing
    # everything after the first 4 secret chars of plain1, so
    # ``plain2[:12] == plain1[:12]`` but the rest of the secret
    # differs. The middleware's prefix-lookup query (``WHERE
    # token_prefix = ?``) will return BOTH rows for either token,
    # which is the case we want to test (verify-each must pick the
    # right one).
    import base64
    import secrets
    import zlib

    from app.auth.pat_format import LOOKUP_PREFIX_LEN, PREFIX

    shared_secret_head = plain1[len(PREFIX):LOOKUP_PREFIX_LEN]  # 4 chars
    fresh_bytes = secrets.token_bytes(24)
    fresh_secret = (
        base64.urlsafe_b64encode(fresh_bytes).rstrip(b"=").decode()
    )
    plain2_secret = shared_secret_head + fresh_secret[len(shared_secret_head):32]
    plain2_body = PREFIX + plain2_secret
    plain2_crc = (
        base64.b32encode(zlib.crc32(plain2_body.encode()).to_bytes(4, "big"))
        .rstrip(b"=")
        .decode()
        .lower()[:6]
    )
    plain2 = f"{plain2_body}_{plain2_crc}"
    assert plain2[:LOOKUP_PREFIX_LEN] == row1.token_prefix
    assert plain2 != plain1

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            AuthToken(
                user_id=user.id,
                created_by_user_id=user.id,
                name="B (synthetic prefix collision)",
                token_prefix=row1.token_prefix,
                token_hash=hash_token(plain2),
                scopes=["user.manage"],
                created_at=_utcnow(),
            )
        )
        await s.commit()

    # Sanity: both rows landed and share the prefix.
    async with factory() as s:
        from sqlalchemy import select as _select

        rows = (
            await s.scalars(
                _select(AuthToken).where(
                    AuthToken.token_prefix == row1.token_prefix
                )
            )
        ).all()
    assert len(rows) == 2, f"expected 2 rows with prefix, got {len(rows)}"

    # Token A: audit.read in scope → reaches the audit endpoint.
    r1 = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain1}"},
    )
    assert r1.status_code == 200, r1.text

    # Token B: same prefix but audit.read NOT in scope → 403.
    # If the middleware used ``scalar()`` and picked the wrong row,
    # token B would either authenticate as token A (200, wrong) or
    # 401 because the hash doesn't match the picked row.
    r2 = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain2}"},
    )
    assert r2.status_code == 403, r2.text


async def test_pat_blocked_by_maintenance_mode(client, engine):
    """When the maintenance kill switch is on, even a valid PAT
    request must see a 503. PATs are **not** on the bypass list — by
    design, programmatic callers should back off during maintenance
    too (issue #112 §13)."""
    await _enable_pats(engine, enabled=True)
    user = await seed_admin(engine, email="pat-maint@example.com")
    plain, _ = await _create_pat(
        engine, user_id=user.id, scopes=["audit.read"]
    )

    # Flip maintenance on through the same KV row the middleware reads.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            AppSetting(
                key="system",
                value={"maintenance_mode": True, "maintenance_message": "brb"},
            )
        )
        await s.commit()
    # Maintenance flag is cached for 2 s; reset to take effect now.
    from app.services import maintenance as maint

    maint.reset_cache()

    # ``/users/me/context`` is on the maintenance bypass list (so
    # the SPA can render the maintenance page); use a non-bypassed
    # route to verify the kill switch reaches PAT-authed traffic.
    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "maintenance_mode"


async def test_inactive_user_pat_refused(client, engine):
    await _enable_pats(engine, enabled=True)
    user = await seed_admin(engine, email="pat-inactive@example.com")
    plain, _ = await _create_pat(
        engine, user_id=user.id, scopes=["audit.read"]
    )
    # Flip the user inactive after token issuance.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        from sqlalchemy import update

        from app.models.auth import User as UserModel

        await s.execute(
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(is_active=False)
        )
        await s.commit()

    r = await client.get(
        "/users/me/context",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "user_inactive"


async def test_service_account_cannot_login_via_password(client, engine):
    """A user with ``is_service_account=True`` is refused at the
    interactive login route — same 400 bucket as bad credentials so
    the response doesn't discriminate."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    from fastapi_users.password import PasswordHelper

    pw_helper = PasswordHelper()
    async with factory() as s:
        from app.models.auth import User as UserModel

        u = UserModel(
            email="svc@example.com",
            hashed_password=pw_helper.hash("svc-pw-12345"),
            is_active=True,
            is_verified=True,
            full_name="Service Account",
            preferred_language="en",
            is_service_account=True,
            email_verified_at=_utcnow(),
        )
        s.add(u)
        await s.commit()

    r = await client.post(
        "/auth/jwt/login",
        data={"username": "svc@example.com", "password": "svc-pw-12345"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # fastapi-users returns 400 LOGIN_BAD_CREDENTIALS for
    # ``authenticate() returned None``. We piggyback on the same
    # response so an attacker can't tell service-account emails
    # apart from human ones.
    assert r.status_code == 400


async def test_service_account_pat_authenticates(client, engine):
    """The flip side of the previous test: the service account's PAT
    works just like a human user's. ``auth_method`` becomes
    ``service_account_pat`` (not directly observable from the user-
    facing API, but the middleware sets it for audit purposes)."""
    await _enable_pats(engine, enabled=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    from fastapi_users.password import PasswordHelper

    from app.auth.rbac import assign_role

    pw_helper = PasswordHelper()
    async with factory() as s:
        from app.models.auth import User as UserModel

        u = UserModel(
            email="svc-pat@example.com",
            hashed_password=pw_helper.hash("never-used"),
            is_active=True,
            is_verified=True,
            full_name="Svc PAT",
            preferred_language="en",
            is_service_account=True,
            email_verified_at=_utcnow(),
        )
        s.add(u)
        await s.flush()
        await assign_role(s, user_id=u.id, role_code="admin")
        await s.commit()
        await s.refresh(u)
    plain, _ = await _create_pat(
        engine, user_id=u.id, scopes=["audit.read"]
    )

    # Authenticate + reach an audit-gated route. Confirms the
    # PAT path treats service accounts identically to humans.
    r = await client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert r.status_code == 200, r.text
