# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Personal Access Token wire format.

Layout::

    atr_pat_<32 base64url chars>_<6 base32 CRC chars>

- ``atr_pat_`` (8 chars, fixed) — type identifier. Lets log redactors
  and GitHub secret-scanning recognise atrium PATs even when they
  appear out of context.
- 32 base64url chars (24 random bytes) — the secret. 192 bits of
  entropy, URL-safe so headers don't need escaping.
- ``_`` separator.
- 6 base32 chars (lowercase) — CRC32 over ``prefix + secret``. Lets
  the middleware reject malformed / typo'd tokens before doing a
  DB lookup or argon2 verify.

Total: 47 chars. Fits comfortably in an ``Authorization`` header.

The first 12 chars (``atr_pat_`` + 4 random) are stored unhashed as
``token_prefix`` for indexed lookup; the full token is argon2-hashed.
"""
from __future__ import annotations

import base64
import secrets
import zlib

PREFIX = "atr_pat_"
SECRET_LEN = 32
CRC_LEN = 6
TOKEN_LEN = len(PREFIX) + SECRET_LEN + 1 + CRC_LEN  # 47
LOOKUP_PREFIX_LEN = 12


def _crc(body: str) -> str:
    crc_int = zlib.crc32(body.encode())
    return (
        base64.b32encode(crc_int.to_bytes(4, "big"))
        .rstrip(b"=")
        .decode()
        .lower()[:CRC_LEN]
    )


def generate_token() -> tuple[str, str]:
    """Mint a fresh PAT.

    Returns ``(full_token, lookup_prefix)``. ``full_token`` is the
    plaintext to hand back to the operator exactly once; never store
    it. ``lookup_prefix`` is the first 12 chars (``atr_pat_`` + 4 of
    the secret) and is what the middleware looks up before doing the
    argon2 verify.
    """
    secret_bytes = secrets.token_bytes(24)  # 24 bytes = 32 base64url chars (no pad)
    secret = base64.urlsafe_b64encode(secret_bytes).rstrip(b"=").decode()
    body = PREFIX + secret
    full_token = f"{body}_{_crc(body)}"
    return full_token, full_token[:LOOKUP_PREFIX_LEN]


def validate_format(token: str) -> bool:
    """Cheap format + CRC check. No DB, no hashing.

    Catches typos, wrong-type bearers, accidentally-sent JWTs etc.
    before the request burns an argon2 verify.
    """
    if not token.startswith(PREFIX):
        return False
    if len(token) != TOKEN_LEN:
        return False
    body, sep, crc = token.rpartition("_")
    if not body or not crc or sep != "_" or len(crc) != CRC_LEN:
        return False
    if not body.startswith(PREFIX):
        return False
    return secrets.compare_digest(crc, _crc(body))


def lookup_prefix(token: str) -> str:
    """Extract the indexed-lookup prefix from a (presumed valid)
    token. Caller is responsible for ``validate_format`` first."""
    return token[:LOOKUP_PREFIX_LEN]
