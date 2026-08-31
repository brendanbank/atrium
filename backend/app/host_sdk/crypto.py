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
from sqlalchemy import LargeBinary, event
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.types import TypeDecorator

from app.settings import get_settings

__all__ = [
    "EncryptedJSON",
    "EncryptedText",
    "MaskedSecret",
    "SecretBlob",
    "SecretDecryptError",
    "SecretLockedError",
    "SecretScope",
    "SecretShreddedError",
    "UserSecret",
    "apply_secret_update",
    "shred_user_key",
    "unlock_user_secrets",
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

_USER_SCOPE_WRONG_MECHANISM = (
    "scope='user' is not available on this column type, and cannot be: "
    "process_bind_param / process_result_value never see the row, so "
    "there is nowhere to read the owner from. Declare the column as "
    "SecretBlob() and put a UserSecret(...) descriptor beside it — see "
    "docs/adr/0004-user-scope-secrets.md and issue #227. scope='site' "
    "stays here, unchanged."
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
        raise NotImplementedError(_USER_SCOPE_WRONG_MECHANISM)
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


def _aad(header: bytes, owner_user_id: int | None) -> bytes:
    """Associated data for the AEAD.

    Site-scope blobs authenticate the header alone. User-scope blobs
    additionally bind the owner, so a ciphertext moved to another
    user's row fails the tag rather than decrypting — the cross-row
    portability that ADR 0003 had to list as an accepted limitation for
    ``site``. Stringified rather than packed so a hex dump stays
    readable; AAD is authenticated, not encrypted, so the bytes are
    free.
    """
    if owner_user_id is None:
        return header
    return header + b"|owner=" + str(owner_user_id).encode("ascii")


def _encrypt(
    plaintext: bytes,
    *,
    purpose: str,
    key_version: str,
    scope: str,
    key: bytes | None = None,
    owner_user_id: int | None = None,
) -> bytes:
    info = f"{scope}.{purpose}.{key_version}".encode("ascii")
    header = _header(scope)
    nonce = os.urandom(NONCE_BYTES)
    material = key if key is not None else _derive_key(_master_key_hex(), info)
    ct = AESGCM(material).encrypt(
        nonce, plaintext, associated_data=_aad(header, owner_user_id)
    )
    return header + nonce + ct


def _decrypt(
    blob: bytes,
    *,
    purpose: str,
    key_version: str,
    scope: str,
    key: bytes | None = None,
    owner_user_id: int | None = None,
) -> bytes:
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
    material = key if key is not None else _derive_key(_master_key_hex(), info)
    try:
        return AESGCM(material).decrypt(
            nonce, ct, associated_data=_aad(header, owner_user_id)
        )
    except InvalidTag as exc:
        owned = "" if owner_user_id is None else f" for owner {owner_user_id}"
        raise SecretDecryptError(
            f"{purpose}: decryption failed{owned}. Either "
            "SECRET_ENCRYPTION_KEY is not the key this row was written "
            "under, or the row was written for a different purpose / "
            "key_version / owner."
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


class SecretBlob(LargeBinary):
    """Raw ciphertext column for a :class:`UserSecret`.

    Not a ``TypeDecorator`` — it neither encrypts nor decrypts. It is a
    ``LargeBinary`` that widens to ``MEDIUMBLOB`` on MySQL, so the
    storage side of a user-scope secret matches
    :class:`EncryptedText` without pretending to be transparent about
    it. The :class:`UserSecret` descriptor beside it does the crypto,
    because it is the only one of the two that can see the row.

    The widening is the ``@compiles`` hook below, **not**
    ``load_dialect_impl``. Being a plain ``TypeEngine`` is exactly why:
    SQLAlchemy only calls ``load_dialect_impl`` on a ``TypeDecorator``,
    so the obvious symmetry with :class:`EncryptedText` is a trap here
    and cost this column its widening once already (#229).
    """


@compiles(SecretBlob, "mysql", "mariadb")
def _secret_blob_mediumblob(element, compiler, **kw) -> str:
    """Widen :class:`SecretBlob` to ``MEDIUMBLOB`` on MySQL/MariaDB.

    ``load_dialect_impl`` -- which :class:`EncryptedText` uses for the
    same widening -- is a ``TypeDecorator`` hook. ``SecretBlob`` is a
    plain ``LargeBinary``, so SQLAlchemy never calls it and the column
    compiled to ``BLOB``: the 64 KB ceiling the widening exists to
    avoid, on the one scope (user) most likely to hold something large
    like a service-account JSON key or a certificate bundle.

    ``@compiles`` is the ``TypeEngine`` equivalent and keeps
    ``SecretBlob`` a plain ``LargeBinary`` -- making it a
    ``TypeDecorator`` instead would work, but only by pretending to a
    transparency it deliberately does not have.

    Every other dialect keeps ``LargeBinary``'s default mapping.
    """
    return "MEDIUMBLOB"


class SecretLockedError(RuntimeError):
    """The user's key has not been unlocked in this session.

    Unwrapping is a database read, and every place it would be
    convenient to hide one — a type hook, a bare attribute access — is
    a sync call site in an async-only codebase, sometimes in the middle
    of consuming a result set. So the read is explicit and up front:
    ``await unlock_user_secrets(session, user_id)`` before touching the
    attribute.
    """


class SecretShreddedError(RuntimeError):
    """No key row for this user: they were deleted, or never had one.

    Distinct from :class:`SecretLockedError` because the remedies are
    opposite — one is "unlock first", the other is "the plaintext is
    gone and is not coming back".
    """


_KEY_CACHE_SLOT = "_atrium_user_secret_keys"
_WRAP_INFO = b"wrap.user_dek.v1"
_WRAP_PURPOSE = "__user_dek__"


def _session_info(session: Any) -> dict:
    """``session.info`` for either an AsyncSession or a Session.

    ``AsyncSession`` proxies to the sync session underneath, and the
    descriptor only ever gets at the sync one (via ``object_session``),
    so both call sites have to land on the same dict.
    """
    return getattr(session, "sync_session", session).info


def _key_cache(session: Any) -> dict[int, bytes]:
    return _session_info(session).setdefault(_KEY_CACHE_SLOT, {})


def _wrap_key() -> bytes:
    return _derive_key(_master_key_hex(), _WRAP_INFO)


def _column_key(dek: bytes, purpose: str, key_version: str) -> bytes:
    """Per-column key from the user's DEK.

    Same role ``purpose`` plays for site scope: a ciphertext lifted from
    one of a user's columns into another of their own columns still
    fails to decrypt.
    """
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=HKDF_SALT,
        info=f"user.{purpose}.{key_version}".encode("ascii"),
    ).derive(dek)


async def unlock_user_secrets(
    session: Any, user_id: int, *, create: bool = False
) -> None:
    """Load ``user_id``'s key into this session so their secrets can be read.

    Call it once, after you have the row that names the owner and
    before you touch any :class:`UserSecret` attribute. It needs no
    authenticated user — the owner is an integer you read off the row,
    which is what makes this usable from a device-authenticated request
    or a worker coroutine.

    ``create=True`` mints the key if the user has none yet; use it on
    the write path. On the read path leave it False so a shredded user
    raises :class:`SecretShreddedError` instead of silently getting a
    fresh key that decrypts nothing.

    The unwrapped key lives in ``session.info`` and dies with the
    session. There is no process-global key cache on purpose: a shred
    has to take effect immediately, and a long-lived cache would keep
    handing out a key whose wrap row is already gone.
    """
    from sqlalchemy import select

    from app.models.user_secret_key import UserSecretKey

    cache = _key_cache(session)
    if user_id in cache:
        return

    row = (
        await session.execute(
            select(UserSecretKey).where(UserSecretKey.user_id == user_id)
        )
    ).scalar_one_or_none()

    if row is None:
        if not create:
            raise SecretShreddedError(
                f"user {user_id} has no secret key: either they were "
                "deleted (their key was destroyed with them and their "
                "ciphertext is unrecoverable) or nothing has ever been "
                "encrypted for them. Pass create=True on a write path."
            )
        dek = os.urandom(KEY_BYTES)
        session.add(
            UserSecretKey(
                user_id=user_id,
                wrapped_key=_encrypt(
                    dek,
                    purpose=_WRAP_PURPOSE,
                    key_version="v1",
                    scope="user",
                    key=_wrap_key(),
                    owner_user_id=user_id,
                ),
            )
        )
        await session.flush()
    else:
        dek = _decrypt(
            row.wrapped_key,
            purpose=_WRAP_PURPOSE,
            key_version="v1",
            scope="user",
            key=_wrap_key(),
            owner_user_id=user_id,
        )

    cache[user_id] = dek


async def shred_user_key(session: Any, user_id: int) -> bool:
    """Destroy ``user_id``'s key. Returns True if there was one.

    Every ciphertext written for that user becomes permanently
    unreadable — including in backups taken before the call, which is
    the property that separates this from deleting the rows.

    Atrium calls this for you when a user is hard-deleted (the wrap row
    also carries ``ON DELETE CASCADE``, so the key cannot outlive the
    account either way). Hosts need it only to shred earlier than that.
    """
    from sqlalchemy import delete

    from app.models.user_secret_key import UserSecretKey

    _key_cache(session).pop(user_id, None)
    result = await session.execute(
        delete(UserSecretKey).where(UserSecretKey.user_id == user_id)
    )
    return bool(result.rowcount)


# Mapped class -> its UserSecret descriptors. Populated at class
# definition time so the flush hook knows which instances to look at
# without walking every attribute of every dirty object.
_USER_SECRETS: dict[type, list[UserSecret]] = {}


class UserSecret:
    """Row-aware per-user secret, stored in a sibling :class:`SecretBlob`.

    ::

        class Device(HostBase):
            __tablename__ = "device"
            user_id: Mapped[int] = mapped_column(HostForeignKey("users.id"))
            secret_ct: Mapped[bytes | None] = mapped_column(
                SecretBlob(), nullable=True
            )
            secret = UserSecret(
                purpose="device.secret",
                owner_attr="user_id",
                column="secret_ct",
            )

        await unlock_user_secrets(session, device.user_id)
        device.secret.reveal()

    Two declarations rather than one because the owner has to come from
    the row, and a ``TypeDecorator`` never sees the row — see
    ``docs/adr/0004-user-scope-secrets.md``. Reads return
    :class:`MaskedSecret`, same as site scope. Writes are held in memory
    and encrypted at flush, so assigning the secret before the owner id
    (constructor keyword order, for instance) is not an error.
    """

    def __init__(
        self,
        *,
        purpose: str,
        owner_attr: str,
        column: str,
        key_version: str = "v1",
        json: bool = False,
    ) -> None:
        if not purpose:
            raise ValueError("purpose is required")
        self.purpose = purpose
        self.owner_attr = owner_attr
        self.column = column
        self.key_version = key_version
        self.json = json
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name
        _USER_SECRETS.setdefault(owner, []).append(self)

    # -- plumbing ---------------------------------------------------- #

    @property
    def _pending_slot(self) -> str:
        return f"_atrium_pending_{self.name}"

    def _owner_of(self, instance: Any) -> int:
        owner = getattr(instance, self.owner_attr, None)
        if owner is None:
            raise SecretLockedError(
                f"{self.purpose}: {type(instance).__name__}."
                f"{self.owner_attr} is not set, so there is no owner to "
                "encrypt for. Set the owner before flushing."
            )
        return int(owner)

    def _key_for(self, session: Any, owner_user_id: int) -> bytes:
        if session is None:
            raise SecretLockedError(
                f"{self.purpose}: the instance is not attached to a "
                "session, so its owner's key cannot be resolved."
            )
        dek = _key_cache(session).get(owner_user_id)
        if dek is None:
            raise SecretLockedError(
                f"{self.purpose}: no key loaded for user {owner_user_id}. "
                f"Call `await unlock_user_secrets(session, {owner_user_id})` "
                "before reading or writing this attribute — unwrapping is a "
                "database read and cannot happen inside attribute access."
            )
        return _column_key(dek, self.purpose, self.key_version)

    def _encode(self, value: Any) -> bytes:
        if self.json:
            return json.dumps(
                value, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        if not isinstance(value, str):
            raise TypeError(
                f"{self.purpose}: expected str or MaskedSecret, got "
                f"{type(value).__name__}"
            )
        return value.encode("utf-8")

    def _decode(self, raw: bytes) -> Any:
        text = raw.decode("utf-8")
        return json.loads(text) if self.json else text

    # -- descriptor protocol ----------------------------------------- #

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        if self._pending_slot in instance.__dict__:
            pending = instance.__dict__[self._pending_slot]
            return None if pending is None else MaskedSecret(pending)

        blob = getattr(instance, self.column, None)
        if blob is None:
            return None

        from sqlalchemy.orm import object_session

        owner_user_id = self._owner_of(instance)
        key = self._key_for(object_session(instance), owner_user_id)
        raw = _decrypt(
            blob,
            purpose=self.purpose,
            key_version=self.key_version,
            scope="user",
            key=key,
            owner_user_id=owner_user_id,
        )
        return MaskedSecret(self._decode(raw))

    def __set__(self, instance: Any, value: Any) -> None:
        if isinstance(value, MaskedSecret):
            value = value.reveal()
        if value is None:
            instance.__dict__[self._pending_slot] = None
            setattr(instance, self.column, None)
            return
        # Held as plaintext until flush: the owner id may not be set
        # yet (``Device(secret=…, user_id=…)`` binds keywords in the
        # order written), and the key may not be unlocked yet either.
        instance.__dict__[self._pending_slot] = value

    # -- flush ------------------------------------------------------- #

    def _flush(self, session: Any, instance: Any) -> None:
        if self._pending_slot not in instance.__dict__:
            return
        pending = instance.__dict__.pop(self._pending_slot)
        if pending is None:
            setattr(instance, self.column, None)
            return
        owner_user_id = self._owner_of(instance)
        key = self._key_for(session, owner_user_id)
        setattr(
            instance,
            self.column,
            _encrypt(
                self._encode(pending),
                purpose=self.purpose,
                key_version=self.key_version,
                scope="user",
                key=key,
                owner_user_id=owner_user_id,
            ),
        )


@event.listens_for(Session, "before_flush")
def _encrypt_pending_user_secrets(session, flush_context, instances) -> None:
    """Encrypt every pending :class:`UserSecret` value about to be written.

    Runs on the sync ``Session`` because that is what SQLAlchemy fires,
    including underneath an ``AsyncSession``. Pure CPU — the key is
    already in ``session.info`` by this point, put there by
    ``unlock_user_secrets``; no IO happens here.
    """
    if not _USER_SECRETS:
        return
    for instance in list(session.new) + list(session.dirty):
        for descriptor in _USER_SECRETS.get(type(instance), ()):
            descriptor._flush(session, instance)


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
