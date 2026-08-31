# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Acceptance gates for the secret-at-rest primitive (issue #225).

The DB round-trip is exercised through the TypeDecorator's own hooks
rather than a live table: ``process_bind_param`` / ``process_result_value``
are the whole contract, and everything below the dialect is
``LargeBinary``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import LargeBinary
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.dialects.mysql import MEDIUMBLOB

from app.host_sdk.crypto import (
    HEADER_BYTES,
    MAGIC,
    EncryptedJSON,
    EncryptedText,
    MaskedSecret,
    SecretBlob,
    SecretDecryptError,
    _derive_key,
    apply_secret_update,
)
from app.services.audit import _json_safe
from app.settings import Settings, get_settings

KEY_A = "11" * 32
KEY_B = "22" * 32


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", KEY_A)
    get_settings.cache_clear()
    _derive_key.cache_clear()
    yield
    get_settings.cache_clear()
    _derive_key.cache_clear()


def _roundtrip(col: EncryptedText, value):
    return col.process_result_value(col.process_bind_param(value, None), None)


# --------------------------------------------------------------------------- #
# Round trip + wire format                                                     #
# --------------------------------------------------------------------------- #


def test_roundtrip_returns_masked_secret():
    col = EncryptedText(purpose="cred.api_key")
    got = _roundtrip(col, "sk-live-abc123")
    assert isinstance(got, MaskedSecret)
    assert got.reveal() == "sk-live-abc123"


def test_none_passes_through():
    col = EncryptedText(purpose="cred.api_key")
    assert col.process_bind_param(None, None) is None
    assert col.process_result_value(None, None) is None


def test_same_plaintext_encrypts_differently():
    """A fresh nonce per write — otherwise equal ciphertexts leak that
    two rows hold the same secret."""
    col = EncryptedText(purpose="cred.api_key")
    first = col.process_bind_param("same", None)
    second = col.process_bind_param("same", None)
    assert first != second
    assert col.process_result_value(first, None) == "same"
    assert col.process_result_value(second, None) == "same"


def test_blob_is_self_describing():
    blob = EncryptedText(purpose="cred.api_key").process_bind_param("x", None)
    assert blob.startswith(MAGIC)
    assert blob[len(MAGIC)] == 1  # wire version
    assert blob[len(MAGIC) + 1] == 1  # scope byte: site


def test_header_is_authenticated():
    """Editing the header fails the AEAD tag rather than selecting a
    different key path — the point of feeding it in as associated data."""
    col = EncryptedText(purpose="cred.api_key")
    blob = bytearray(col.process_bind_param("x", None))
    blob[len(MAGIC) + 1] = 2  # rewrite scope byte to 'user'
    with pytest.raises(SecretDecryptError):
        col.process_result_value(bytes(blob), None)


def test_truncated_blob_is_rejected():
    col = EncryptedText(purpose="cred.api_key")
    blob = col.process_bind_param("x", None)
    with pytest.raises(SecretDecryptError, match="too short"):
        col.process_result_value(blob[: HEADER_BYTES + 4], None)


def test_foreign_bytes_are_rejected():
    with pytest.raises(SecretDecryptError, match="not an atrium secret blob"):
        EncryptedText(purpose="cred.api_key").process_result_value(b"plain", None)


def test_masked_secret_round_trips_on_write():
    """A loaded row can be re-saved without unwrapping the secret."""
    col = EncryptedText(purpose="cred.api_key")
    loaded = _roundtrip(col, "hunter2")
    assert _roundtrip(col, loaded).reveal() == "hunter2"


def test_non_string_write_is_refused():
    with pytest.raises(TypeError, match="expected str or MaskedSecret"):
        EncryptedText(purpose="cred.api_key").process_bind_param(42, None)


# --------------------------------------------------------------------------- #
# Key / purpose separation                                                     #
# --------------------------------------------------------------------------- #


def test_ciphertext_does_not_move_between_columns():
    """`purpose` is what stops a blob being lifted from one column into
    another and still decrypting."""
    blob = EncryptedText(purpose="cred.api_key").process_bind_param("s", None)
    with pytest.raises(SecretDecryptError, match="decryption failed"):
        EncryptedText(purpose="cred.password").process_result_value(blob, None)


def test_key_version_separates_keys():
    blob = EncryptedText(purpose="cred.api_key").process_bind_param("s", None)
    with pytest.raises(SecretDecryptError):
        EncryptedText(purpose="cred.api_key", key_version="v2").process_result_value(
            blob, None
        )


def test_wrong_master_key_names_the_purpose(monkeypatch):
    """The bare failure is an InvalidTag from inside SQLAlchemy result
    processing, on an endpoint that may not look secret-related."""
    blob = EncryptedText(purpose="cred.api_key").process_bind_param("s", None)
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", KEY_B)
    get_settings.cache_clear()
    with pytest.raises(SecretDecryptError, match=r"cred\.api_key"):
        EncryptedText(purpose="cred.api_key").process_result_value(blob, None)


# --------------------------------------------------------------------------- #
# Scope                                                                        #
# --------------------------------------------------------------------------- #


def test_user_scope_on_this_type_redirects_to_the_row_aware_mechanism():
    """Replaces the 0.27.0 "not implemented yet" gate.

    The round trip that supersedes it lives in
    ``tests/integration/test_user_scope_secrets.py``; what stays here is
    the guard that this type never silently accepts a user secret. It
    cannot implement one — its hooks never see the row — so the error
    has to name the mechanism that can.
    """
    with pytest.raises(NotImplementedError) as exc:
        EncryptedText(purpose="cred.api_key", scope="user")
    message = str(exc.value)
    assert "UserSecret" in message
    assert "SecretBlob" in message
    assert "#227" in message


def test_a_site_blob_is_not_readable_as_a_user_blob():
    """The scope byte reserved in 0.27.0 doing its job in both
    directions, now that both scopes exist."""
    from app.host_sdk.crypto import _decrypt, _encrypt

    site = _encrypt(b"s", purpose="p", key_version="v1", scope="site")
    with pytest.raises(SecretDecryptError, match="scope"):
        _decrypt(
            site,
            purpose="p",
            key_version="v1",
            scope="user",
            key=b"\x00" * 32,
            owner_user_id=1,
        )

    user = _encrypt(
        b"s",
        purpose="p",
        key_version="v1",
        scope="user",
        key=b"\x00" * 32,
        owner_user_id=1,
    )
    with pytest.raises(SecretDecryptError, match="scope"):
        _decrypt(user, purpose="p", key_version="v1", scope="site")


def test_the_owner_is_authenticated_not_just_stored():
    """Same key, different owner in the AAD — the tag has to fail."""
    from app.host_sdk.crypto import _decrypt, _encrypt

    key = b"\x11" * 32
    blob = _encrypt(
        b"s", purpose="p", key_version="v1", scope="user", key=key, owner_user_id=1
    )
    with pytest.raises(SecretDecryptError, match="for owner 2"):
        _decrypt(
            blob, purpose="p", key_version="v1", scope="user", key=key, owner_user_id=2
        )


def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError, match="unknown scope"):
        EncryptedText(purpose="cred.api_key", scope="tenant")


def test_purpose_is_required():
    with pytest.raises(ValueError, match="purpose is required"):
        EncryptedText(purpose="")


# --------------------------------------------------------------------------- #
# MaskedSecret                                                                 #
# --------------------------------------------------------------------------- #


def test_masked_secret_is_not_a_str():
    """Subclassing str would satisfy every isinstance check in the
    codebase and leak into all of them."""
    assert not isinstance(MaskedSecret("s3cret"), str)


def test_masked_secret_does_not_render():
    secret = MaskedSecret("s3cret")
    assert str(secret) == "***"
    assert "s3cret" not in repr(secret)
    assert "s3cret" not in f"{secret}"


def test_masked_secret_compares_without_revealing():
    assert MaskedSecret("a") == "a"
    assert MaskedSecret("a") == MaskedSecret("a")
    assert MaskedSecret("a") != "b"


def test_masked_secret_is_unhashable():
    with pytest.raises(TypeError):
        {MaskedSecret("a")}


def test_hint_gives_the_tail_only():
    assert MaskedSecret("sk-live-9f3a").hint() == "9f3a"
    assert MaskedSecret("shrt").hint() == ""  # too short to hint safely
    assert MaskedSecret({"a": 1}).hint() == ""


def test_audit_diff_never_carries_cleartext():
    """The shortest path from a decrypted credential to a durable table
    with a retention policy."""
    diff = _json_safe({"api_key": MaskedSecret("sk-live-abc123"), "name": "prod"})
    assert diff == {"api_key": "***", "name": "prod"}


# --------------------------------------------------------------------------- #
# Dialect                                                                      #
# --------------------------------------------------------------------------- #


def test_mysql_widens_to_mediumblob():
    """LargeBinary maps to BLOB (64 KB) on MySQL — atrium-pa hit that
    ceiling in production."""
    impl = EncryptedText(purpose="cred.api_key").load_dialect_impl(mysql.dialect())
    assert isinstance(impl, MEDIUMBLOB)


def test_other_dialects_keep_large_binary():
    impl = EncryptedText(purpose="cred.api_key").load_dialect_impl(sqlite.dialect())
    assert isinstance(impl, LargeBinary)


# The two assertions above call ``load_dialect_impl`` directly, which
# proves the hook returns the right type but not that SQLAlchemy ever
# calls it. It does for ``EncryptedText`` (a ``TypeDecorator``) and did
# not for ``SecretBlob`` (a plain ``LargeBinary``) — issue #229, where
# the column shipped as ``BLOB`` while the hook, the docstring and a
# hook-style test all said ``MEDIUMBLOB``. Everything below goes
# through ``.compile()`` instead, which is what actually reaches the
# DDL.


def test_encrypted_text_compiles_to_mediumblob_on_mysql():
    assert "MEDIUMBLOB" in EncryptedText(purpose="cred.api_key").compile(
        dialect=mysql.dialect()
    )


def test_secret_blob_compiles_to_mediumblob_on_mysql():
    """#229: the storage side of a user-scope secret has to match
    EncryptedText, and user scope is where the large payloads live."""
    assert "MEDIUMBLOB" in SecretBlob().compile(dialect=mysql.dialect())


def test_secret_blob_keeps_the_default_mapping_on_other_dialects():
    assert "MEDIUMBLOB" not in SecretBlob().compile(dialect=sqlite.dialect())


def test_secret_blob_column_ddl_is_mediumblob():
    """The end of the chain: what CREATE TABLE actually emits."""
    from sqlalchemy import Column, MetaData, Table
    from sqlalchemy.schema import CreateTable

    table = Table("t", MetaData(), Column("ct", SecretBlob()))
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "MEDIUMBLOB" in ddl


# --------------------------------------------------------------------------- #
# EncryptedJSON                                                                #
# --------------------------------------------------------------------------- #


def test_json_roundtrip_is_masked():
    col = EncryptedJSON(purpose="cred.payload")
    payload = {"token": "abc", "scopes": ["a", "b"]}
    got = col.process_result_value(col.process_bind_param(payload, None), None)
    assert isinstance(got, MaskedSecret)
    assert got.reveal() == payload
    assert "abc" not in str(got)


# --------------------------------------------------------------------------- #
# Update convention                                                            #
# --------------------------------------------------------------------------- #


class _Row:
    api_key: object = "existing"


def test_blank_preserves_the_stored_secret():
    """Editing an unrelated field on the same form must not blank the
    credential — the failure would surface much later as an auth error."""
    row = _Row()
    assert apply_secret_update(row, "api_key", "") is False
    assert row.api_key == "existing"


def test_explicit_null_clears():
    """Without this, a secret can be set or kept but never unset."""
    row = _Row()
    assert apply_secret_update(row, "api_key", None) is True
    assert row.api_key is None


def test_a_value_sets():
    row = _Row()
    assert apply_secret_update(row, "api_key", "new") is True
    assert row.api_key == "new"


# --------------------------------------------------------------------------- #
# Settings                                                                     #
# --------------------------------------------------------------------------- #


def test_prod_refuses_the_dev_default_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("APP_SECRET_KEY", "not-a-default")
    monkeypatch.setenv("JWT_SECRET", "not-a-default")
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "00" * 32)
    with pytest.raises(ValueError, match="SECRET_ENCRYPTION_KEY is still the dev"):
        Settings()


def test_prod_accepts_a_real_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("APP_SECRET_KEY", "not-a-default")
    monkeypatch.setenv("JWT_SECRET", "not-a-default")
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", KEY_A)
    assert Settings().secret_encryption_key == KEY_A


@pytest.mark.parametrize("bad", ["nothex", "aa", "11" * 31])
def test_malformed_key_fails_at_startup_in_any_environment(monkeypatch, bad):
    """A typo here would otherwise boot fine and surface as a decrypt
    failure on the first credential read."""
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", bad)
    with pytest.raises(ValueError, match="SECRET_ENCRYPTION_KEY"):
        Settings()
