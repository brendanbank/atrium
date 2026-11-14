# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""fastapi-users database adapter, owned by atrium.

This replaces ``fastapi_users_db_sqlalchemy.SQLAlchemyUserDatabase``.
That package (7.0.0, unreleased since Jan 2025) pins
``sqlalchemy<2.1`` and was the only thing holding atrium on
SQLAlchemy 2.0. Atrium used exactly one class from it, and none of
its OAuth or access-token tables, so we carry the user CRUD here and
depend on plain ``fastapi-users``.

Behaviour matches the upstream adapter on purpose: email lookup is
case-insensitive, and ``create`` / ``update`` / ``delete`` commit
their own transaction (fastapi-users' ``BaseUserManager`` relies on
that). OAuth methods are left to ``BaseUserDatabase``, which raises
``NotImplementedError`` -- atrium has no OAuth login.
"""

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends
from fastapi_users.db import BaseUserDatabase
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.auth import User


class SQLAlchemyUserDatabase(BaseUserDatabase[User, int]):
    """fastapi-users user store backed by atrium's ``users`` table."""

    def __init__(self, session: AsyncSession, user_table: type[User] = User):
        self.session = session
        self.user_table = user_table

    async def get(self, id: int) -> User | None:
        return await self._one(select(self.user_table).where(self.user_table.id == id))

    async def get_by_email(self, email: str) -> User | None:
        return await self._one(
            select(self.user_table).where(
                func.lower(self.user_table.email) == func.lower(email)
            )
        )

    async def create(self, create_dict: dict[str, Any]) -> User:
        user = self.user_table(**create_dict)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update(self, user: User, update_dict: dict[str, Any]) -> User:
        for key, value in update_dict.items():
            setattr(user, key, value)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        await self.session.delete(user)
        await self.session.commit()

    async def _one(self, statement: Select[User]) -> User | None:
        result = await self.session.execute(statement)
        return result.unique().scalar_one_or_none()


async def get_user_db(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)
