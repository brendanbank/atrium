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


class I18nConfig(BaseModel):
    """Locale enablement + per-locale string overrides.

    ``enabled_locales`` controls which language switcher entries the
    header renders; codes correspond to the JSON files shipped under
    ``frontend/src/i18n/locales``. ``overrides`` lets an admin patch
    individual i18n keys per locale at runtime — outer key is the
    locale code, inner key is the dotted i18n key (e.g.
    ``"login.submit"``), inner value is the replacement string. The
    frontend merges ``overrides[locale]`` on top of the bundled
    resources at boot.
    """

    enabled_locales: list[str] = Field(default_factory=lambda: ["en", "nl"])
    overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class SystemConfig(BaseModel):
    """Operational toggles. Public so the frontend can render the
    maintenance page or announcement banner without an extra round-trip
    or a polling loop after a flag flip."""

    maintenance_mode: bool = False
    maintenance_message: str = Field(
        default=(
            "Atrium is undergoing maintenance. Please check back in a few "
            "minutes."
        ),
        max_length=500,
    )
    # Plain text. HTML / markdown would invite an XSS surface unless we
    # ran the value through the existing bleach sanitiser, and the
    # textarea is expected to hold one or two short sentences.
    announcement: str | None = Field(default=None, max_length=2000)
    announcement_level: Literal["info", "warning", "critical"] = "info"


class AuthConfig(BaseModel):
    """Auth-policy toggles. Phase 7 ships only the self-deletion knobs;
    later phases extend this same model (signup, password policy,
    captcha, 2FA enforcement)."""

    allow_self_delete: bool = True
    delete_grace_days: int = Field(default=30, ge=0, le=365)
    # Self-serve signup (Phase 2). Off by default — atrium stays
    # invite-only until an operator opts in. ``signup_default_role_code``
    # is the RBAC role assigned to fresh signups; ``user`` is the
    # zero-permission default. ``require_email_verification`` blocks
    # login until the verification link is consumed.
    allow_signup: bool = False
    signup_default_role_code: str = Field(default="user", max_length=64)
    require_email_verification: bool = True
    # Phase 3 password policy. The minimum is configurable but bounded
    # — six is the absolute floor (anything below is a typing accident),
    # 128 matches the bcrypt input ceiling. Mixed-case / digit / symbol
    # are off by default so atrium stays usable for low-stakes deploys;
    # operators opt-in. ``password_check_breach`` calls HIBP's range API;
    # network failures fail open (see services.password_policy).
    password_min_length: int = Field(default=8, ge=6, le=128)
    password_require_mixed_case: bool = False
    password_require_digit: bool = False
    password_require_symbol: bool = False
    password_check_breach: bool = False
    # Role codes that require a confirmed second factor. A user holding
    # any of these roles without an enrolled 2FA method gets bounced to
    # /2fa with ``code: 2fa_enrollment_required`` until they finish
    # setup. Empty list = no enforcement (default).
    require_2fa_for_roles: list[str] = Field(default_factory=list)
    # Phase 4: pluggable CAPTCHA on the unauthenticated auth endpoints
    # (register / login / forgot-password). The site key is public —
    # rendered into the widget on the login page — but the secret
    # belongs in the env var ``CAPTCHA_SECRET`` so it never lands in the
    # KV row. ``none`` disables the gate entirely.
    captcha_provider: Literal["none", "turnstile", "hcaptcha"] = "none"
    captcha_site_key: str | None = Field(default=None, max_length=200)


class _Namespace(BaseModel):
    key: str
    model: type[BaseModel]
    public: bool


NAMESPACES: dict[str, _Namespace] = {
    "brand": _Namespace(key="brand", model=BrandConfig, public=True),
    "i18n": _Namespace(key="i18n", model=I18nConfig, public=True),
    "system": _Namespace(key="system", model=SystemConfig, public=True),
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
    # Carve-out: the ``auth`` namespace is admin-only (it carries
    # password-policy and similar values that shouldn't leak), but the
    # LoginPage needs ``allow_signup`` to gate the "Sign up" link. Pull
    # only that one boolean into the public bundle under an ``auth``
    # key — never expose the full AuthConfig publicly.
    auth_cfg = await get_namespace(session, "auth")
    out["auth"] = {
        "allow_signup": getattr(auth_cfg, "allow_signup", False),
        # Captcha provider + site key are inherently public — the widget
        # renders them in the page source. The secret lives in env, not
        # in this bundle.
        "captcha_provider": getattr(auth_cfg, "captcha_provider", "none"),
        "captcha_site_key": getattr(auth_cfg, "captcha_site_key", None),
    }
    return out


async def get_all_admin_config(session: AsyncSession) -> dict[str, dict]:
    """Every namespace, including admin-only ones, for the admin UI."""
    out: dict[str, dict] = {}
    for ns in NAMESPACES.values():
        model = await get_namespace(session, ns.key)
        out[ns.key] = model.model_dump(mode="json")
    return out


register_namespace("auth", AuthConfig, public=False)
