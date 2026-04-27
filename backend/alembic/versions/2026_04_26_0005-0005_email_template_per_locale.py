# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Per-locale email templates + outbox locale column.

Revision ID: 0005_email_template_per_locale
Revises: 0004_email_verifications
Create Date: 2026-04-26

Reshapes ``email_templates`` from a single-row-per-key store to a
composite-keyed (key, locale) store. Existing rows backfill to
``locale='en'`` so the chain stays valid on upgrade.

Also adds ``email_outbox.locale`` so a queued email persists which
locale variant it was rendered against — the worker re-renders on
retry and a recipient who registered in Dutch should still get the
Dutch body when the relay comes back online.

Seeds nl/de/fr translations for every shipped template
(``invite``, ``password_reset``, ``admin_password_reset_notice``,
``email_otp_code``, ``account_delete_confirm``,
``account_delete_admin_notice``, ``email_verify``). The English
rows already exist (added in 0001 / 0003 / 0004); this migration
only inserts the new locale variants.

Downgrade drops the locale column on both tables and restores the
single-column PK on ``email_templates``. **Data loss is acceptable
on downgrade**: any non-EN row is dropped because the post-downgrade
schema can only hold one row per key. The downgrade body deletes
non-EN rows explicitly before reshaping the PK, so the resulting
table holds the same shape it had at 0004.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_email_template_per_locale"
down_revision = "0004_email_verifications"
branch_labels = None
depends_on = None


# ---- translation payload ----------------------------------------------------
#
# Same markup as the EN seed in 0001 / 0003 / 0004 — only visible copy and
# subjects translate. Technical product names (Atrium) and protocol nouns
# (TOTP, WebAuthn) are preserved across locales by intent.

_TRANSLATIONS: list[dict[str, str]] = [
    # ---- invite ----
    {
        "key": "invite",
        "locale": "nl",
        "subject": "Je bent uitgenodigd voor {{ app_name | default('Atrium') }}",
        "body_html": (
            "<p>Hallo,</p>"
            "<p>{{ invited_by_name }} heeft je uitgenodigd om mee te doen aan "
            "{{ app_name | default('Atrium') }}.</p>"
            "<p><a href=\"{{ accept_url }}\">Accepteer de uitnodiging</a> "
            "en stel je wachtwoord in.</p>"
            "<p>De link verloopt op {{ expires_on }}.</p>"
        ),
    },
    {
        "key": "invite",
        "locale": "de",
        "subject": "Du bist eingeladen zu {{ app_name | default('Atrium') }}",
        "body_html": (
            "<p>Hallo,</p>"
            "<p>{{ invited_by_name }} hat dich eingeladen, "
            "{{ app_name | default('Atrium') }} beizutreten.</p>"
            "<p><a href=\"{{ accept_url }}\">Einladung annehmen</a> "
            "und ein Passwort festlegen.</p>"
            "<p>Der Link laeuft am {{ expires_on }} ab.</p>"
        ),
    },
    {
        "key": "invite",
        "locale": "fr",
        "subject": "Vous etes invite a rejoindre {{ app_name | default('Atrium') }}",
        "body_html": (
            "<p>Bonjour,</p>"
            "<p>{{ invited_by_name }} vous invite a rejoindre "
            "{{ app_name | default('Atrium') }}.</p>"
            "<p><a href=\"{{ accept_url }}\">Accepter l'invitation</a> "
            "et definir votre mot de passe.</p>"
            "<p>Le lien expire le {{ expires_on }}.</p>"
        ),
    },
    # ---- password_reset ----
    {
        "key": "password_reset",
        "locale": "nl",
        "subject": "Stel je wachtwoord opnieuw in",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Je hebt een wachtwoordreset aangevraagd. "
            "<a href=\"{{ reset_url }}\">Klik hier om een nieuw wachtwoord "
            "in te stellen</a>.</p>"
            "<p>Heb je dit niet aangevraagd? Dan kun je deze e-mail negeren.</p>"
        ),
    },
    {
        "key": "password_reset",
        "locale": "de",
        "subject": "Setze dein Passwort zurueck",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Du hast eine Passwort-Zuruecksetzung angefordert. "
            "<a href=\"{{ reset_url }}\">Hier klicken, um ein neues Passwort "
            "festzulegen</a>.</p>"
            "<p>Hast du das nicht angefordert? Dann kannst du diese E-Mail "
            "ignorieren.</p>"
        ),
    },
    {
        "key": "password_reset",
        "locale": "fr",
        "subject": "Reinitialiser votre mot de passe",
        "body_html": (
            "<p>Bonjour {{ recipient.full_name }},</p>"
            "<p>Vous avez demande une reinitialisation de mot de passe. "
            "<a href=\"{{ reset_url }}\">Cliquez ici pour definir un nouveau "
            "mot de passe</a>.</p>"
            "<p>Si vous n'etes pas a l'origine de cette demande, vous pouvez "
            "ignorer ce message.</p>"
        ),
    },
    # ---- admin_password_reset_notice ----
    {
        "key": "admin_password_reset_notice",
        "locale": "nl",
        "subject": "Een beheerder heeft je wachtwoord gereset",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>{{ admin.full_name }} ({{ admin.email }}) heeft zojuist een "
            "wachtwoordreset voor je account in gang gezet. Een aparte e-mail "
            "bevat de resetlink.</p>"
            "<p>Heb je dit niet verwacht? Neem dan contact op met je beheerder.</p>"
        ),
    },
    {
        "key": "admin_password_reset_notice",
        "locale": "de",
        "subject": "Ein Administrator hat dein Passwort zurueckgesetzt",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>{{ admin.full_name }} ({{ admin.email }}) hat soeben eine "
            "Passwort-Zuruecksetzung fuer dein Konto ausgeloest. Eine separate "
            "E-Mail enthaelt den Link zum Zuruecksetzen.</p>"
            "<p>Hast du das nicht erwartet? Wende dich an deinen Administrator.</p>"
        ),
    },
    {
        "key": "admin_password_reset_notice",
        "locale": "fr",
        "subject": "Un administrateur a reinitialise votre mot de passe",
        "body_html": (
            "<p>Bonjour {{ recipient.full_name }},</p>"
            "<p>{{ admin.full_name }} ({{ admin.email }}) vient de declencher "
            "une reinitialisation de mot de passe pour votre compte. Un autre "
            "message contient le lien de reinitialisation.</p>"
            "<p>Si vous ne vous y attendiez pas, contactez votre administrateur.</p>"
        ),
    },
    # ---- email_otp_code ----
    {
        "key": "email_otp_code",
        "locale": "nl",
        "subject": "Je inlogcode",
        "body_html": (
            "<p>Hallo {{ user_name }},</p>"
            "<p>Je inlogcode is <strong>{{ code }}</strong>.</p>"
            "<p>Deze verloopt over 10 minuten. Heb je niet geprobeerd in te "
            "loggen? Dan kun je deze e-mail negeren.</p>"
        ),
    },
    {
        "key": "email_otp_code",
        "locale": "de",
        "subject": "Dein Anmeldecode",
        "body_html": (
            "<p>Hallo {{ user_name }},</p>"
            "<p>Dein Anmeldecode lautet <strong>{{ code }}</strong>.</p>"
            "<p>Er laeuft in 10 Minuten ab. Hast du nicht versucht, dich "
            "anzumelden? Dann kannst du diese E-Mail ignorieren.</p>"
        ),
    },
    {
        "key": "email_otp_code",
        "locale": "fr",
        "subject": "Votre code de connexion",
        "body_html": (
            "<p>Bonjour {{ user_name }},</p>"
            "<p>Votre code de connexion est <strong>{{ code }}</strong>.</p>"
            "<p>Il expire dans 10 minutes. Si vous n'avez pas essaye de vous "
            "connecter, vous pouvez ignorer ce message.</p>"
        ),
    },
    # ---- account_delete_confirm ----
    {
        "key": "account_delete_confirm",
        "locale": "nl",
        "subject": "Je account wordt verwijderd",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Je account wordt verwijderd op "
            "<strong>{{ date }}</strong>.</p>"
            "<p>Tot die datum is inloggen uitgeschakeld. Was dit een vergissing? "
            "Reageer op dit bericht of neem contact op met "
            "<a href=\"mailto:{{ support_email }}\">{{ support_email }}</a> "
            "om de verwijdering te annuleren.</p>"
            "<p>Na {{ date }} worden het account en de persoonsgegevens "
            "definitief verwijderd.</p>"
        ),
    },
    {
        "key": "account_delete_confirm",
        "locale": "de",
        "subject": "Dein Konto wird zur Loeschung vorgemerkt",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Dein Konto wird am <strong>{{ date }}</strong> geloescht.</p>"
            "<p>Bis dahin ist die Anmeldung deaktiviert. War das ein Versehen? "
            "Antworte auf diese Nachricht oder wende dich an "
            "<a href=\"mailto:{{ support_email }}\">{{ support_email }}</a>, "
            "um die Loeschung abzubrechen.</p>"
            "<p>Nach dem {{ date }} werden das Konto und die persoenlichen "
            "Daten dauerhaft entfernt.</p>"
        ),
    },
    {
        "key": "account_delete_confirm",
        "locale": "fr",
        "subject": "Votre compte est programme pour suppression",
        "body_html": (
            "<p>Bonjour {{ recipient.full_name }},</p>"
            "<p>Votre compte est programme pour suppression le "
            "<strong>{{ date }}</strong>.</p>"
            "<p>Jusque-la, la connexion est desactivee. S'il s'agit d'une "
            "erreur, repondez a ce message ou contactez "
            "<a href=\"mailto:{{ support_email }}\">{{ support_email }}</a> "
            "pour annuler la suppression.</p>"
            "<p>Apres le {{ date }}, le compte et les donnees personnelles "
            "seront definitivement supprimes.</p>"
        ),
    },
    # ---- account_delete_admin_notice ----
    {
        "key": "account_delete_admin_notice",
        "locale": "nl",
        "subject": "Account verwijderd door een beheerder",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>{{ admin.full_name }} ({{ admin.email }}) heeft je account "
            "zojuist verwijderd. De persoonsgegevens worden gewist op "
            "{{ date }}.</p>"
            "<p>Heb je dit niet verwacht? Neem contact op met je beheerder.</p>"
        ),
    },
    {
        "key": "account_delete_admin_notice",
        "locale": "de",
        "subject": "Konto durch einen Administrator geloescht",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>{{ admin.full_name }} ({{ admin.email }}) hat soeben dein "
            "Konto geloescht. Die persoenlichen Daten werden am "
            "{{ date }} entfernt.</p>"
            "<p>Hast du das nicht erwartet? Wende dich an deinen Administrator.</p>"
        ),
    },
    {
        "key": "account_delete_admin_notice",
        "locale": "fr",
        "subject": "Compte supprime par un administrateur",
        "body_html": (
            "<p>Bonjour {{ recipient.full_name }},</p>"
            "<p>{{ admin.full_name }} ({{ admin.email }}) vient de supprimer "
            "votre compte. Les donnees personnelles seront purgees le "
            "{{ date }}.</p>"
            "<p>Si vous ne vous y attendiez pas, contactez votre administrateur.</p>"
        ),
    },
    # ---- email_verify ----
    {
        "key": "email_verify",
        "locale": "nl",
        "subject": "Bevestig je e-mailadres voor {{ brand_name }}",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Welkom bij {{ brand_name }}. Bevestig dit e-mailadres "
            "om in te kunnen loggen.</p>"
            "<p><a href=\"{{ verify_url }}\">Bevestig je e-mailadres</a></p>"
            "<p>De link verloopt over 24 uur. Heb je geen account "
            "aangemaakt? Dan kun je dit bericht negeren.</p>"
        ),
    },
    {
        "key": "email_verify",
        "locale": "de",
        "subject": "Bestaetige deine E-Mail-Adresse fuer {{ brand_name }}",
        "body_html": (
            "<p>Hallo {{ recipient.full_name }},</p>"
            "<p>Willkommen bei {{ brand_name }}. Bitte bestaetige diese "
            "E-Mail-Adresse, damit du dich anmelden kannst.</p>"
            "<p><a href=\"{{ verify_url }}\">E-Mail-Adresse bestaetigen</a></p>"
            "<p>Der Link laeuft in 24 Stunden ab. Hast du kein Konto "
            "erstellt? Dann kannst du diese Nachricht ignorieren.</p>"
        ),
    },
    {
        "key": "email_verify",
        "locale": "fr",
        "subject": "Verifiez votre e-mail pour {{ brand_name }}",
        "body_html": (
            "<p>Bonjour {{ recipient.full_name }},</p>"
            "<p>Bienvenue sur {{ brand_name }}. Veuillez confirmer cette "
            "adresse e-mail pour pouvoir vous connecter.</p>"
            "<p><a href=\"{{ verify_url }}\">Verifier votre e-mail</a></p>"
            "<p>Le lien expire dans 24 heures. Si vous n'avez pas cree de "
            "compte, vous pouvez ignorer ce message.</p>"
        ),
    },
]


def _reminder_rules_fk_name(bind: sa.engine.Connection) -> str | None:
    """Return the auto-named FK on ``reminder_rules.template_key`` so we
    can drop it before reshaping the email_templates PK. MySQL refuses
    to drop the referenced PK while a FK still depends on it. The name
    differs between fresh and migrated DBs (the original migration
    didn't pin it), so introspect rather than hardcode."""
    rows = bind.execute(
        sa.text(
            """
            SELECT CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'reminder_rules'
              AND COLUMN_NAME = 'template_key'
              AND REFERENCED_TABLE_NAME = 'email_templates'
            """
        )
    ).fetchone()
    return rows[0] if rows else None


def upgrade() -> None:
    # ---- email_templates: drop PK(key), add locale, add PK(key, locale) ----
    #
    # ``reminder_rules.template_key`` has a FK on ``email_templates.key``.
    # MySQL refuses to drop the referenced PK while the FK is live;
    # drop it here and don't restore it. With per-locale variants the
    # ``key`` column is no longer unique, so the FK can't point at it
    # directly anyway - the reference becomes a soft (application-
    # level) one. Reminder-rule deletion / template removal validation
    # already lives in the API layer.
    bind = op.get_bind()
    fk_name = _reminder_rules_fk_name(bind)
    if fk_name:
        op.drop_constraint(fk_name, "reminder_rules", type_="foreignkey")

    op.add_column(
        "email_templates",
        sa.Column(
            "locale",
            sa.String(10),
            nullable=False,
            server_default="en",
        ),
    )
    # MySQL: ``DROP PRIMARY KEY`` plus a fresh ``ADD PRIMARY KEY`` is
    # the canonical reshape; alembic's ``drop_constraint`` with
    # ``type_='primary'`` translates to that.
    op.execute("ALTER TABLE email_templates DROP PRIMARY KEY")
    op.create_primary_key(
        "pk_email_templates",
        "email_templates",
        ["key", "locale"],
    )

    # ---- email_outbox.locale ------------------------------------------------
    op.add_column(
        "email_outbox",
        sa.Column(
            "locale",
            sa.String(10),
            nullable=False,
            server_default="en",
        ),
    )

    # ---- seed nl/de/fr variants of every shipped template -----------------
    op.bulk_insert(
        sa.table(
            "email_templates",
            sa.column("key", sa.String),
            sa.column("locale", sa.String),
            sa.column("subject", sa.String),
            sa.column("body_html", sa.Text),
            sa.column("description", sa.String),
        ),
        [
            {
                "key": row["key"],
                "locale": row["locale"],
                "subject": row["subject"],
                "body_html": row["body_html"],
                # description is null on translated rows — the EN
                # row owns the description and the admin UI groups
                # by key.
                "description": None,
            }
            for row in _TRANSLATIONS
        ],
    )


def downgrade() -> None:
    # Data loss: any non-EN translations are dropped here so the
    # post-downgrade single-column PK can hold the table's rows.
    op.execute("DELETE FROM email_templates WHERE locale != 'en'")

    op.execute("ALTER TABLE email_templates DROP PRIMARY KEY")
    op.create_primary_key(
        "pk_email_templates_legacy",
        "email_templates",
        ["key"],
    )
    op.drop_column("email_templates", "locale")

    op.drop_column("email_outbox", "locale")

    # Restore the reminder_rules FK that 0001 originally created. The
    # name is regenerated by MySQL (we don't pin it) so introspection
    # can still find it on a future re-upgrade.
    op.create_foreign_key(
        None,
        "reminder_rules",
        "email_templates",
        ["template_key"],
        ["key"],
        ondelete="RESTRICT",
    )
