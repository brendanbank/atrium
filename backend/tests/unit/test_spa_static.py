# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Regression tests for the SPA catch-all mount.

Issue #252: Starlette's ``Mount`` matches ``websocket`` scopes as well
as ``http`` ones, so a handshake to any path fell through to
``StaticFiles.__call__`` and tripped its ``assert scope["type"] ==
"http"``. Unauthenticated scanners probing for leaked Vite HMR
endpoints turned that into a daily burst of unhandled-ASGI tracebacks.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.static import SPAStaticFiles


@pytest.fixture()
def spa_client(tmp_path):
    (tmp_path / "index.html").write_text("<html>atrium</html>")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app-abc123.js").write_text("console.log(1)")

    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True), name="spa")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/@vite/client", "/admin/audit"])
def test_websocket_handshake_is_rejected_not_crashed(spa_client, path):
    """The handshake must be closed cleanly on every path the catch-all
    mount swallows -- the root, the Vite HMR endpoints scanners probe
    for, and a client-side route the HTTP side answers with the shell.
    Before the fix each of these raised ``AssertionError`` out of the
    ASGI app."""
    with pytest.raises(WebSocketDisconnect), spa_client.websocket_connect(path):
        pass  # pragma: no cover - connect never succeeds


def test_http_still_serves_the_shell(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert "atrium" in resp.text


def test_http_unknown_route_falls_back_to_the_shell(spa_client):
    resp = spa_client.get("/admin/audit")
    assert resp.status_code == 200
    assert "atrium" in resp.text
    assert resp.headers["cache-control"] == "no-store"


def test_assets_keep_immutable_caching(spa_client):
    resp = spa_client.get("/assets/app-abc123.js")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_non_get_unknown_route_does_not_get_the_shell(spa_client):
    """The SPA fallback is GET-only -- a POST to an unknown path gets
    ``StaticFiles``' 405, not a sea of HTML."""
    resp = spa_client.post("/nope")
    assert resp.status_code == 405
    assert "atrium" not in resp.text
