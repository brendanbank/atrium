# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Pydantic schemas for users.

Same shape as fastapi-users' ``schemas.BaseUser*`` minus ``is_superuser``
(role/authority flow through RBAC). Inheriting from
``CreateUpdateDictModel`` keeps the ``create_update_dict[_superuser]``
helpers that ``UserManager.create`` relies on.
"""
from datetime import datetime

from fastapi_users.schemas import CreateUpdateDictModel
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import Language


class UserRead(CreateUpdateDictModel):
    id: int
    # Plain ``str`` rather than ``EmailStr``: the value is already
    # validated on the way in (UserCreate / UserUpdate / register),
    # and soft-deleted users carry a synthetic placeholder
    # (``deleted+{id}@deleted.invalid``) that the email-validator
    # library rejects because RFC 6761 reserves the .invalid TLD.
    # We're echoing whatever the DB holds, not re-checking it.
    email: str
    is_active: bool = True
    is_verified: bool = False

    full_name: str
    phone: str | None = None
    preferred_language: Language

    model_config = ConfigDict(from_attributes=True)


class UserCreate(CreateUpdateDictModel):
    email: EmailStr
    password: str
    is_active: bool | None = True
    is_verified: bool | None = False

    full_name: str
    phone: str | None = None
    preferred_language: Language = Language.EN


class UserUpdate(CreateUpdateDictModel):
    password: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    is_verified: bool | None = None

    full_name: str | None = None
    phone: str | None = None
    preferred_language: Language | None = None


class InviteCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    # RBAC role codes to grant on accept. At least one required.
    role_codes: list[str] = Field(min_length=1)
    expires_in_hours: int = Field(default=168, ge=1, le=720)


class InviteRead(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role_codes: list[str]
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class InviteCreated(InviteRead):
    """Returned only from POST /invites — includes the acceptance token
    so the admin UI can surface it for copy/send. The list endpoint
    never returns this shape, preventing token enumeration."""
    token: str


class InviteAccept(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
