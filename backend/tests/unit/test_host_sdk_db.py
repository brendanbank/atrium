# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests for ``app.host_sdk.db.HostForeignKey``.

These tests exercise the marker contract in isolation — no DB, no
alembic. The integration test in
``tests/integration/test_host_sdk_alembic.py`` validates the
autogenerate hook end-to-end against MySQL.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.host_sdk.db import INFO_KEY, HostFKSpec, HostForeignKey


class _HostBase(DeclarativeBase):
    pass


def test_marker_attaches_spec_to_column_info():
    class M(_HostBase):
        __tablename__ = "m_attaches_spec"
        id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
        user_id: Mapped[int] = mapped_column(
            sa.Integer,
            HostForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        )

    col = M.__table__.c.user_id
    specs = col.info[INFO_KEY]
    assert specs == (
        HostFKSpec(target="users.id", ondelete="RESTRICT"),
    )


def test_marker_does_not_register_mapper_foreign_key():
    """The whole point: the mapper sees a plain column, no cross-metadata FK."""

    class M(_HostBase):
        __tablename__ = "m_no_fk"
        id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
        user_id: Mapped[int] = mapped_column(
            sa.Integer,
            HostForeignKey("users.id"),
            nullable=False,
        )

    col = M.__table__.c.user_id
    assert col.foreign_keys == set()
    # SA's mapper-level configure must succeed without raising — if
    # we'd let a real ForeignKey through, an explicit
    # ``configure_mappers()`` would blow up here on the cross-metadata
    # reference.
    sa.orm.configure_mappers()


def test_multiple_markers_on_one_column_round_trip():
    """Two ``HostForeignKey`` calls on the same column accumulate.

    Realistically rare (a single column with two FKs is unusual) but
    the marker contract should be predictable: order preserved, no
    silent drop.
    """

    class M(_HostBase):
        __tablename__ = "m_multi"
        id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
        ref: Mapped[int] = mapped_column(
            sa.Integer,
            HostForeignKey("users.id", ondelete="RESTRICT"),
            HostForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        )

    specs = M.__table__.c.ref.info[INFO_KEY]
    assert len(specs) == 2
    assert specs[0].target == "users.id"
    assert specs[0].ondelete == "RESTRICT"
    assert specs[1].target == "roles.id"
    assert specs[1].ondelete == "CASCADE"


def test_optional_kwargs_default_to_none():
    spec = HostForeignKey("users.id").spec
    assert spec.target == "users.id"
    assert spec.ondelete is None
    assert spec.onupdate is None
    assert spec.name is None


def test_supports_explicit_constraint_name_and_onupdate():
    spec = HostForeignKey(
        "users.id",
        ondelete="SET NULL",
        onupdate="CASCADE",
        name="fk_bookings_user",
    ).spec
    assert spec.ondelete == "SET NULL"
    assert spec.onupdate == "CASCADE"
    assert spec.name == "fk_bookings_user"
