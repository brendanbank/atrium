# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""App-config endpoints.

Two surfaces:

* ``GET /app-config`` (public) — one bundled JSON of every public
  namespace, hit by the frontend on boot to seed the Mantine theme,
  i18n locales, etc.
* ``GET /admin/app-config`` + ``PUT /admin/app-config/{namespace}``
  (gated on ``app_setting.manage``) — admin UI reads/writes individual
  namespaces. Validation is per-namespace via the Pydantic model
  registered in ``services.app_config.NAMESPACES``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import SCOPE_KEY, Principal
from app.auth.rbac import require_perm
from app.auth.users import _current_user_or_none
from app.db import get_session
from app.models.auth import User
from app.services import app_config as app_config_service
from app.services.audit import record as record_audit

public_router = APIRouter(tags=["app-config"])
admin_router = APIRouter(prefix="/admin/app-config", tags=["admin"])


@public_router.get("/app-config")
async def get_public(
    request: Request,
    user: User | None = Depends(_current_user_or_none),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # The bundle stays anonymous-readable (brand / i18n / system / the
    # auth carve-out), but the backend ``version`` is only handed to an
    # authenticated caller so it can't be used to fingerprint the
    # deployment pre-login (issue #179). A cookie session (even partial,
    # pre-2FA) or a PAT-authed request both count as authenticated.
    pat_principal = request.scope.get(SCOPE_KEY)
    authenticated = user is not None or isinstance(pat_principal, Principal)
    return await app_config_service.get_public_config(
        session, include_version=authenticated
    )


@admin_router.get("")
async def get_admin(
    _actor: User = Depends(require_perm("app_setting.manage")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await app_config_service.get_all_admin_config(session)


@admin_router.put("/{namespace}")
async def put_namespace_endpoint(
    namespace: str,
    payload: dict[str, Any],
    actor: User = Depends(require_perm("app_setting.manage")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if namespace not in app_config_service.NAMESPACES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown namespace '{namespace}'",
        )
    try:
        validated = await app_config_service.put_namespace(
            session, namespace, payload
        )
    except ValueError as exc:
        # Pydantic validation failure — surface the message instead of
        # a generic 500 so the admin UI can show what's wrong.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await record_audit(
        session,
        actor_user_id=actor.id,
        entity="app_setting",
        entity_id=0,
        action="update",
        diff={"namespace": namespace, "fields": list(payload.keys())},
    )
    await session.commit()
    return validated.model_dump(mode="json")
