# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
