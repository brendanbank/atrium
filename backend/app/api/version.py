# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""``GET /api/version`` — what this deployment is actually running.

Two layers, because an atrium deployment is two builds stacked: the
atrium base image and (optionally) the host app image built on top of
it. Knowing one without the other has been the recurring support
question — "which atrium is under that app?" previously meant exec-ing
into a container.

Authenticated-only, matching the same call made for the ``version``
field in ``GET /app-config`` (issue #179): an anonymous version string
lets a scanner fingerprint exact dependency versions for CVE matching.
The consumer is the signed-in user menu, so nothing is lost.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.users import current_user
from app.models.auth import User
from app.services.build_info import Component, app_build, atrium_build

router = APIRouter(tags=["meta"])


class ComponentVersion(BaseModel):
    """One build stamp.

    ``name`` is ``"Atrium"`` for the base layer and whatever the host
    image stamped for its own (``None`` when it stamped none).
    ``version`` is the git tag the image was built from; ``commit`` is
    the sha. A tagged release has both, an untagged build has only the
    commit, and an unstamped image (local ``docker compose build``
    without the args) may have neither — the client renders whichever
    is present rather than inventing a placeholder.
    """

    name: str | None = None
    version: str | None = None
    commit: str | None = None

    @classmethod
    def of(cls, component: Component) -> ComponentVersion:
        return cls(
            name=component.name,
            version=component.version,
            commit=component.commit,
        )


class VersionInfo(BaseModel):
    atrium: ComponentVersion
    # ``None`` on a bare atrium deployment — there is no host app layer
    # to report, so the UI shows a single line.
    app: ComponentVersion | None = None


@router.get("/version", response_model=VersionInfo)
async def read_version(_: User = Depends(current_user)) -> VersionInfo:
    host = app_build()
    return VersionInfo(
        atrium=ComponentVersion.of(atrium_build()),
        app=ComponentVersion.of(host) if host else None,
    )
