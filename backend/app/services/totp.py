# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""TOTP helpers — enrollment + verification.

Thin wrapper over ``pyotp`` that hides the step/digits/algorithm choices
so callers don't have to get them right every time. We stay on the
defaults (SHA-1, 6 digits, 30 s step) for universal authenticator-app
compatibility.

``verify_code`` tolerates a ±1-step clock skew, which is the standard
accommodation for phones that aren't NTP-synced. Replay protection is
not layered on top — see ``/auth/totp/verify`` for the rationale (the
session's ``totp_passed`` flag is the durable gate).
"""
from __future__ import annotations

import pyotp

_ISSUER = "Atrium"


def generate_secret() -> str:
    """Return a fresh base32 TOTP seed (160 bits / 32 chars)."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_email: str) -> str:
    """otpauth:// URI suitable for a QR encode.

    Any RFC-6238 authenticator (Google Authenticator, 1Password,
    Authy, Bitwarden, etc.) will accept it. ``issuer_name`` lets the
    app show "Atrium" (or whatever ``_ISSUER`` is) next to the entry.
    """
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_email, issuer_name=_ISSUER
    )


def verify_code(secret: str, code: str, *, valid_window: int = 1) -> bool:
    """Constant-time verification with ±``valid_window`` 30 s steps of slack."""
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)
