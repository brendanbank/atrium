# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DEV_SECRET = "dev-insecure-change-me"
# Valid hex so a fresh checkout boots and can read its own dev rows;
# obviously a placeholder so the prod check below can refuse it.
_DEFAULT_DEV_FIELD_KEY = "00" * 32
_DEFAULT_DEV_PASSWORDS = {
    "test-pw-123",
    "admin-pw-123",
    "user-pw-123",
    "smoke-pw-12345",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "prod"] = "dev"
    app_timezone: str = "UTC"
    app_secret_key: str = "dev-insecure-change-me"
    app_base_url: str = "http://localhost:5173"
    app_role: Literal["api", "worker"] = "api"

    database_url: str = (
        "mysql+aiomysql://atrium:atrium-change-me@mysql:3306/atrium"
    )
    # Connection-pool ceiling per process (api and worker each get their
    # own). SQLAlchemy's stock 5 + 10 is tight for this app: one SPA page
    # load fans out to roughly 15 parallel XHRs, so the defaults left no
    # headroom at all (issue #246). Total connections to MySQL is
    # (pool_size + max_overflow) * processes - keep that under the
    # server's max_connections.
    db_pool_size: int = 10
    db_max_overflow: int = 20

    jwt_secret: str = "dev-insecure-change-me"
    # Default 7 days. No refresh-token rotation is implemented, so this
    # is the hard session limit before the user is bounced to /login.
    jwt_access_token_expire_minutes: int = 60 * 24 * 7
    # Reserved for a future refresh flow; not honored today.
    jwt_refresh_token_expire_days: int = 30

    # "console" (print-only, dev default), "smtp" (real send, prod default),
    # "dummy" (silent drop). Empty string => auto: smtp in prod, console in dev.
    mail_backend: str = ""
    smtp_host: str = "host.docker.internal"
    smtp_port: int = 25
    smtp_use_tls: bool = False
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from: str = "no-reply@example.com"
    mail_reply_to: str = ""

    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # CAPTCHA secret (Cloudflare Turnstile or hCaptcha). Read at request
    # time inside ``services.captcha``. If the provider is enabled but
    # this is empty, ``verify_captcha`` logs a warning and fails open
    # (same posture as the HIBP integration).
    captcha_secret: str = ""

    # WebAuthn / FIDO2 relying-party config. ``rp_id`` is the host
    # the credential is scoped to (no scheme / port — just the
    # domain); ``origin`` is the full origin the browser will be on.
    # Dev defaults match ``make up`` (vite dev on localhost:5173);
    # prod needs the real hostname.
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Atrium"
    webauthn_origin: str = "http://localhost:5173"

    # Master key for host secret columns (``app.host_sdk.crypto``).
    # 32 bytes hex — ``openssl rand -hex 32``. Deliberately separate
    # from APP_SECRET_KEY / JWT_SECRET: rotating a signing secret must
    # not destroy stored data, and a leaked signing key must not also
    # decrypt every credential in the database. Losing this key makes
    # the encrypted columns unrecoverable — back it up outside the
    # database dump. See docs/adr/0003-secret-at-rest.md.
    secret_encryption_key: str = _DEFAULT_DEV_FIELD_KEY

    @model_validator(mode="after")
    def _prod_sanity(self) -> "Settings":
        """Fail loudly at startup when prod-only invariants are broken.

        Catches the three ways a prod deploy could ship with an
        insecure posture: the dev-default secrets slipping through,
        credentialed CORS paired with a ``*`` wildcard, or a placeholder
        bootstrap password never rotated. Each of these was a real
        finding in the security audit (H3 / M5 / L3).

        The field-encryption key is checked for *shape* in every
        environment — a typo there would otherwise boot fine and
        surface as a decrypt failure on the first credential read,
        long after the deploy looked successful.
        """
        try:
            key = bytes.fromhex(self.secret_encryption_key)
        except ValueError as exc:
            raise ValueError(
                "SECRET_ENCRYPTION_KEY must be hex-encoded; generate one "
                "with `openssl rand -hex 32`"
            ) from exc
        if len(key) != 32:
            raise ValueError(
                f"SECRET_ENCRYPTION_KEY decodes to {len(key)} bytes; need 32 "
                "(64 hex chars) — generate one with `openssl rand -hex 32`"
            )

        if self.environment != "prod":
            return self

        if self.secret_encryption_key == _DEFAULT_DEV_FIELD_KEY:
            raise ValueError(
                "SECRET_ENCRYPTION_KEY is still the dev default; set a real "
                "key in .env (`openssl rand -hex 32`). Back it up: losing it "
                "makes every encrypted column unrecoverable."
            )

        if self.app_secret_key == _DEFAULT_DEV_SECRET:
            raise ValueError(
                "APP_SECRET_KEY is still the dev default; set a real secret in .env"
            )
        if self.jwt_secret == _DEFAULT_DEV_SECRET:
            raise ValueError(
                "JWT_SECRET is still the dev default; set a real secret in .env"
            )
        if "*" in self.cors_allow_origins:
            raise ValueError(
                "CORS_ALLOW_ORIGINS contains '*' — incompatible with "
                "credentialed cookies. Set explicit origins in .env."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def is_dev_default_password(password: str) -> bool:
    """Callers (seed-admin, etc.) refuse to persist one of the hard-
    coded dev passwords when running in prod."""
    return password in _DEFAULT_DEV_PASSWORDS
