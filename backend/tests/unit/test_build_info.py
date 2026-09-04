# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit-test the build-stamp resolver.

The API test covers the wire shape; this covers the parsing edges that
only show up with a weird stamp — empty build args (Docker turns an
unset ``ARG X=""`` into an empty string, not an absent variable), and
tag strings that do or don't carry the conventional leading ``v``.
"""
from __future__ import annotations

import pytest

from app.services import build_info

_VARS = (
    "ATRIUM_VERSION",
    "ATRIUM_COMMIT",
    "ATRIUM_APP_NAME",
    "ATRIUM_APP_VERSION",
    "ATRIUM_APP_COMMIT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)


def test_empty_build_args_read_as_unstamped(monkeypatch):
    """``ARG ATRIUM_APP_VERSION=""`` with no ``--build-arg`` bakes an
    empty string. That must read as "no host app", not as a host app
    with a blank version."""
    for var in _VARS:
        monkeypatch.setenv(var, "")
    assert build_info.app_build() is None
    # Atrium falls back to the source-declared version rather than
    # reporting an empty one.
    assert build_info.atrium_build().version


@pytest.mark.parametrize("tag", ["v1.2.3", "2026.1", "release-4", "valhalla"])
def test_tags_are_reported_verbatim(monkeypatch, tag):
    """No normalisation of any kind. The stamp is what a reader pastes
    into ``git checkout`` / ``docker pull``, so trimming a ``v`` for
    cosmetics would break the one job it has — and hosts are free to
    use any tagging scheme at all."""
    monkeypatch.setenv("ATRIUM_VERSION", tag)
    monkeypatch.setenv("ATRIUM_APP_VERSION", tag)
    assert build_info.atrium_build().version == tag
    assert build_info.app_build().version == tag


def test_whitespace_only_stamp_is_not_a_version(monkeypatch):
    monkeypatch.setenv("ATRIUM_APP_NAME", "  ")
    monkeypatch.setenv("ATRIUM_APP_VERSION", "\n")
    assert build_info.app_build() is None
