# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Build stamps for the running image — atrium's and the host app's.

Answers "which atrium is this deployment actually running, and which
build of *my* app is on top of it?" without exec-ing into a container.

The values are baked at **image build time** as environment variables,
not derived at runtime: the runtime image has no ``.git`` and no git
binary, and the source-declared ``pyproject.toml`` version only tells
you which release line the code came from, never which commit.

| Env var              | Set by                          | Example        |
| -------------------- | ------------------------------- | -------------- |
| ``ATRIUM_VERSION``   | atrium's Dockerfile build arg   | ``v0.29.1``    |
| ``ATRIUM_COMMIT``    | atrium's Dockerfile build arg   | ``912b5da…``   |
| ``ATRIUM_APP_NAME``  | host Dockerfile build arg       | ``Hello World``|
| ``ATRIUM_APP_VERSION``| host Dockerfile build arg      | ``1.4.0``      |
| ``ATRIUM_APP_COMMIT``| host Dockerfile build arg       | ``deadbee…``   |

``ATRIUM_*`` survives ``FROM ghcr.io/…/atrium:X`` because Docker
inherits ``ENV`` from the base image, which is exactly what makes the
two-layer answer possible: the host image only stamps its own three
vars and the atrium pair rides along from the base.

Both halves are "tag if there is one, otherwise the commit" — a build
from an untagged commit leaves ``version`` empty and only ``commit``
set. The UI renders ``Atrium v0.29.1`` for the first and
``atrium-pa: 22d2801`` for the second, so the two are never confused
for each other at a glance.

The ``ATRIUM_APP_*`` prefix (rather than a bare ``APP_VERSION``) keeps
these out of atrium's own ``APP_*`` settings namespace
(``APP_SECRET_KEY``, ``APP_BASE_URL``, ``APP_ROLE``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# The unstamped fallback deliberately reuses app_config's resolver
# rather than re-implementing it: it is the same string the public
# ``/app-config`` bundle reports, and having two answers to "what
# version is this" drift apart is the exact confusion this module
# exists to end.
from app.services.app_config import _atrium_version

# Deliberately not cached. These are process-lifetime constants in
# practice, but reading os.environ on request is a few microseconds and
# keeps the functions trivially monkeypatchable in tests.


@dataclass(frozen=True)
class Component:
    """One layer of the deployment: atrium itself, or the host app.

    ``name`` is ``None`` for a host image that stamped a version but
    no name — the SPA then labels the line with the (admin-editable)
    brand name rather than inventing one here.
    """

    name: str | None
    version: str | None
    commit: str | None


def _clean(value: str | None) -> str | None:
    """Empty / whitespace-only env vars read as "not stamped"."""
    return (value or "").strip() or None


# Tags are reported verbatim — ``v0.29.1`` stays ``v0.29.1``. The
# stamp is meant to be pasted straight into ``git checkout`` /
# ``docker pull``, and normalising it would break that for the sake of
# cosmetics.


def atrium_build() -> Component:
    """Atrium's own build stamp.

    Falls back to the source-declared version (``pyproject.toml`` /
    dist metadata, same resolver that feeds
    ``window.__ATRIUM_VERSION__``) when the image wasn't stamped —
    a dev tree, or an image built without the build args.
    """
    version = _clean(os.environ.get("ATRIUM_VERSION"))
    if version is None:
        declared = _atrium_version()
        version = None if declared == "unknown" else declared
    return Component(
        name="Atrium",
        version=version,
        commit=_clean(os.environ.get("ATRIUM_COMMIT")),
    )


def app_build() -> Component | None:
    """The host app's build stamp, or ``None`` on a bare atrium.

    Atrium ships no domain layer, so an unstamped image genuinely has
    no second version to report — the UI then shows the atrium line
    only, rather than an "unknown" placeholder.
    """
    name = _clean(os.environ.get("ATRIUM_APP_NAME"))
    version = _clean(os.environ.get("ATRIUM_APP_VERSION"))
    commit = _clean(os.environ.get("ATRIUM_APP_COMMIT"))
    if name is None and version is None and commit is None:
        return None
    return Component(name=name, version=version, commit=commit)
