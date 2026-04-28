# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit tests for ``emit_host_foreign_keys``.

Exercises the ``process_revision_directives`` callback against
hand-built ``MigrationScript`` ops — no real DB, no real
autogenerate. The integration test runs the full chain against
MySQL.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic.operations import ops

from app.host_sdk.alembic import emit_host_foreign_keys
from app.host_sdk.db import INFO_KEY, HostForeignKey


def _make_script(upgrade_ops: list[ops.MigrateOperation]) -> ops.MigrationScript:
    return ops.MigrationScript(
        rev_id="rev",
        upgrade_ops=ops.UpgradeOps(ops=upgrade_ops),
        downgrade_ops=ops.DowngradeOps(ops=[]),
    )


def _marked_column(col_name: str, target: str, **kw) -> sa.Column:
    col = sa.Column(col_name, sa.Integer(), nullable=False)
    col.info[INFO_KEY] = (HostForeignKey(target, **kw).spec,)
    return col


def test_create_table_op_grows_foreign_key_constraint():
    cto = ops.CreateTableOp(
        "hello_messages",
        [
            sa.Column("id", sa.Integer(), primary_key=True),
            _marked_column("created_by_user_id", "users.id", ondelete="RESTRICT"),
        ],
    )
    emit_host_foreign_keys(None, None, [_make_script([cto])])

    fks = [c for c in cto.columns if isinstance(c, sa.ForeignKeyConstraint)]
    assert len(fks) == 1
    fk = fks[0]
    assert fk.elements[0].target_fullname == "users.id"
    assert fk.ondelete == "RESTRICT"
    assert list(fk.column_keys) == ["created_by_user_id"]


def test_create_table_op_without_marker_is_untouched():
    cto = ops.CreateTableOp(
        "plain_host_table",
        [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(50)),
        ],
    )
    before = list(cto.columns)
    emit_host_foreign_keys(None, None, [_make_script([cto])])
    assert cto.columns == before  # no FK injected — nothing to do


def test_add_column_op_emits_sibling_create_foreign_key():
    new_col = sa.Column("agent_user_id", sa.Integer(), nullable=True)
    new_col.info[INFO_KEY] = (
        HostForeignKey("users.id", ondelete="SET NULL").spec,
    )
    addop = ops.AddColumnOp("bookings", new_col)
    script = _make_script([addop])
    emit_host_foreign_keys(None, None, [script])

    upgrade = script.upgrade_ops.ops
    assert len(upgrade) == 2
    assert isinstance(upgrade[0], ops.AddColumnOp)
    cfk = upgrade[1]
    assert isinstance(cfk, ops.CreateForeignKeyOp)
    assert cfk.source_table == "bookings"
    assert cfk.referent_table == "users"
    assert cfk.local_cols == ["agent_user_id"]
    assert cfk.remote_cols == ["id"]
    assert cfk.kw.get("ondelete") == "SET NULL"


def test_add_column_op_inside_modify_table_ops_is_walked():
    """Real autogenerate wraps AddColumnOp in ModifyTableOps when a
    table grows multiple changes at once. The walker must recurse."""
    new_col = sa.Column("agent_user_id", sa.Integer(), nullable=True)
    new_col.info[INFO_KEY] = (HostForeignKey("users.id").spec,)
    addop = ops.AddColumnOp("bookings", new_col)
    modify = ops.ModifyTableOps("bookings", [addop])
    emit_host_foreign_keys(None, None, [_make_script([modify])])

    assert len(modify.ops) == 2
    assert isinstance(modify.ops[0], ops.AddColumnOp)
    assert isinstance(modify.ops[1], ops.CreateForeignKeyOp)


def test_malformed_target_skips_quietly():
    """A typo in the target string shouldn't crash the migration
    generation — log a warning and skip the FK so autogenerate
    completes and the operator sees the warning in the alembic
    output. The skip is the load-bearing behaviour; the warning
    plumbing is verified by ``test_malformed_target_logs_warning``.
    """
    cto = ops.CreateTableOp(
        "broken",
        [
            sa.Column("id", sa.Integer(), primary_key=True),
            _marked_column("bad", "no_dot_here"),
        ],
    )
    emit_host_foreign_keys(None, None, [_make_script([cto])])
    fks = [c for c in cto.columns if isinstance(c, sa.ForeignKeyConstraint)]
    assert fks == []


def test_malformed_target_logs_warning(monkeypatch):
    """The warning is observable via the module logger, even if
    pytest's caplog plumbing is shadowed by a sibling fixture."""
    seen: list[str] = []
    from app.host_sdk import alembic as host_alembic

    monkeypatch.setattr(
        host_alembic.log,
        "warning",
        lambda msg, *args, **kwargs: seen.append(msg % args if args else msg),
    )
    cto = ops.CreateTableOp(
        "broken",
        [
            sa.Column("id", sa.Integer(), primary_key=True),
            _marked_column("bad", "no_dot_here"),
        ],
    )
    emit_host_foreign_keys(None, None, [_make_script([cto])])
    assert seen
    assert "malformed target" in seen[0]


def test_optional_constraint_name_passes_through():
    cto = ops.CreateTableOp(
        "named",
        [
            sa.Column("id", sa.Integer(), primary_key=True),
            _marked_column(
                "user_id", "users.id", name="fk_named_user_id", ondelete="CASCADE"
            ),
        ],
    )
    emit_host_foreign_keys(None, None, [_make_script([cto])])
    fk = next(c for c in cto.columns if isinstance(c, sa.ForeignKeyConstraint))
    assert fk.name == "fk_named_user_id"
    assert fk.ondelete == "CASCADE"
