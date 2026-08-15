# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Secret-at-rest primitive for host columns.

A host declares a secret field and gets AES-256-GCM at rest without
making any cryptographic decisions::

    from app.host_sdk.crypto import EncryptedText, MaskedSecret

    class LlmProvider(HostBase):
        __tablename__ = "llm_providers"
        api_key: Mapped[MaskedSecret] = mapped_column(
            EncryptedText(purpose="llm_provider.api_key", scope="site"),
            nullable=False,
        )

Reads return a :class:`MaskedSecret`, not a ``str`` — call
``.reveal()`` at the point of use. See
``docs/adr/0003-secret-at-rest.md`` for why the column type returns a
wrapper, why the wire format carries a header from the first commit,
and why ``scope="user"`` raises instead of quietly behaving like
``site``.

Wire format::

    ATR | version(1) | scope(1) | nonce(12) | ciphertext | tag(16)

The 5-byte header is passed to the AEAD as associated data, so editing
it on a stored row fails the tag rather than selecting a different key
path.

Not supported, deliberately: indexes / uniqueness / ``ORDER BY`` /
``LIKE`` over an encrypted column, automated key rotation (declare a
second column at ``key_version="v2"``, backfill, drop the first), and
per-user keys. ``purpose`` binds a ciphertext to a column but not to a
row.
"""
from __future__ import annotations

import hmac
import json
import os
from functools import lru_cache
from typing import Any, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import LargeBinary
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.types import TypeDecorator

from app.settings import get_settings

__all__ = [
    "EncryptedJSON",
    "EncryptedText",
    "MaskedSecret",
    "SecretDecryptError",
    "SecretScope",
    "apply_secret_update",
]

SecretScope = Literal["site", "user"]

MAGIC = b"ATR"
WIRE_VERSION = 1
HEADER_BYTES = len(MAGIC) + 2

NONCE_BYTES = 12
KEY_BYTES = 32
GCM_TAG_BYTES = 16

# Domain-separates this KDF from any other HKDF use in the codebase.
# Never change it: every stored blob was written under it.
HKDF_SALT = b"atrium.field-encryption.v1"

_SCOPE_BYTE: dict[str, int] = {"site": 1, "user": 2}

_USER_SCOPE_NOT_IMPLEMENTED = (
    "scope='user' is not implemented. It is not a different salt — it "
    "needs a request-scoped owner binding, defined behaviour outside a "
    "request scope (workers included), the owner bound into the AEAD's "
    "associated data, and a key-wrap record with shredding semantics. "
    "See docs/adr/0003-secret-at-rest.md and issue #225. Use "
    "scope='site' for a secret the whole installation shares."
)


class SecretDecryptError(RuntimeError):
    """A stored secret could not be decrypted.

    Names the ``purpose`` because the raw failure is an ``InvalidTag``
    raised deep inside SQLAlchemy's result processing — with no
    indication of which column, on an endpoint that may not look like
    it touches secrets at all.
    """


class MaskedSecret:
    """A decrypted secret that does not render itself.

    Deliberately **not** a ``str`` subclass: subclassing would satisfy
    every ``isinstance(value, str)`` check in the codebase — including
    the first branch of ``services.audit._json_safe`` — and leak the
    cleartext into exactly the places this type exists to keep it out
    of. Rendering is ``***``, so a stray f-string or an audit diff
    produces a redaction rather than a credential.

    Call :meth:`reveal` at the point of use, and nowhere else.
    """

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = value

    def reveal(self) -> Any:
        """Return the cleartext. Every call site is a review point."""
        return self._value

    def hint(self, chars: int = 4) -> str:
        """Last ``chars`` characters, for "which key is this?" UI.

        Empty for a non-string secret or one too short to hint at
        without giving most of it away. A hint is right for an API key
        and wrong for a password — it is opt-in per endpoint, not
        something the column decides.
        """
        if not isinstance(self._value, str) or len(self._value) <= chars:
            return ""
        return self._value[-chars:]

    def __repr__(self) -> str:
        return "MaskedSecret('***')"

    def __str__(self) -> str:
        return "***"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MaskedSecret):
            other = other._value
        if isinstance(self._value, str) and isinstance(other, str):
            return hmac.compare_digest(self._value, other)
        return bool(self._value == other)

    # __eq__ without __hash__ makes the type unhashable, which is the
    # behaviour we want: a secret has no business being a dict key or
    # landing in a set.
    __hash__ = None  # type: ignore[assignment]


def _reject_user_scope(scope: str) -> str:
    if scope == "user":
        raise NotImplementedError(_USER_SCOPE_NOT_IMPLEMENTED)
    if scope not in _SCOPE_BYTE:
        raise ValueError(
            f"unknown scope {scope!r}; expected 'site' (or 'user', unimplemented)"
        )
    return scope


@lru_cache(maxsize=64)
def _derive_key(master_hex: str, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=HKDF_SALT,
        info=info,
    ).derive(bytes.fromhex(master_hex))


def _master_key_hex() -> str:
    """The configured master, already format-validated at startup.

    ``Settings`` rejects a malformed key in every environment and the
    dev default in prod, so by the time a column is read the value is
    known-good. Reading it here rather than caching module-side keeps
    ``get_settings.cache_clear()`` sufficient for tests.
    """
    return get_settings().secret_encryption_key


def _header(scope: str) -> bytes:
    return MAGIC + bytes([WIRE_VERSION, _SCOPE_BYTE[scope]])


def _encrypt(plaintext: bytes, *, purpose: str, key_version: str, scope: str) -> bytes:
    info = f"{scope}.{purpose}.{key_version}".encode("ascii")
    header = _header(scope)
    nonce = os.urandom(NONCE_BYTES)
    ct = AESGCM(_derive_key(_master_key_hex(), info)).encrypt(
        nonce, plaintext, associated_data=header
    )
    return header + nonce + ct


def _decrypt(blob: bytes, *, purpose: str, key_version: str, scope: str) -> bytes:
    header = _header(scope)
    if not blob.startswith(MAGIC):
        raise SecretDecryptError(
            f"{purpose}: stored value is not an atrium secret blob "
            "(missing magic prefix)"
        )
    if blob[:HEADER_BYTES] != header:
        got_version, got_scope = blob[len(MAGIC)], blob[len(MAGIC) + 1]
        raise SecretDecryptError(
            f"{purpose}: blob was written as wire v{got_version} scope "
            f"byte {got_scope}, column expects v{WIRE_VERSION} scope "
            f"{scope!r}"
        )
    payload = blob[HEADER_BYTES:]
    if len(payload) < NONCE_BYTES + GCM_TAG_BYTES:
        raise SecretDecryptError(f"{purpose}: ciphertext blob too short")
    info = f"{scope}.{purpose}.{key_version}".encode("ascii")
    nonce, ct = payload[:NONCE_BYTES], payload[NONCE_BYTES:]
    try:
        return AESGCM(_derive_key(_master_key_hex(), info)).decrypt(
            nonce, ct, associated_data=header
        )
    except InvalidTag as exc:
        raise SecretDecryptError(
            f"{purpose}: decryption failed. Either SECRET_ENCRYPTION_KEY "
            "is not the key this row was written under, or the row was "
            "written for a different purpose / key_version."
        ) from exc


class _EncryptedBase(TypeDecorator):
    """Shared plumbing for the encrypted column types."""

    impl = LargeBinary
    cache_ok = True

    def __init__(
        self,
        *,
        purpose: str,
        key_version: str = "v1",
        scope: SecretScope = "site",
    ) -> None:
        super().__init__()
        if not purpose:
            raise ValueError("purpose is required — it is what stops a "
                             "ciphertext being moved between columns")
        self.purpose = purpose
        self.key_version = key_version
        self.scope = _reject_user_scope(scope)

    def load_dialect_impl(self, dialect):
        # MySQL maps LargeBinary to BLOB (64 KB). atrium-pa hit that
        # ceiling in production with real payloads; MEDIUMBLOB (16 MB)
        # costs nothing here and a migration later.
        if dialect.name in ("mysql", "mariadb"):
            return dialect.type_descriptor(MEDIUMBLOB())
        return dialect.type_descriptor(LargeBinary())

    def _encrypt(self, plaintext: bytes) -> bytes:
        return _encrypt(
            plaintext,
            purpose=self.purpose,
            key_version=self.key_version,
            scope=self.scope,
        )

    def _decrypt(self, blob: bytes) -> bytes:
        return _decrypt(
            blob,
            purpose=self.purpose,
            key_version=self.key_version,
            scope=self.scope,
        )


class EncryptedText(_EncryptedBase):
    """AES-256-GCM-encrypted UTF-8 text column.

    Accepts ``str`` or :class:`MaskedSecret` on write (so a loaded row
    can be re-saved without unwrapping); returns
    :class:`MaskedSecret` on read.
    """

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, MaskedSecret):
            value = value.reveal()
        if not isinstance(value, str):
            raise TypeError(
                f"{self.purpose}: expected str or MaskedSecret, got "
                f"{type(value).__name__}"
            )
        return self._encrypt(value.encode("utf-8"))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return MaskedSecret(self._decrypt(value).decode("utf-8"))


class EncryptedJSON(_EncryptedBase):
    """AES-256-GCM-encrypted JSON column.

    Same wire shape as :class:`EncryptedText`; the difference is
    compact UTF-8 JSON serialisation before encryption. Reads return a
    :class:`MaskedSecret` wrapping the decoded value — a payload kept
    encrypted at rest should not become loggable just because it
    happens to be a dict.
    """

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, MaskedSecret):
            value = value.reveal()
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        return self._encrypt(encoded.encode("utf-8"))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return MaskedSecret(json.loads(self._decrypt(value).decode("utf-8")))


def apply_secret_update(obj: Any, field: str, incoming: str | None) -> bool:
    """Apply an inbound secret value under the blank-preserves rule.

    The convention, and the reason it needs a helper rather than a
    docs bullet:

    - ``None`` (an explicit JSON ``null``) **clears** the secret.
    - ``""`` — which is also what an absent field looks like when the
      schema defaults to ``""`` — **preserves** the stored ciphertext.
    - anything else is the new secret.

    Without the clear-path, "blank preserves" leaves a secret that can
    be set or kept but never unset. Without "blank preserves", editing
    an unrelated field on the same form silently blanks the credential
    and the failure surfaces much later as an auth error with no
    obvious cause.

    Returns ``True`` when the attribute was touched, so callers can
    skip a needless re-encrypt (and a misleading audit diff) on a
    no-op update.
    """
    if incoming is None:
        setattr(obj, field, None)
        return True
    if incoming == "":
        return False
    setattr(obj, field, incoming)
    return True
