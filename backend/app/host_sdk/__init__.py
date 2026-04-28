# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Python host SDK.

A small, typed surface that host bundles import to plug into atrium
without re-implementing the same boilerplate every time. Imports are
explicit per submodule (``app.host_sdk.db``, ``app.host_sdk.alembic``)
so the namespace stays tree-shakeable and submodules don't cause each
other to load alembic / SQLAlchemy bits a host doesn't actually need.

See ``docs/adr/0001-python-host-sdk.md`` for why this lives at
``app.host_sdk`` rather than under ``app.services`` or as a separate
package.
"""
from __future__ import annotations
