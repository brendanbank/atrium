# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Per-user data-encryption key, wrapped under the installation master.

The row *is* the shredding mechanism. A user's key is 32 random bytes
generated once, stored encrypted under ``SECRET_ENCRYPTION_KEY``, and
destroyed by the ``ON DELETE CASCADE`` when the ``users`` row goes.
After that the user's ciphertext is unreadable by anyone — including
an operator holding the master key and a backup taken before the
delete.

That last property is the entire point, and it is why the key is
**random and stored** rather than HKDF-derived from the master the way
``scope="site"`` keys are. A derived key is recomputable from the
master forever, so "delete the user's key" would be a no-op dressed up
as a security control — see ``docs/adr/0004-user-scope-secrets.md``
and the analysis on issue #227.

Nothing in atrium writes to this table on its own; it materialises the
first time a host calls ``unlock_user_secrets(..., create=True)`` for
a user.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserSecretKey(Base):
    __tablename__ = "user_secret_keys"

    # PK is the user id, not a surrogate: exactly one key per user, and
    # the uniqueness is the invariant rather than a constraint bolted
    # on beside it.
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    # ATR | version | scope | nonce | ct | tag over the 32-byte DEK,
    # under a key derived from the master for the wrap purpose. The
    # user id rides in the AEAD's associated data, so a wrap row moved
    # to another user fails the tag instead of handing out their key.
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
