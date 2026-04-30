# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

import importlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.account_deletion import admin_router as account_deletion_admin_router
from app.api.account_deletion import self_router as account_deletion_self_router
from app.api.admin_roles import router as admin_roles_router
from app.api.admin_users import router as admin_users_router
from app.api.app_config import admin_router as app_config_admin_router
from app.api.app_config import public_router as app_config_public_router
from app.api.audit import router as audit_router
from app.api.email_otp import router as email_otp_router
from app.api.email_outbox import router as email_outbox_router
from app.api.email_templates import router as email_templates_router
from app.api.health import router as health_router
from app.api.impersonate import (
    IMPERSONATOR_COOKIE,
    _read_impersonator,
)
from app.api.impersonate import router as impersonate_router
from app.api.invites import router as invites_router
from app.api.me_context import router as me_context_router
from app.api.notifications import router as notifications_router
from app.api.reminder_rules import router as reminder_rules_router
from app.api.sessions import router as sessions_router
from app.api.signup import router as signup_router
from app.api.totp import admin_router as totp_admin_router
from app.api.totp import router as totp_router
from app.api.webauthn import router as webauthn_router
from app.auth.backend import auth_backend
from app.auth.schemas import UserRead, UserUpdate
from app.auth.users import fastapi_users
from app.logging import configure_logging, log
from app.services.audit import set_impersonator
from app.services.captcha import CaptchaLoginMiddleware
from app.services.maintenance import MaintenanceMiddleware
from app.services.rate_limit import AuthRateLimitMiddleware
from app.settings import get_settings
from app.static import SPAStaticFiles


class ImpersonationAuditMiddleware(BaseHTTPMiddleware):
    """Populate the audit-log ContextVar with the actor behind an
    impersonated session, so ``record_audit`` attributes actions to the
    real super_admin rather than to the user they're acting as.

    Runs for every request — no-op when the impersonator cookie is
    absent or invalid. Clears the contextvar after the
    response to avoid bleed across worker-recycled coroutines (FastAPI
    reuses the same event-loop task for the request, so ContextVar is
    request-scoped in practice, but resetting is cheap and safer if a
    handler schedules background work).
    """

    async def dispatch(self, request: Request, call_next):
        actor_id: int | None = None
        token = request.cookies.get(IMPERSONATOR_COOKIE)
        if token:
            try:
                actor_id = _read_impersonator(token)
            except Exception:
                # Stale or tampered cookie — ignore, continue as a
                # normal session. Log at debug level only; every
                # request fires if an old cookie lingers.
                actor_id = None
        set_impersonator(actor_id)
        try:
            response = await call_next(request)
        finally:
            set_impersonator(None)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("app.startup", environment=get_settings().environment)
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Atrium API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ImpersonationAuditMiddleware)
    app.add_middleware(AuthRateLimitMiddleware)
    # CaptchaLoginMiddleware sits between rate-limit and maintenance:
    # rate-limits still apply to a request that fails the captcha
    # (otherwise an attacker with a valid token could DoS login), but
    # the maintenance gate wins so a 503 isn't masked by a 400.
    app.add_middleware(CaptchaLoginMiddleware)
    # Outermost so it short-circuits before the rate-limiter or audit
    # middleware bother to spin up; otherwise a 503 still costs us a
    # rate-limit bucket increment.
    app.add_middleware(MaintenanceMiddleware)

    # Every JSON route lives under ``/api/...`` so the SPA owns the
    # un-prefixed URL space (``/admin/users``, ``/notifications`` etc.
    # are SPA routes). Without this split, a hard reload of an SPA
    # admin page would resolve to the API JSON because the API route
    # matches first and ``SPAStaticFiles`` only falls back on a 404.
    # See issue #89.
    api_router = APIRouter()
    api_router.include_router(health_router)

    # Auth routes — no public /register; invite flow is the only path.
    api_router.include_router(
        fastapi_users.get_auth_router(auth_backend),
        prefix="/auth/jwt",
        tags=["auth"],
    )
    api_router.include_router(
        fastapi_users.get_reset_password_router(),
        prefix="/auth",
        tags=["auth"],
    )
    api_router.include_router(
        fastapi_users.get_verify_router(UserRead),
        prefix="/auth",
        tags=["auth"],
    )
    # GET /users/me + PATCH /users/me for self-service.
    # Superuser-only routes (GET /{id}, PATCH /{id}, DELETE /{id}) come free.
    api_router.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/users",
        tags=["users"],
    )

    api_router.include_router(app_config_public_router)
    api_router.include_router(app_config_admin_router)
    api_router.include_router(invites_router)
    api_router.include_router(notifications_router)
    api_router.include_router(admin_users_router)
    api_router.include_router(admin_roles_router)
    api_router.include_router(impersonate_router)
    api_router.include_router(me_context_router)
    api_router.include_router(audit_router)
    api_router.include_router(email_templates_router)
    api_router.include_router(email_outbox_router)
    api_router.include_router(reminder_rules_router)
    api_router.include_router(sessions_router)
    api_router.include_router(totp_router)
    api_router.include_router(totp_admin_router)
    api_router.include_router(email_otp_router)
    api_router.include_router(webauthn_router)
    api_router.include_router(account_deletion_self_router)
    api_router.include_router(account_deletion_admin_router)
    api_router.include_router(signup_router)

    app.include_router(api_router, prefix="/api")

    host_module = os.environ.get("ATRIUM_HOST_MODULE")
    if host_module:
        # ImportError is intentionally loud — the operator opted in by
        # setting the env var, so a typo or missing dep should fail
        # startup rather than silently launch atrium without the host.
        # Hosts must mount their own routes under /api/... so they
        # don't shadow SPA routes (see issue #89). Atrium does not
        # prefix on the host's behalf — the host owns its full path.
        mod = importlib.import_module(host_module)
        init = getattr(mod, "init_app", None)
        if callable(init):
            init(app)
        else:
            log.info(
                "host.init_app.absent", module=host_module
            )

    # Mount the built SPA last so it acts as the catch-all. Conditional
    # on the directory existing so a dev tree without ``pnpm build``
    # still boots — Vite's dev server on :5173 covers that workflow.
    static_dir = Path(os.environ.get("ATRIUM_STATIC_DIR", "/opt/atrium/static"))
    if static_dir.is_dir():
        app.mount("/", SPAStaticFiles(directory=str(static_dir), html=True), name="spa")

    return app


app = create_app()
