# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Per-locale email template coverage.

What's pinned:

* GET /admin/email-templates returns a flat list of every (key, locale)
  row so the UI can group by key client-side.
* GET /admin/email-templates/{key}/{locale} returns the specific
  variant.
* Fetching a locale that has no row returns 404 from the admin API
  (the admin authoring flow needs to know the row is missing so it can
  upsert) — but ``send_and_log`` falls back to EN so the user-facing
  email never breaks.
* PATCH on an existing variant round-trips. PATCH on a missing
  variant upserts when subject + body_html are both supplied.
* ``send_and_log(..., locale='nl')`` renders the Dutch row when one
  exists; ``locale='es'`` (no row) silently falls back to EN.
* Migration round-trip (alembic upgrade -> downgrade -> upgrade)
  leaves the schema valid in both shapes.
"""
from __future__ import annotations

import os
import subprocess

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.email.sender import render_template, send_and_log
from app.models.email_template import EmailTemplate
from app.models.ops import EmailLog
from tests.helpers import seed_admin

# ---------- admin API ----------


@pytest.mark.asyncio
async def test_list_returns_flat_per_locale_rows(client, engine):
    admin = await seed_admin(engine)
    from tests.helpers import login

    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.get("/admin/email-templates")
    assert r.status_code == 200, r.text
    rows = r.json()
    # Seed migration ships EN + nl/de/fr for each of the seven shipped
    # templates. We only assert the locales are exposed and the
    # invite key has a Dutch variant — exact counts would couple to
    # any future template addition.
    locales = {row["locale"] for row in rows if row["key"] == "invite"}
    assert {"en", "nl", "de", "fr"} <= locales


@pytest.mark.asyncio
async def test_get_specific_variant_returns_localised_body(client, engine):
    admin = await seed_admin(engine)
    from tests.helpers import login

    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.get("/admin/email-templates/invite/nl")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["locale"] == "nl"
    # "Hallo" is the Dutch greeting in the seeded body.
    assert "Hallo" in body["body_html"]


@pytest.mark.asyncio
async def test_get_unknown_locale_returns_404(client, engine):
    admin = await seed_admin(engine)
    from tests.helpers import login

    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.get("/admin/email-templates/invite/es")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_round_trips_localised_body(client, engine):
    admin = await seed_admin(engine)
    from tests.helpers import login

    await login(client, admin.email, "admin-pw-123", engine=engine)

    new_subject = "Neues Thema fuer den Test"
    new_body = "<p>Geaenderter Text {{ recipient.full_name }}</p>"
    r = await client.patch(
        "/admin/email-templates/invite/de",
        json={"subject": new_subject, "body_html": new_body},
    )
    assert r.status_code == 200, r.text

    r2 = await client.get("/admin/email-templates/invite/de")
    assert r2.status_code == 200
    body = r2.json()
    assert body["subject"] == new_subject
    # html_sanitise allows <p>, so the body should round-trip intact.
    assert "Geaenderter Text" in body["body_html"]


@pytest.mark.asyncio
async def test_patch_upserts_new_locale(client, engine):
    admin = await seed_admin(engine)
    from tests.helpers import login

    await login(client, admin.email, "admin-pw-123", engine=engine)

    # 'pt' wasn't seeded — first PATCH creates the row. We use 'pt'
    # rather than 'es' so the fallback-to-EN test below can target a
    # different unseeded locale without colliding with this row (the
    # email_templates table is in the conftest truncate-skip list, so
    # rows persist across tests).
    r = await client.patch(
        "/admin/email-templates/invite/pt",
        json={
            "subject": "Estas convidado",
            "body_html": "<p>Ola {{ invited_by_name }}</p>",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["locale"] == "pt"
    assert body["subject"] == "Estas convidado"

    # Now it's fetchable.
    r2 = await client.get("/admin/email-templates/invite/pt")
    assert r2.status_code == 200

    # Tidy up so subsequent tests don't see the upserted row (the
    # email_templates table is preserved between tests by the
    # conftest's truncate-skip list).
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(
            text(
                "DELETE FROM email_templates WHERE `key`='invite' "
                "AND locale='pt'"
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_patch_unknown_key_returns_404(client, engine):
    admin = await seed_admin(engine)
    from tests.helpers import login

    await login(client, admin.email, "admin-pw-123", engine=engine)

    r = await client.patch(
        "/admin/email-templates/no_such_template/en",
        json={
            "subject": "x",
            "body_html": "<p>x</p>",
        },
    )
    assert r.status_code == 404


# ---------- sender locale resolution ----------


@pytest.mark.asyncio
async def test_render_template_returns_localised_body(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        subject_nl, _, html_nl = await render_template(
            s,
            "invite",
            {
                "invited_by_name": "Carla",
                "accept_url": "https://example.com/a",
                "expires_on": "2026-05-01",
            },
            locale="nl",
        )
    assert "Hallo" in html_nl
    # NL subject contains the literal "uitgenodigd" word.
    assert "uitgenodigd" in subject_nl


@pytest.mark.asyncio
async def test_render_template_unknown_locale_falls_back_to_en(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        subject, _, html = await render_template(
            s,
            "invite",
            {
                "invited_by_name": "Carla",
                "accept_url": "https://example.com/a",
                "expires_on": "2026-05-01",
            },
            locale="es",  # not seeded for 'invite'
        )
    # English subject contains "invited".
    assert "invited" in subject
    assert "Hello" in html


@pytest.mark.asyncio
async def test_send_and_log_renders_french(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await send_and_log(
            s,
            template="invite",
            to=["fr-user@example.com"],
            context={
                "invited_by_name": "Carla",
                "accept_url": "https://example.com/a",
                "expires_on": "2026-05-01",
                "recipient": {"email": "fr-user@example.com", "full_name": ""},
            },
            locale="fr",
        )
        await s.commit()

        rows = (
            await s.execute(
                select(EmailLog).where(
                    EmailLog.to_addr == "fr-user@example.com"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    # The French subject contains the word "invite".
    assert "invite" in rows[0].subject.lower()


@pytest.mark.asyncio
async def test_send_and_log_unknown_locale_falls_back_to_en(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await send_and_log(
            s,
            template="invite",
            to=["es-user@example.com"],
            context={
                "invited_by_name": "Carla",
                "accept_url": "https://example.com/a",
                "expires_on": "2026-05-01",
                "recipient": {"email": "es-user@example.com", "full_name": ""},
            },
            locale="es",  # not seeded
        )
        await s.commit()

        rows = (
            await s.execute(
                select(EmailLog).where(
                    EmailLog.to_addr == "es-user@example.com"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    # English subject "You're invited" - case matches the seed.
    assert "invited" in rows[0].subject.lower()


# ---------- migration round trip ----------


@pytest.mark.asyncio
async def test_migration_round_trip_keeps_schema_valid(engine, mysql_url):
    """``alembic upgrade head -> downgrade -1 -> upgrade head`` keeps
    both the EN-only (downgrade target) and per-locale (head) shapes
    consistent with their migrations.

    We shell out to a fresh alembic process against a sync URL so the
    upgrade/downgrade can run independently of the running asyncio
    loop. Asserts on schema introspection bracket each step.
    """
    # alembic/env.py runs an async engine via asyncio.run, so feed it
    # the aiomysql DSN directly (as the conftest run_migrations fixture
    # does). DATABASE_URL is the override env.py honours when set.
    env = {**os.environ, "DATABASE_URL": mysql_url}

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    def _alembic(args: list[str]) -> None:
        subprocess.run(
            ["uv", "run", "alembic", *args],
            check=True,
            cwd=repo_root,
            env=env,
        )

    # Sanity: head shape has the locale column on both tables.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        cols = {
            r[0]
            for r in (
                await s.execute(text("SHOW COLUMNS FROM email_templates"))
            ).all()
        }
        assert "locale" in cols
        cols_outbox = {
            r[0]
            for r in (
                await s.execute(text("SHOW COLUMNS FROM email_outbox"))
            ).all()
        }
        assert "locale" in cols_outbox

    # Down to 0004 — locale column should disappear from both tables.
    _alembic(["downgrade", "0004_email_verifications"])
    # New connection so we don't read cached metadata.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        cols = {
            r[0]
            for r in (
                await s.execute(text("SHOW COLUMNS FROM email_templates"))
            ).all()
        }
        assert "locale" not in cols

    # Back to head — locale column reappears and translations re-seed.
    _alembic(["upgrade", "head"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        cols = {
            r[0]
            for r in (
                await s.execute(text("SHOW COLUMNS FROM email_templates"))
            ).all()
        }
        assert "locale" in cols
        nl_invite = (
            await s.execute(
                select(EmailTemplate).where(
                    EmailTemplate.key == "invite",
                    EmailTemplate.locale == "nl",
                )
            )
        ).scalar_one_or_none()
        assert nl_invite is not None
