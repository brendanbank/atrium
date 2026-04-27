# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailTemplate(Base):
    """Editable email template.

    Composite PK ``(key, locale)`` — one row per (template, language)
    pair. The English row is the canonical fallback when a recipient's
    ``preferred_language`` has no translation. ``locale`` is a 10-char
    string so it can hold BCP-47 region tags like ``en-US`` or ``pt-BR``
    if a host app needs them; the seed only ships base codes.

    Subject is a single Jinja line; body is HTML (as produced by
    CKEditor) with Jinja expressions inside.
    """
    __tablename__ = "email_templates"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    locale: Mapped[str] = mapped_column(
        String(10), primary_key=True, default="en", server_default="en"
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
