# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Personal Access Token authentication middleware.

Sits in the middleware chain *after* maintenance / rate-limit /
captcha but *before* the cookie-auth dep chain. When a request
carries an ``Authorization: Bearer atr_pat_…`` header, this
middleware:

1. Refuses any URL that contains a recognisable PAT (tokens belong in
   ``Authorization``, never in path / query — spec §13). The check
   runs unconditionally, before the bearer parse, so an unauthenticated
   request with a token in the query string is still rejected.
2. Validates the wire format (cheap CRC check, no DB).
3. Looks up candidate rows by the 12-char public prefix.
4. argon2-verifies each candidate (almost always exactly one).
5. Checks ``revoked_at``, ``expires_at``, and ``user.is_active``.
6. Computes ``scopes ∩ user.permissions`` — a token can never do
   what its user cannot.
7. Per-token rate limit (default 600/min). Exceeding it short-circuits
   with a 429 + Retry-After + ``auth.pat_rate_limited`` audit row.
8. Stashes a fully-formed ``Principal`` on the request scope and
   pins the token id on the audit ContextVar so downstream
   ``audit.record(...)`` calls land on the right token.
9. After the response, updates ``last_used_at`` / ip / ua /
   ``use_count`` with a fresh session (the request session is
   already closed by then).

PATs do **not** bypass maintenance mode — when the kill switch
is on, programmatic callers see the same 503 as cookie callers.
The recovery path stays a super-admin's cookie session.

Tokens with no matching row, expired, revoked, or for an inactive
user all return ``401 invalid_token`` (or a more specific code) with
no body that distinguishes between them at the middleware boundary.
The audit log carries the discriminating signal (``pat_invalid`` /
``pat_expired`` / etc.) for ops to inspect.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any, Final

from fastapi import Request, Response
from sqlalchemy import select, update
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.pat_format import (
    LOOKUP_PREFIX_LEN,
    PREFIX,
    validate_format,
)
from app.auth.pat_hashing import verify_token
from app.auth.principal import SCOPE_KEY, Principal
from app.auth.rbac import get_user_permissions
from app.db import get_session_factory
from app.logging import log
from app.models.auth import User
from app.models.auth_token import AuthToken
from app.services.audit import record as record_audit
from app.services.audit import set_token_id
from app.services.pat_rate_limit import check_rate_limit

_BEARER_PREFIX: Final = "Bearer "

# Audit entity used for every PAT-related event. Pairs with
# ``audit_log.token_id`` (FK back to auth_tokens) so the per-token
# trail view can filter on entity OR token_id and pick up the same set.
_AUDIT_ENTITY: Final = "auth_token"


def _401(code: str, message: str | None = None) -> Response:
    body = (
        '{"detail":"unauthorized","code":' + _q(code) + (
            ',"message":' + _q(message) if message else ""
        ) + "}"
    )
    return Response(
        content=body,
        status_code=401,
        media_type="application/json",
    )


def _400(code: str, message: str | None = None) -> Response:
    body = (
        '{"detail":"bad_request","code":' + _q(code) + (
            ',"message":' + _q(message) if message else ""
        ) + "}"
    )
    return Response(
        content=body,
        status_code=400,
        media_type="application/json",
    )


def _429(code: str, retry_after: int) -> Response:
    body = (
        '{"detail":"rate_limited","code":' + _q(code) + "}"
    )
    return Response(
        content=body,
        status_code=429,
        media_type="application/json",
        headers={"Retry-After": str(retry_after)},
    )


def _q(value: str) -> str:
    """Quote a value for inclusion in a hand-built JSON body. Keeps
    us off ``json.dumps`` for hot-path errors but still escapes the
    handful of chars that matter inside a string literal."""
    safe = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{safe}"'


async def _read_pats_config():
    """Read ``app_settings['pats']``. On any failure return the model
    defaults (which include ``enabled=True`` since Phase 4).

    Reading on every PAT-presenting request is fine: PATs are far
    rarer than cookie requests, and a 2-3 ms DB hit per PAT call is
    not the bottleneck. Don't add a process-wide cache without a
    good reason — the maintenance-cache TTL bug class is already
    noisy enough.
    """
    from app.services.app_config import PatsConfig, get_namespace

    factory = get_session_factory()
    try:
        async with factory() as session:
            cfg = await get_namespace(session, "pats")
        if isinstance(cfg, PatsConfig):
            return cfg
        return PatsConfig()
    except Exception as exc:
        log.warning("pat.config_read_failed", error=str(exc))
        return PatsConfig()


async def _emit_audit(
    *,
    action: str,
    token_id: int | None,
    user_id: int | None,
    diff: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit row from middleware code paths.

    Uses a fresh session because the request session (if any) hasn't
    been opened yet — middleware runs outside the dep chain. Failures
    are logged and swallowed: an audit hiccup must never turn an
    otherwise-successful request into a 500, and an auth-rejection
    response shouldn't be masked by a failed audit either.
    """
    try:
        factory = get_session_factory()
        async with factory() as s:
            await record_audit(
                s,
                actor_user_id=user_id,
                entity=_AUDIT_ENTITY,
                # ``audit_log.entity_id`` is non-null. Use 0 as a sentinel
                # for events that don't resolve to a token (URL rejection,
                # DB miss). The token_id column carries the real linkage
                # for events that do.
                entity_id=token_id or 0,
                action=action,
                diff=diff,
                token_id=token_id,
            )
            await s.commit()
    except Exception as exc:
        log.warning(
            "pat.audit_emit_failed", action=action, error=str(exc)
        )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class PATAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate ``Authorization: Bearer atr_pat_*`` requests."""

    async def dispatch(self, request: Request, call_next):
        # 1. URL-token refusal. Tokens belong in ``Authorization``,
        #    nowhere else. A token in the path or query string is a
        #    leak (logs, browser history, referer headers) and we
        #    refuse loudly with an audit row. Substring match is
        #    enough — ``atr_pat_`` never legitimately appears in a
        #    path or query string.
        if PREFIX in (request.url.path or "") or PREFIX in (
            request.url.query or ""
        ):
            await _emit_audit(
                action="in_url_attempt",
                token_id=None,
                user_id=None,
                diff={
                    "path": request.url.path,
                    "ip": _client_ip(request),
                    "user_agent": request.headers.get("user-agent"),
                },
            )
            return _400("token_in_url", "Tokens must travel in Authorization.")

        auth_header = request.headers.get("authorization") or ""
        if not auth_header.startswith(_BEARER_PREFIX):
            return await call_next(request)

        token = auth_header[len(_BEARER_PREFIX):].strip()
        if not token.startswith(PREFIX):
            # Bearer header but not an atrium PAT — leave it for any
            # downstream auth handler. Today nothing else consumes
            # bearer tokens, but cookie auth doesn't care about the
            # header so falling through is harmless.
            return await call_next(request)

        if not validate_format(token):
            # Format-invalid tokens don't generate ``pat_invalid`` —
            # that event is reserved for format-valid tokens that
            # miss the DB (i.e., something close to a real token but
            # wrong). Format-trash is just noise.
            return _401("invalid_token", "Token format invalid.")

        cfg = await _read_pats_config()
        if not cfg.enabled:
            # Don't broadcast that PATs exist if the operator turned
            # them off — same posture as ``/auth/register`` returning
            # 404 when ``allow_signup`` is false.
            log.info("pat.disabled", path=request.url.path)
            return _401("invalid_token")

        prefix = token[:LOOKUP_PREFIX_LEN]
        factory = get_session_factory()
        async with factory() as db:
            # Prefix is 12 chars (8 fixed + 4 random base64url) =
            # ~16.7M distinct prefixes. Collisions are extremely
            # rare but not impossible at scale; ``.scalar()`` would
            # silently drop colliding rows. Fetch all candidates and
            # verify each. Almost always exactly one.
            candidates = (
                await db.scalars(
                    select(AuthToken).where(
                        AuthToken.token_prefix == prefix,
                        AuthToken.revoked_at.is_(None),
                    )
                )
            ).all()
            if not candidates:
                # Format-valid token, no DB row. Could be a stale token
                # the operator already revoked (filtered by the WHERE
                # above) or a brute-force probe. Audit either way —
                # ops can correlate prefixes across the log.
                await _emit_audit(
                    action="invalid",
                    token_id=None,
                    user_id=None,
                    diff={
                        "token_prefix": prefix,
                        "ip": _client_ip(request),
                        "user_agent": request.headers.get("user-agent"),
                    },
                )
                return _401("invalid_token")

            row = next(
                (c for c in candidates if verify_token(token, c.token_hash)),
                None,
            )
            if row is None:
                await _emit_audit(
                    action="invalid",
                    token_id=None,
                    user_id=None,
                    diff={
                        "token_prefix": prefix,
                        "ip": _client_ip(request),
                        "user_agent": request.headers.get("user-agent"),
                    },
                )
                return _401("invalid_token")

            now = datetime.now(UTC).replace(tzinfo=None)
            if row.expires_at is not None and row.expires_at < now:
                await _emit_audit(
                    action="expired",
                    token_id=row.id,
                    user_id=row.user_id,
                    diff={"expires_at": row.expires_at.isoformat()},
                )
                return _401("token_expired")

            user = await db.get(User, row.user_id)
            if user is None or not user.is_active:
                return _401("user_inactive")

            user_permissions = await get_user_permissions(db, user.id)
            stored_scopes = frozenset(row.scopes or [])
            effective_scopes = stored_scopes & user_permissions

            # Detect scope drift the moment the user's permission set
            # has shrunk below the token's stored scopes. Informational
            # — the request still goes through with the intersected
            # permissions; the audit row tells operators why a
            # previously-working call now 403s on a sub-permission.
            removed_scopes = stored_scopes - effective_scopes
            if removed_scopes:
                await _emit_audit(
                    action="scope_reduced",
                    token_id=row.id,
                    user_id=row.user_id,
                    diff={
                        "removed_scopes": sorted(removed_scopes),
                        "stored_scopes": sorted(stored_scopes),
                        "effective_scopes": sorted(effective_scopes),
                    },
                )

            # Per-token rate limit. Sits between auth-success and the
            # principal handoff so a rate-limited request never reaches
            # the route handler at all. Audit BEFORE returning so the
            # 429 trace is attributable.
            allowed, retry_after = check_rate_limit(
                row.id, cfg.default_rate_limit_per_minute
            )
            if not allowed:
                await _emit_audit(
                    action="rate_limited",
                    token_id=row.id,
                    user_id=row.user_id,
                    diff={
                        "ip": _client_ip(request),
                        "user_agent": request.headers.get("user-agent"),
                        "limit_per_minute": cfg.default_rate_limit_per_minute,
                    },
                )
                return _429("rate_limited", retry_after)

            # Sampled "this token was used" event. First use is always
            # logged (use_count==0 before the writeback); subsequent
            # uses are sampled at ``cfg.use_audit_sample_rate``.
            first_use = row.use_count == 0
            if first_use or random.random() < cfg.use_audit_sample_rate:
                await _emit_audit(
                    action="used",
                    token_id=row.id,
                    user_id=row.user_id,
                    diff={
                        "ip": _client_ip(request),
                        "user_agent": request.headers.get("user-agent"),
                        "first_use": first_use,
                    },
                )

            principal = Principal(
                user=user,
                permissions=effective_scopes,
                auth_method=(
                    "service_account_pat"
                    if user.is_service_account
                    else "pat"
                ),
                token_id=row.id,
                auth_session_id=None,
            )
            row_id = row.id

        # Pin the principal on the request scope so ``current_user``
        # and ``current_principal`` short-circuit; pin the token id
        # on the audit ContextVar so downstream ``record(...)`` calls
        # attribute to the issuing token.
        request.scope[SCOPE_KEY] = principal
        set_token_id(row_id)
        try:
            response = await call_next(request)
        finally:
            # Always clear so the contextvar can't leak into a
            # subsequent request handled by the same task.
            set_token_id(None)

        # last_used_at writeback: fresh session because the one above
        # is closed; running after the response so the request itself
        # never blocks on the UPDATE. Best-effort — a failure here
        # mustn't propagate as a 500 to the caller (the request has
        # already finished successfully).
        try:
            async with factory() as db2:
                await db2.execute(
                    update(AuthToken)
                    .where(AuthToken.id == row_id)
                    .values(
                        last_used_at=datetime.now(UTC).replace(tzinfo=None),
                        last_used_ip=_client_ip(request),
                        last_used_user_agent=request.headers.get("user-agent"),
                        use_count=AuthToken.use_count + 1,
                    )
                )
                await db2.commit()
        except Exception as exc:
            log.warning("pat.last_used_writeback_failed", error=str(exc))

        return response
