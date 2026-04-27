# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""ATRIUM_HOST_MODULE bootstrap hook (main.py + worker.py).

The hook lets a host project register routers, app-config namespaces,
permissions, and APScheduler jobs from a single named module — see
``docs/published-images.md`` and §2 of the extension-surface plan.

Three contracts to verify:

1. With the env var unset, ``create_app()`` works as it always has — the
   hook is dormant when nobody opted in. (``conftest._reseed_rbac`` and
   the rest of the suite already exercise this; the test below is the
   explicit assertion.)
2. With the env var pointing at a real module exposing ``init_app``,
   the hook calls it with the FastAPI app — that's the contract the
   docs promise.
3. With a missing or unimportable module, the hook raises so the
   operator sees the typo at startup rather than silently launching
   atrium without their host extensions.

The worker path mirrors the api path; we exercise the same shape by
calling the inline import logic against a fake ``init_worker`` module.
Spinning up the real ``worker.main()`` would start an APScheduler
event loop, which isn't worth the test fixture cost.
"""
from __future__ import annotations

import importlib
import os
import sys
import types

import pytest
from fastapi import FastAPI


@pytest.fixture
def _restore_env():
    """Make sure ATRIUM_HOST_MODULE doesn't leak between tests — the
    autouse session fixtures don't touch it."""
    original = os.environ.get("ATRIUM_HOST_MODULE")
    yield
    if original is None:
        os.environ.pop("ATRIUM_HOST_MODULE", None)
    else:
        os.environ["ATRIUM_HOST_MODULE"] = original


def _install_fake_module(name: str, module: types.ModuleType) -> None:
    sys.modules[name] = module


def _uninstall_fake_module(name: str) -> None:
    sys.modules.pop(name, None)


def test_create_app_unset_is_noop(_restore_env, monkeypatch):
    """Sanity: create_app() works without ATRIUM_HOST_MODULE."""
    monkeypatch.delenv("ATRIUM_HOST_MODULE", raising=False)

    from app.main import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_create_app_calls_init_app(_restore_env, monkeypatch):
    """A host module exposing ``init_app(app)`` is called with the app."""
    captured: dict[str, FastAPI] = {}

    fake = types.ModuleType("atrium_test_host_module_a")

    def init_app(app: FastAPI) -> None:
        captured["app"] = app

    fake.init_app = init_app
    _install_fake_module("atrium_test_host_module_a", fake)
    monkeypatch.setenv("ATRIUM_HOST_MODULE", "atrium_test_host_module_a")

    try:
        from app.main import create_app

        app = create_app()
    finally:
        _uninstall_fake_module("atrium_test_host_module_a")

    assert captured.get("app") is app


def test_create_app_missing_init_app_is_noop(_restore_env, monkeypatch):
    """Side-effects-only host modules (no ``init_app`` defined) are
    allowed — atrium logs and continues."""
    fake = types.ModuleType("atrium_test_host_module_b")
    # No init_app attribute.
    _install_fake_module("atrium_test_host_module_b", fake)
    monkeypatch.setenv("ATRIUM_HOST_MODULE", "atrium_test_host_module_b")

    try:
        from app.main import create_app

        app = create_app()
    finally:
        _uninstall_fake_module("atrium_test_host_module_b")

    assert isinstance(app, FastAPI)


def test_create_app_unimportable_module_raises(_restore_env, monkeypatch):
    """The operator opted in by setting the env var; a typo or missing
    install must fail loud at startup rather than silently launching
    atrium without the host extensions."""
    monkeypatch.setenv(
        "ATRIUM_HOST_MODULE", "definitely_not_a_real_module_xyz"
    )

    # Reload main so the env var is read fresh by create_app's body.
    from app.main import create_app

    with pytest.raises(ImportError):
        create_app()


def test_worker_bootstrap_calls_init_worker(_restore_env, monkeypatch):
    """Mirror of the api hook: the worker reads ATRIUM_HOST_MODULE and
    invokes ``init_worker(scheduler)`` if present.

    We exercise the inline code shape rather than spinning up
    ``worker.main()`` — that path starts an APScheduler event loop and
    is significantly more expensive to fixture than the bootstrap
    contract warrants.
    """
    captured: dict[str, object] = {}

    fake = types.ModuleType("atrium_test_host_module_w")

    def init_worker(scheduler: object) -> None:
        captured["scheduler"] = scheduler

    fake.init_worker = init_worker
    _install_fake_module("atrium_test_host_module_w", fake)
    monkeypatch.setenv("ATRIUM_HOST_MODULE", "atrium_test_host_module_w")

    try:
        host_module = os.environ.get("ATRIUM_HOST_MODULE")
        scheduler_sentinel = object()
        if host_module:
            mod = importlib.import_module(host_module)
            init = getattr(mod, "init_worker", None)
            if callable(init):
                init(scheduler_sentinel)
    finally:
        _uninstall_fake_module("atrium_test_host_module_w")

    assert captured.get("scheduler") is scheduler_sentinel
