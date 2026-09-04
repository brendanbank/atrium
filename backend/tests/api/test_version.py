# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""``GET /version`` — the two build stamps behind the user menu.

The point of the endpoint is answering "which atrium is this, and
which build of the app on top of it?" from the browser. Three things
have to hold for that to be trustworthy:

* it never answers an anonymous caller (same fingerprinting argument
  as the ``version`` field in ``/app-config``, issue #179),
* a stamped image reports exactly what was baked in, and
* an unstamped one degrades to the source-declared version instead of
  inventing something.
"""
from __future__ import annotations

import pytest

from tests.helpers import login, seed_admin


@pytest.fixture(autouse=True)
def _unstamped(monkeypatch):
    """Start every test from a bare, unstamped image.

    The dev shell (and the Makefile) may well export ATRIUM_COMMIT,
    which would otherwise leak into the assertions below.
    """
    for var in (
        "ATRIUM_VERSION",
        "ATRIUM_COMMIT",
        "ATRIUM_APP_NAME",
        "ATRIUM_APP_VERSION",
        "ATRIUM_APP_COMMIT",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.asyncio
async def test_anonymous_is_refused(client):
    r = await client.get("/version")
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_reports_the_baked_in_stamps(client, engine, monkeypatch):
    monkeypatch.setenv("ATRIUM_VERSION", "v9.9.9")
    monkeypatch.setenv("ATRIUM_COMMIT", "a" * 40)
    monkeypatch.setenv("ATRIUM_APP_NAME", "Hello World")
    monkeypatch.setenv("ATRIUM_APP_VERSION", "1.4.0")
    monkeypatch.setenv("ATRIUM_APP_COMMIT", "b" * 40)

    await seed_admin(engine, email="v@example.com", password="admin-pw-123")
    await login(client, "v@example.com", "admin-pw-123", engine=engine)

    r = await client.get("/version")
    assert r.status_code == 200, r.text
    body = r.json()
    # Verbatim: the ``v`` belongs to the tag and the stamp is meant to
    # be pasted into ``git checkout``.
    assert body["atrium"] == {
        "name": "Atrium",
        "version": "v9.9.9",
        "commit": "a" * 40,
    }
    assert body["app"] == {
        "name": "Hello World",
        "version": "1.4.0",
        "commit": "b" * 40,
    }


@pytest.mark.asyncio
async def test_bare_atrium_reports_no_app_layer(client, engine):
    """Atrium ships no domain layer — with nothing stamped there is no
    second version to report, and the UI renders a single line rather
    than an "unknown" placeholder."""
    await seed_admin(engine, email="bare@example.com", password="admin-pw-123")
    await login(client, "bare@example.com", "admin-pw-123", engine=engine)

    r = await client.get("/version")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["app"] is None, body
    # Unstamped atrium still reports something: the source-declared
    # version, same resolver that feeds window.__ATRIUM_VERSION__.
    assert body["atrium"]["version"], body
    assert body["atrium"]["commit"] is None, body


@pytest.mark.asyncio
async def test_untagged_build_reports_the_commit_only(client, engine, monkeypatch):
    """A build off an untagged commit has no tag to show. The commit is
    the fallback identity — that's the whole reason it's stamped."""
    monkeypatch.setenv("ATRIUM_APP_COMMIT", "c" * 40)

    await seed_admin(engine, email="untagged@example.com", password="admin-pw-123")
    await login(client, "untagged@example.com", "admin-pw-123", engine=engine)

    body = (await client.get("/version")).json()
    assert body["app"] == {"name": None, "version": None, "commit": "c" * 40}
