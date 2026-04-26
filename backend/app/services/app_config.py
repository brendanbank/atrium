"""Typed namespace-scoped reader/writer over the ``app_settings`` KV table.

Each namespace owns one row whose ``value`` JSON column matches a Pydantic
model. Defaults come from the model — there's no migration to seed rows;
they materialize on first PUT.

The split between *public* and *admin* namespaces is enforced here, not
at the route layer. A namespace marked ``public=True`` is exposed via
``GET /app-config`` (no auth) and used by the frontend at boot. Anything
policy- or security-adjacent (auth, audit retention) stays admin-only.

Phase 0 ships only ``brand``. Subsequent phases extend ``NAMESPACES``
with their own schemas (auth signup toggles, system maintenance mode,
audit retention, i18n overrides).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ops import AppSetting


class BrandConfig(BaseModel):
    """Branding tokens consumed by the frontend Mantine theme."""

    name: str = Field(default="Atrium", max_length=100)
    logo_url: str | None = Field(default="/logo.svg", max_length=500)
    support_email: str | None = Field(default=None, max_length=255)
    preset: Literal["default", "dark-glass", "classic"] = "default"
    # Curated subset of MantineThemeOverride. Keeping this narrow on
    # purpose — the admin UI ships color pickers + font selectors, not
    # a free-form JSON editor, so the validation surface stays
    # predictable.
    overrides: dict[str, str] = Field(default_factory=dict)


class _Namespace(BaseModel):
    key: str
    model: type[BaseModel]
    public: bool


NAMESPACES: dict[str, _Namespace] = {
    "brand": _Namespace(key="brand", model=BrandConfig, public=True),
}


def register_namespace(key: str, model: type[BaseModel], *, public: bool) -> None:
    """Register an additional namespace at import time.

    Subsequent phases (auth, system, audit, i18n) call this from their
    own modules so the routes pick them up automatically.
    """
    NAMESPACES[key] = _Namespace(key=key, model=model, public=public)


async def get_namespace(session: AsyncSession, key: str) -> BaseModel:
    if key not in NAMESPACES:
        raise KeyError(key)
    ns = NAMESPACES[key]
    row = (
        await session.execute(select(AppSetting.value).where(AppSetting.key == key))
    ).scalar_one_or_none()
    if row is None:
        return ns.model()
    # ``model_validate`` re-applies defaults for any field added since
    # the row was last written — so adding a new BrandConfig field
    # doesn't require a backfill migration.
    return ns.model.model_validate(row)


async def put_namespace(
    session: AsyncSession, key: str, payload: dict
) -> BaseModel:
    if key not in NAMESPACES:
        raise KeyError(key)
    ns = NAMESPACES[key]
    validated = ns.model.model_validate(payload)
    stmt = mysql_insert(AppSetting).values(
        key=key, value=validated.model_dump(mode="json")
    )
    stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
    await session.execute(stmt)
    await session.commit()
    return validated


async def get_public_config(session: AsyncSession) -> dict[str, dict]:
    """Bundle every public namespace into one response — the frontend
    hits this once at boot and feeds it to MantineProvider/i18n/etc."""
    out: dict[str, dict] = {}
    for ns in NAMESPACES.values():
        if not ns.public:
            continue
        model = await get_namespace(session, ns.key)
        out[ns.key] = model.model_dump(mode="json")
    return out


async def get_all_admin_config(session: AsyncSession) -> dict[str, dict]:
    """Every namespace, including admin-only ones, for the admin UI."""
    out: dict[str, dict] = {}
    for ns in NAMESPACES.values():
        model = await get_namespace(session, ns.key)
        out[ns.key] = model.model_dump(mode="json")
    return out
