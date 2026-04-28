# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Unit-test the version resolver in isolation.

Issue #57 surfaced because the integration test only checked truthiness
— ``"unknown"`` is truthy. The published runtime image's venv has no
``atrium-backend`` dist-info, so ``importlib.metadata`` raised and the
resolver silently fell through to ``"unknown"``. Exercise the fallback
chain directly so the bug class can't regress unobserved again.
"""
from __future__ import annotations

import tomllib
from importlib import metadata as _metadata
from pathlib import Path

import pytest

from app.services import app_config


def _expected_version() -> str:
    pyproject = Path(app_config.__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_returns_pyproject_version_when_metadata_missing(monkeypatch):
    """Simulate the published runtime image: dist-info is absent, but
    pyproject.toml is on disk. The resolver must read the file rather
    than degrading to ``"unknown"``."""

    def _raise(_name):
        raise _metadata.PackageNotFoundError("atrium-backend")

    monkeypatch.setattr(app_config._metadata, "version", _raise)

    assert app_config._atrium_version() == _expected_version()


def test_returns_unknown_only_when_both_sources_fail(monkeypatch, tmp_path):
    """If even the pyproject.toml lookup fails (corrupt file, missing
    project table), the resolver must still produce a string — no
    exceptions leak into ``GET /app-config``."""

    def _raise(_name):
        raise _metadata.PackageNotFoundError("atrium-backend")

    monkeypatch.setattr(app_config._metadata, "version", _raise)

    # Point parents[2] at a directory whose pyproject.toml is broken.
    broken = tmp_path / "pyproject.toml"
    broken.write_text("not = valid = toml = at = all\n")

    fake_app_config = tmp_path / "app" / "services" / "app_config.py"
    fake_app_config.parent.mkdir(parents=True)
    fake_app_config.write_text("# stub\n")

    monkeypatch.setattr(app_config, "__file__", str(fake_app_config))

    assert app_config._atrium_version() == "unknown"


def test_metadata_path_returns_real_version_in_dev_tree():
    """In a dev tree where ``uv sync`` has installed atrium-backend as
    an editable distribution, ``importlib.metadata`` is the primary
    source. Either path is acceptable as long as the value matches
    pyproject."""
    expected = _expected_version()
    assert app_config._atrium_version() == expected


@pytest.mark.parametrize("bad", ["", None])
def test_pyproject_version_missing_falls_through_to_unknown(monkeypatch, tmp_path, bad):
    """Empty / non-string ``[project].version`` (defensive — shouldn't
    happen in practice) doesn't masquerade as a real version."""

    def _raise(_name):
        raise _metadata.PackageNotFoundError("atrium-backend")

    monkeypatch.setattr(app_config._metadata, "version", _raise)

    pyproject = tmp_path / "pyproject.toml"
    if bad is None:
        pyproject.write_text("[project]\nname = 'x'\n")
    else:
        pyproject.write_text(f"[project]\nname = 'x'\nversion = {bad!r}\n")

    fake_app_config = tmp_path / "app" / "services" / "app_config.py"
    fake_app_config.parent.mkdir(parents=True)
    fake_app_config.write_text("# stub\n")

    monkeypatch.setattr(app_config, "__file__", str(fake_app_config))

    assert app_config._atrium_version() == "unknown"
