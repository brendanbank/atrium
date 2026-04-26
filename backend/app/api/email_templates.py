"""Admin API for email templates. Owner-only; agents have no reason
to see template content.
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
        select(EmailTemplate).order_by(EmailTemplate.key)
    )
    return list(rows.scalars().all())


@router.get("/{key}", response_model=EmailTemplateRead)
async def get_template(
    key: str,
    _actor: User = Depends(require_perm("email_template.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmailTemplate:
    row = await session.get(EmailTemplate, key)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return row


@router.patch("/{key}", response_model=EmailTemplateRead)
async def update_template(
    key: str,
    payload: EmailTemplateUpdate,
    owner: User = Depends(require_perm("email_template.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmailTemplate:
    row = await session.get(EmailTemplate, key)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    updates = payload.model_dump(exclude_unset=True)
    if "body_html" in updates and updates["body_html"] is not None:
        # Bleach runs on every write so CKEditor or a pasted body
        # containing <script>/on*= handlers / javascript: URLs can't
        # land in the DB. Allowed-list is in services.html_sanitise.
        updates["body_html"] = sanitise_template_body(updates["body_html"])
    for k, v in updates.items():
        setattr(row, k, v)

    # Diff is noisy for HTML — just record which fields changed.
    await record_audit(
        session,
        actor_user_id=owner.id,
        entity="email_template",
        entity_id=0,  # string PK; use 0 + log key in diff
        action="update",
        diff={"key": key, "fields": list(updates.keys())},
    )
    await session.commit()
    await session.refresh(row)
    return row
