# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Add a paste-able fallback URL line to the password_reset template.

Revision ID: 0007_password_reset_fallback_url
Revises: 0006_email_outbox_perm
Create Date: 2026-04-30

The default ``password_reset`` template's body_html embedded the
reset URL only inside an ``<a href="{{ reset_url }}">…</a>`` anchor.
``send_and_log`` derives the plain-text alternative by stripping
tags, so the URL never reached the plaintext body — readers on
text-only mail clients saw "Click here to set a new password" with
no destination, and the e2e suite couldn't scrape the token from
the console mail backend's stdout capture.

This mirrors the ``email_verify`` template (added in 0004) which
already carries a small "Or paste this link" fallback line outside
the anchor for the same reasons.

Updates all four seeded locales (en / nl / de / fr).

Idempotent via ``UPDATE ... WHERE body_html LIKE ...``: re-running on
an already-patched DB is a no-op because the LIKE clause won't match
the patched rows. Downgrade restores the original anchor-only body.
"""
from __future__ import annotations

from alembic import op

revision = "0007_password_reset_fallback_url"
down_revision = "0006_email_outbox_perm"
branch_labels = None
depends_on = None


# (locale, original anchor-only body, patched body with fallback)
_LOCALES = (
    (
        "en",
        (
            "<p>Hello {{ recipient.full_name }},</p>"
            "<p>You requested a password reset. "
            "<a href=\"{{ reset_url }}\">Click here to set a new password</a>.</p>"
            "<p>If you didn't request this, you can ignore this email.</p>"
        ),
        (
            "<p>Hello {{ recipient.full_name }},</p>"
            "<p>You requested a password reset. "
            "<a href=\"{{ reset_url }}\">Click here to set a new password</a>.</p>"
            "<p style=\"font-size:12px;color:#666\">"
            "Or paste this link: {{ reset_url }}"
            "</p>"
            "<p>If you didn't request this, you can ignore this email.</p>"
        ),
    ),
    (
        "nl",
        (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Je hebt een wachtwoordreset aangevraagd. "
            "<a href=\"{{ reset_url }}\">Klik hier om een nieuw wachtwoord "
            "in te stellen</a>.</p>"
            "<p>Als je dit niet hebt aangevraagd, kun je deze e-mail negeren.</p>"
        ),
        (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Je hebt een wachtwoordreset aangevraagd. "
            "<a href=\"{{ reset_url }}\">Klik hier om een nieuw wachtwoord "
            "in te stellen</a>.</p>"
            "<p style=\"font-size:12px;color:#666\">"
            "Of plak deze link: {{ reset_url }}"
            "</p>"
            "<p>Als je dit niet hebt aangevraagd, kun je deze e-mail negeren.</p>"
        ),
    ),
    (
        "de",
        (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Du hast eine Passwortzurucksetzung angefordert. "
            "<a href=\"{{ reset_url }}\">Hier klicken, um ein neues Passwort "
            "festzulegen</a>.</p>"
            "<p>Falls du das nicht angefordert hast, kannst du diese E-Mail "
            "ignorieren.</p>"
        ),
        (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Du hast eine Passwortzurucksetzung angefordert. "
            "<a href=\"{{ reset_url }}\">Hier klicken, um ein neues Passwort "
            "festzulegen</a>.</p>"
            "<p style=\"font-size:12px;color:#666\">"
            "Oder diesen Link einfugen: {{ reset_url }}"
            "</p>"
            "<p>Falls du das nicht angefordert hast, kannst du diese E-Mail "
            "ignorieren.</p>"
        ),
    ),
    (
        "fr",
        (
            "<p>Bonjour {{ recipient.full_name }},</p>"
            "<p>Vous avez demande la reinitialisation de votre mot de passe. "
            "<a href=\"{{ reset_url }}\">Cliquez ici pour definir un nouveau "
            "mot de passe</a>.</p>"
            "<p>Si vous n'avez pas fait cette demande, ignorez cet e-mail.</p>"
        ),
        (
            "<p>Bonjour {{ recipient.full_name }},</p>"
            "<p>Vous avez demande la reinitialisation de votre mot de passe. "
            "<a href=\"{{ reset_url }}\">Cliquez ici pour definir un nouveau "
            "mot de passe</a>.</p>"
            "<p style=\"font-size:12px;color:#666\">"
            "Ou copiez ce lien : {{ reset_url }}"
            "</p>"
            "<p>Si vous n'avez pas fait cette demande, ignorez cet e-mail.</p>"
        ),
    ),
)


def upgrade() -> None:
    for locale, original, patched in _LOCALES:
        op.execute(
            """
            UPDATE email_templates
            SET body_html = :patched
            WHERE `key` = 'password_reset'
              AND locale = :locale
              AND body_html = :original
            """.replace(":patched", _q(patched))
                .replace(":locale", _q(locale))
                .replace(":original", _q(original))
        )


def downgrade() -> None:
    for locale, original, patched in _LOCALES:
        op.execute(
            """
            UPDATE email_templates
            SET body_html = :original
            WHERE `key` = 'password_reset'
              AND locale = :locale
              AND body_html = :patched
            """.replace(":original", _q(original))
                .replace(":locale", _q(locale))
                .replace(":patched", _q(patched))
        )


def _q(value: str) -> str:
    """Inline a string literal for op.execute. MySQL backslash + single
    quote are the only escapes we need; the bodies don't carry either
    in their raw form."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
