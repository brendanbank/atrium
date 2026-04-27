# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from __future__ import annotations

import pytest

from app.email.backend import (
    ConsoleMailBackend,
    EmailMessage,
    SmtpMailBackend,
    _resolve_backend_name,
    get_mail_backend,
    reset_mail_backend_for_tests,
)
from app.settings import get_settings


@pytest.fixture(autouse=True)
def _reset():
    reset_mail_backend_for_tests()
    get_settings.cache_clear()
    yield
    reset_mail_backend_for_tests()
    get_settings.cache_clear()


def test_dev_defaults_to_console(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("MAIL_BACKEND", raising=False)
    get_settings.cache_clear()
    assert _resolve_backend_name() == "console"
    assert isinstance(get_mail_backend(), ConsoleMailBackend)


def test_prod_defaults_to_smtp(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    # Prod settings refuse the dev-default APP_SECRET_KEY + JWT_SECRET
    # (see migration-era security hardening). Supply non-defaults so
    # the Settings() construction doesn't explode.
    monkeypatch.setenv("APP_SECRET_KEY", "test-prod-secret-not-a-default")
    monkeypatch.setenv("JWT_SECRET", "test-prod-jwt-not-a-default")
    monkeypatch.delenv("MAIL_BACKEND", raising=False)
    get_settings.cache_clear()
    assert _resolve_backend_name() == "smtp"
    assert isinstance(get_mail_backend(), SmtpMailBackend)


def test_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("APP_SECRET_KEY", "test-prod-secret-not-a-default")
    monkeypatch.setenv("JWT_SECRET", "test-prod-jwt-not-a-default")
    monkeypatch.setenv("MAIL_BACKEND", "console")
    get_settings.cache_clear()
    assert _resolve_backend_name() == "console"


def test_console_backend_does_not_raise_without_smtp(monkeypatch):
    """The whole point: dev work never tries to open an SMTP socket."""
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("SMTP_HOST", "unreachable.invalid")
    get_settings.cache_clear()

    import asyncio

    backend = ConsoleMailBackend()
    asyncio.run(
        backend.send(
            EmailMessage(
                to=["guest@example.com"],
                subject="Hello",
                body_text="Safe in dev",
                template="test",
            )
        )
    )
