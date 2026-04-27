# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Admin API for email templates. Owner-only; agents have no reason
to see template content.

Templates are keyed on ``(key, locale)``. The list endpoint returns a
flat array of every (key, locale) row so the admin UI can group by key
client-side; the get/patch endpoints are scoped on both axes. PATCH
upserts when the (key, locale) row doesn't yet exist - the EN row is
guaranteed by the seed migration, so authoring a fresh translation
just creates its row on first save.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_perm
from app.db import get_session
from app.models.auth import User
from app.models.email_template import EmailTemplate
from app.schemas.email_template import EmailTemplateRead, EmailTemplateUpdate
from app.services.audit import record as record_audit
from app.services.html_sanitise import sanitise_template_body

router = APIRouter(prefix="/admin/email-templates", tags=["admin"])


@router.get("", response_model=list[EmailTemplateRead])
async def list_templates(
    _actor: User = Depends(require_perm("email_template.manage")),
    session: AsyncSession = Depends(get_session),
) -> list[EmailTemplate]:
    rows = await session.execute(
        select(EmailTemplate).order_by(
            EmailTemplate.key, EmailTemplate.locale
        )
    )
    return list(rows.scalars().all())


@router.get("/{key}/{locale}", response_model=EmailTemplateRead)
async def get_template(
    key: str,
    locale: str,
    _actor: User = Depends(require_perm("email_template.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmailTemplate:
    row = await session.get(EmailTemplate, (key, locale))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return row


@router.patch("/{key}/{locale}", response_model=EmailTemplateRead)
async def update_template(
    key: str,
    locale: str,
    payload: EmailTemplateUpdate,
    owner: User = Depends(require_perm("email_template.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmailTemplate:
    row = await session.get(EmailTemplate, (key, locale))
    updates = payload.model_dump(exclude_unset=True)
    if "body_html" in updates and updates["body_html"] is not None:
        # Bleach runs on every write so CKEditor or a pasted body
        # containing <script>/on*= handlers / javascript: URLs can't
        # land in the DB. Allowed-list is in services.html_sanitise.
        updates["body_html"] = sanitise_template_body(updates["body_html"])

    if row is None:
        # Upsert: enabling a new locale and authoring its first
        # translation would otherwise need a separate POST step. We
        # require subject + body_html so the new row passes the
        # NOT NULL constraints; description is optional.
        if not updates.get("subject") or not updates.get("body_html"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "template variant not found - PATCH must include "
                    "subject and body_html to create a new locale row"
                ),
            )
        # Confirm the base template (any locale) exists - we only
        # auto-create translations of templates the host has shipped,
        # not arbitrary new keys.
        any_locale = (
            await session.execute(
                select(EmailTemplate).where(EmailTemplate.key == key).limit(1)
            )
        ).scalar_one_or_none()
        if any_locale is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        row = EmailTemplate(
            key=key,
            locale=locale,
            subject=updates["subject"],
            body_html=updates["body_html"],
            description=updates.get("description"),
        )
        session.add(row)
    else:
        for k, v in updates.items():
            setattr(row, k, v)

    # Diff is noisy for HTML — just record which fields changed plus
    # the (key, locale) pair so the audit trail attributes the edit to
    # a specific variant.
    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="email_template",
        entity_id=0,  # composite PK; log key + locale in diff
        action="update",
        diff={"key": key, "locale": locale, "fields": list(updates.keys())},
    )
    await session.commit()
    await session.refresh(row)
    return row
