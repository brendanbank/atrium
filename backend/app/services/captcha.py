# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Pluggable CAPTCHA verification.

Two providers — Cloudflare Turnstile and hCaptcha — share the same
``siteverify`` JSON contract: POST ``secret`` + ``response`` form
fields, expect ``{"success": bool}`` back. The provider toggle and the
site key live in ``AuthConfig``; the secret comes from the
``CAPTCHA_SECRET`` env var so a leaked DB dump can't replay it.

Posture decisions:

* The verifier is **fail-open** on any network or upstream failure —
  same trade-off as the HIBP integration in
  :mod:`app.services.password_policy`. The alternative (an upstream
  hCaptcha incident locking every login out) is worse than a transient
  policy gap. Operators who need fail-closed should run their own
  reverse proxy in front of atrium.
* No caching: tokens are single-use by design. Re-using a token
  successfully would defeat the purpose of the challenge.
* The login middleware reads the request body via ``request.body()``
  (which caches the bytes on the request scope) and parses the
  form/JSON itself. Starlette's ``BaseHTTPMiddleware._CachedRequest``
  re-emits the cached bytes downstream so fastapi-users still sees
  the original payload. Calling ``request.form()`` directly would
  drain the stream without populating ``_body`` — downstream would
  then see an empty body.
"""
from __future__ import annotations

import json
from typing import Final
from urllib.parse import parse_qs

import httpx
from fastapi import Request, Response
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import get_session_factory
from app.logging import log
from app.models.ops import AppSetting
from app.settings import get_settings

_TURNSTILE_URL: Final = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)
_HCAPTCHA_URL: Final = "https://api.hcaptcha.com/siteverify"
_TIMEOUT_SECONDS: Final = 5.0

# Which auth endpoints carry the captcha gate when a provider is on.
# Login + forgot-password go through the middleware (fastapi-users
# routes them); register handles its own check inline because it has
# a JSON body.
_GATED_PATHS: Final = frozenset({
    "/api/auth/jwt/login",
    "/api/auth/forgot-password",
})


async def _read_captcha_provider() -> str:
    """Tiny helper around the ``auth`` namespace lookup that doesn't
    require an injected session — the middleware doesn't have one.

    Fails open on any DB error (missing table on a pre-migration
    deployment, transient infra). Same posture as the rest of this
    module: an upstream / DB issue must not lock users out of
    auth-flow endpoints.
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            raw = (
                await session.execute(
                    select(AppSetting.value).where(AppSetting.key == "auth")
                )
            ).scalar_one_or_none()
    except Exception as exc:
        log.warning("captcha.read_failed", error=str(exc))
        return "none"
    if raw is None:
        return "none"
    return str(raw.get("captcha_provider", "none"))


async def verify_captcha(token: str | None) -> bool:
    """Validate ``token`` against the configured provider.

    Returns True on success **or** when the provider is ``none``
    (feature off). Returns False only when the provider is on, the
    upstream check responded normally, and the token was rejected.

    A network / upstream error returns True (fail-open) and logs a
    warning so operators can spot a sustained outage.
    """
    provider = await _read_captcha_provider()
    if provider == "none":
        return True

    if not token:
        # Provider is on but the client didn't send a token. The widget
        # was either bypassed or the user didn't complete the challenge
        # — both cases are a hard fail.
        return False

    settings = get_settings()
    secret = settings.captcha_secret
    if not secret:
        log.warning(
            "captcha.secret_missing",
            provider=provider,
            note="failing open because CAPTCHA_SECRET is empty",
        )
        return True

    if provider == "turnstile":
        url = _TURNSTILE_URL
    elif provider == "hcaptcha":
        url = _HCAPTCHA_URL
    else:
        # An unknown provider value lands here. Treat it as
        # mis-configuration and fail open with a warning rather than
        # locking everyone out.
        log.warning("captcha.unknown_provider", provider=provider)
        return True

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                data={"secret": secret, "response": token},
            )
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        log.warning(
            "captcha.upstream_unreachable",
            provider=provider,
            error=str(exc),
        )
        return True  # fail-open

    return bool(body.get("success", False))


class CaptchaLoginMiddleware(BaseHTTPMiddleware):
    """Gate ``POST /auth/jwt/login`` and ``POST /auth/forgot-password``
    on a valid CAPTCHA token when the provider is on.

    fastapi-users owns these route handlers, so the cleanest hook is
    here at the middleware layer. ``request.form()`` caches the parsed
    body on the request scope — the downstream handler reads it again
    without re-streaming.

    Off-path requests (any other URL, any other method, captcha
    provider == ``none``) fall through untouched.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST" or request.url.path not in _GATED_PATHS:
            return await call_next(request)

        provider = await _read_captcha_provider()
        if provider == "none":
            return await call_next(request)

        token: str | None = None
        content_type = request.headers.get("content-type", "")
        try:
            # Read the raw bytes; Starlette caches them on the
            # _CachedRequest so the downstream handler still sees
            # them. Parse here ourselves instead of going through
            # request.form() / request.json(), which would drain the
            # stream without populating the cached body.
            body_bytes = await request.body()
            if not body_bytes:
                token = None
            elif "application/x-www-form-urlencoded" in content_type:
                parsed = parse_qs(body_bytes.decode("utf-8", errors="replace"))
                values = parsed.get("captcha_token") or []
                token = values[0] if values else None
            elif "application/json" in content_type:
                payload = json.loads(body_bytes.decode("utf-8", errors="replace"))
                if isinstance(payload, dict):
                    raw = payload.get("captcha_token")
                    token = str(raw) if raw is not None else None
            # multipart/form-data login isn't a configuration we ship,
            # but we don't try to parse it here — the body is left
            # untouched and verify_captcha sees ``token=None``, which
            # is the correct fail-closed behaviour.
        except Exception as exc:
            log.warning("captcha.body_parse_failed", error=str(exc))

        if not await verify_captcha(token):
            return Response(
                content='{"detail":"captcha verification failed"}',
                status_code=400,
                media_type="application/json",
            )
        return await call_next(request)
