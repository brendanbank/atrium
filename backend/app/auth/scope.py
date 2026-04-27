# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Scope abstraction.

Atrium ships a no-op admin scope. Host apps that need row-level
filtering (e.g. an agent who only sees their own bookings) define a
custom scope class + a ``get_scope`` dependency that returns it.
"""
from dataclasses import dataclass

from fastapi import Depends

from app.auth.users import current_user
from app.models.auth import User


@dataclass(frozen=True)
class AdminScope:
    """Default scope: full access. Atrium ships nothing else."""
    user: User


Scope = AdminScope


async def get_scope(user: User = Depends(current_user)) -> Scope:
    return AdminScope(user=user)
