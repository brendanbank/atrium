# Host integration patterns

A single-page index of "I want X in my host bundle - which API gives
me that?" Atrium ships only the platform shell; every host-shaped
extension goes through one of the registry hooks or backend
entrypoints below. The TSDoc on
[`@brendanbank/atrium-host-types`](../packages/host-types/src/index.ts)
is the per-symbol reference; this page is the discovery aid that
maps a host author's *need* onto the right symbol.

For the contract surface (image catalogue, tagging, env vars), see
[`published-images.md`](published-images.md). For the per-version
matrix of when each hook landed, see
[`compat-matrix.md`](compat-matrix.md). For a working repo that
exercises every hook below, see
[`../examples/hello-world/`](../examples/hello-world/) - in
particular [`frontend/src/main.tsx`](../examples/hello-world/frontend/src/main.tsx).

## Quick map

| I want to...                                        | Use this                                                                       |
| --------------------------------------------------- | ------------------------------------------------------------------------------ |
| Add a sidebar nav item                              | [`registerNavItem`](#sidebar-nav-item)                                         |
| Add a custom page (any URL)                         | [`registerRoute`](#custom-page)                                                |
| Add a card on the home page                         | [`registerHomeWidget`](#home-page-widget)                                      |
| Add an admin tab under `/admin/...`                 | [`registerAdminTab({ section: 'admin' })`](#admin-tab)                         |
| Add a settings page in a collapsible Settings group | [`registerAdminTab({ section: 'settings' })`](#settings-page)                  |
| Group several admin/settings pages under one parent | [`registerSettingsGroup`](#nested-collapsible-group)                           |
| Move atrium's built-in admin tabs                   | [`setBuiltinAdminTabSection`](#move-built-in-admin-tabs)                       |
| Add a card to the user profile page                 | [`registerProfileItem`](#profile-card)                                         |
| Render a custom notification kind                   | [`registerNotificationKind`](#notification-kind-renderer)                      |
| Subscribe to SSE events without a second connection | [`subscribeEvent`](#sse-subscriber)                                            |
| Override / extend i18n strings                      | [`registerLocale`](#locale-overlay)                                            |
| Add a host-specific JSON config namespace           | [`register_namespace`](#config-namespace)                                      |
| Run a recurring background job                      | [`HostWorkerCtx.register_job_handler`](#background-job)                        |
| Send an email from a host route, synchronously      | [`drain_outbox_row`](#synchronous-email)                                       |
| Add a logical FK from a host table to atrium        | [`HostForeignKey`](#cross-base-foreign-key)                                    |
| Stub atrium globals in host unit tests              | [`@brendanbank/atrium-test-utils`](#test-helpers)                              |

Every entry below is annotated with the atrium version that shipped
the API; older hosts can detect availability at runtime through
`window.__ATRIUM_VERSION__` (see *Runtime version detection* in
[`published-images.md`](published-images.md)).

---

## Frontend registry hooks

All seven `register*` functions plus `subscribeEvent` and
`setBuiltinAdminTabSection` are exposed two ways:

- as named exports of `@brendanbank/atrium-host-types` (typed,
  preferred when the host imports the SDK package), and
- on the `window.__ATRIUM_REGISTRY__` global, populated before the
  host bundle imports - so a bundle that wants zero atrium
  TypeScript dependencies can call
  `window.__ATRIUM_REGISTRY__.registerHomeWidget(...)` instead.

Calls must be made at **import time**, before React mounts. Atrium
loads the host bundle synchronously in `main.tsx` and only mounts
the SPA once import-time side-effects have run; a registration call
made after first paint will be ignored by every consumer that
already iterated its registry.

### Sidebar nav item
<a id="sidebar-nav-item"></a>

```ts
registerNavItem({
  key: 'leagues',
  label: 'Leagues',
  to: '/leagues',
  icon: <IconTrophy size={18} />,
  order: 250,
  condition: ({ me }) => me?.permissions.includes('league.read') ?? false,
});
```

Defined in [`frontend/src/host/registry.ts`](../frontend/src/host/registry.ts);
rendered by [`AppLayout.tsx`](../frontend/src/components/AppLayout.tsx).
Atrium's built-in nav uses `order: 100/200/300` (Home / Notifications /
Admin) so a host slot at `order: 250` lands between Notifications and
Admin. Available since atrium 0.9.

### Custom page
<a id="custom-page"></a>

```ts
registerRoute({
  key: 'leagues-page',
  path: '/leagues',
  render: () => <LeaguesPage />,
  requireAuth: true,
  layout: 'shell',
});
```

Defined in [`registry.ts`](../frontend/src/host/registry.ts); mounted
in React Router by [`App.tsx`](../frontend/src/App.tsx). Use `render: () => …`
(not `element:`) for new code - the captured-element form is
soft-deprecated since 0.12 because shared element references can
carry stale state across navigations. Available since atrium 0.9;
the `render` shape since 0.12.

### Home-page widget
<a id="home-page-widget"></a>

```ts
registerHomeWidget({
  key: 'next-match',
  width: 'wide',
  render: () => <NextMatchCard />,
});
```

Defined in [`registry.ts`](../frontend/src/host/registry.ts); rendered
by [`HostHomeWidgets.tsx`](../frontend/src/components/HostHomeWidgets.tsx).
`width` is one of `narrow` / `wide` / `full`. Registering at least one
widget auto-hides the built-in welcome blurb so the home page becomes
a host-shaped dashboard instead. Available since atrium 0.9; `width`
since 0.11.1.

### Admin tab
<a id="admin-tab"></a>

```ts
registerAdminTab({
  key: 'leagues',
  label: 'Leagues',
  section: 'admin',
  perm: 'league.manage',
  order: 750,
  render: () => <LeaguesAdmin />,
});
```

Defined in [`registry.ts`](../frontend/src/host/registry.ts); mounted
at `/admin/{key}` by [`AdminPage.tsx`](../frontend/src/routes/AdminPage.tsx)
+ [`sections.tsx`](../frontend/src/admin/sections.tsx). `perm` hides
the tab from users who don't hold the permission code; atrium's
built-in tabs use `order: 100..900` so hosts can interleave (e.g.
`order: 750` between Reminders and Audit). Available since atrium 0.9;
`section` since 0.17.

### Settings page
<a id="settings-page"></a>

```ts
registerAdminTab({
  key: 'league-prefs',
  label: 'League preferences',
  section: 'settings',          // <- the only difference from an admin tab
  render: () => <LeaguePrefsPage />,
});
```

Same call as an admin tab; the `section: 'settings'` flag puts it in
the parallel **Settings** sidebar group above Admin and routes it at
`/settings/{key}`. Atrium ships zero items in Settings, so the
parent collapses entirely until at least one host registers into it.
Available since atrium 0.17.

### Nested collapsible group
<a id="nested-collapsible-group"></a>

When a host has more than two related admin pages, group them under
a single collapsible parent so the sidebar doesn't sprawl:

```ts
registerRoute({ key: 'pa-redaction', path: '/admin/pa/redaction', render: () => <Redaction /> });
registerRoute({ key: 'pa-anomaly',   path: '/admin/pa/anomaly',   render: () => <Anomaly /> });

registerSettingsGroup({
  key: 'pa-tools',
  label: 'PA tools',
  section: 'admin',
  perm: 'pa.manage',           // hides the whole group + every child in one shot
  order: 800,
  children: [
    { key: 'redaction', label: 'Redaction', to: '/admin/pa/redaction' },
    { key: 'anomaly',   label: 'Anomaly',   to: '/admin/pa/anomaly'   },
  ],
});
```

Children are nav-only; their actual content comes from the routes
the host registered separately. A group with every child gated out
hides itself. Defined in [`registry.ts`](../frontend/src/host/registry.ts);
rendered by [`sections.tsx`](../frontend/src/admin/sections.tsx).
Available since atrium 0.25.

### Move built-in admin tabs
<a id="move-built-in-admin-tabs"></a>

```ts
setBuiltinAdminTabSection('branding', 'settings', 50);
setBuiltinAdminTabSection('translations', 'settings', 60);
```

Relocate atrium's built-in admin tabs (`branding`, `emails`,
`outbox`, `reminders`, `translations`, `system`, `auth`, `users`,
`roles`, `audit`) into the Settings group, or re-rank them within
their current group. Useful when a host's brand-tuning workflow
genuinely belongs alongside the host's own settings instead of
buried in `/admin`. Available since atrium 0.17.

### Profile card
<a id="profile-card"></a>

```ts
registerProfileItem({
  key: 'league-prefs',
  slot: 'after-roles',
  render: () => <LeaguePrefsCard />,
  condition: ({ me }) => me.permissions.includes('league.read'),
});
```

Defined in [`registry.ts`](../frontend/src/host/registry.ts); rendered
by [`ProfilePage.tsx`](../frontend/src/routes/ProfilePage.tsx). `slot`
is one of `after-profile` / `after-password` / `after-2fa` /
`after-roles` (default) / `after-sessions` / `before-delete`. The
host owns the card chrome - atrium does not auto-wrap in a `Paper`.
Available since atrium 0.11.

### Notification kind renderer
<a id="notification-kind-renderer"></a>

Atrium emits `Notification` rows with a `kind` string and an opaque
`payload`. Each kind a host cares about needs a renderer:

```ts
registerNotificationKind({
  kind: 'match.scheduled',
  title:  (n) => `Match against ${n.payload.opponent}`,
  href:   (n) => `/match/${n.payload.match_id}`,
  render: (n) => <MatchScheduledDetail n={n} />,
});
```

`title` drives the bell + inbox row text (string-only so the inbox
list stays cheap). `href`, when set, navigates instead of opening
the detail modal. `render` populates the detail modal body when
`href` is omitted. Atrium falls back to `kind` + a raw-JSON `<pre>`
for any kind without a registered renderer. Defined in
[`registry.ts`](../frontend/src/host/registry.ts); consumed by
[`NotificationsBell.tsx`](../frontend/src/components/NotificationsBell.tsx)
and [`NotificationsPage.tsx`](../frontend/src/routes/NotificationsPage.tsx).
Available since atrium 0.11.2.

### SSE subscriber
<a id="sse-subscriber"></a>

```ts
import { subscribeEvent } from '@brendanbank/atrium-host-types';

const unsubscribe = subscribeEvent('match.scheduled', ({ kind, payload }) => {
  queryClient.invalidateQueries({ queryKey: ['matches'] });
});
```

Atrium maintains a single `EventSource('/api/notifications/stream')`
connection; `subscribeEvent` taps into it. Use this for cache
invalidations driven by SSE-pushed events. The
`@brendanbank/atrium-host-bundle-utils/react` package ships
`useAtriumLocation()`, `useAtriumNavigate()`, `useAtriumUser()`, and
`useAtriumColorScheme()` as `useSyncExternalStore`-wrapped variants
for the equivalent `atrium:*` `CustomEvent`s on `window`. Available
since atrium 0.11.3 (typed `{kind, payload}` since 0.11.3 also).

### Locale overlay
<a id="locale-overlay"></a>

```ts
registerLocale({
  locale: 'en',
  strings: {
    'home.welcome': 'Welcome to the league.',
    leagues: { title: 'My leagues' },
  },
});
```

Layers on top of atrium's shipped strings and any admin-edited
overrides from `/app-config`. Precedence: shipped < admin overrides
< host overlay. Available since atrium 0.12.

The shared `common.*` keys atrium reserves (and host bundles can
read via `__atrium_t__`) are documented in
[`host-i18n.md`](host-i18n.md).

---

## Backend extension points

The host's backend module is loaded via `ATRIUM_HOST_MODULE`. It
must export `init_app(app)` for FastAPI registration and / or
`init_worker(host)` for the scheduler worker. The worker context
gives the host typed access to atrium's runtime; the API context is
the FastAPI app itself.

### Config namespace
<a id="config-namespace"></a>

```python
from pydantic import BaseModel
from app.services.app_config import register_namespace

class LeagueConfig(BaseModel):
    season_start_month: int = 9
    auto_close_after_days: int = 30

register_namespace("league", LeagueConfig, public=False)
```

Defined in [`backend/app/services/app_config.py`](../backend/app/services/app_config.py).
Once registered, the namespace shows up on `GET /api/admin/app-config`
(super-admin only) and is editable via `PUT /api/admin/app-config/league`.
`public=True` adds it to the unauthenticated `/api/app-config` bundle
the SPA fetches at boot. Defaults come from the Pydantic model -
*do not* write a seed migration; the row materialises on first PUT
and `model_validate` re-applies defaults for fields added since.
Call from any module that imports at startup (e.g. the host's
`init_app`). Available since atrium 0.9.

### Background job
<a id="background-job"></a>

```python
from app.host_sdk.worker import HostWorkerCtx
from sqlalchemy.ext.asyncio import AsyncSession

async def send_welcome_email(session: AsyncSession, job, payload: dict) -> None:
    ...

def init_worker(host: HostWorkerCtx) -> None:
    host.register_job_handler(
        kind="welcome_email",
        handler=send_welcome_email,
        description="Send welcome email after signup",
    )
    # ...or schedule a recurring tick:
    host.scheduler.add_job(weekly_rollup, "cron", day_of_week="mon", hour=2)
```

Defined in [`backend/app/host_sdk/worker.py`](../backend/app/host_sdk/worker.py);
invoked from [`backend/app/worker.py`](../backend/app/worker.py).
Job rows in `scheduled_jobs` carry `kind`, opaque `payload`, and
optional `entity_type` + `entity_id` for soft attribution. The
runner claims rows via `next_due_job` (FOR UPDATE SKIP LOCKED) so
multiple worker replicas are safe. Available since atrium 0.14.

### Synchronous email
<a id="synchronous-email"></a>

For host UI flows that need "send now" semantics (e.g. an admin
button that previews an email), `app.host_sdk.email.drain_outbox_row`
renders + sends a single `email_outbox` row from inside an API
handler:

```python
from app.host_sdk.email import drain_outbox_row

await drain_outbox_row(session, outbox_id=row_id)
```

Bypasses the scheduler's exponential backoff; use sparingly.
Available since atrium 0.16.

### Cross-base foreign key
<a id="cross-base-foreign-key"></a>

Host tables live on a separate SQLAlchemy `Base`, so a normal
`ForeignKey('users.id')` reference would fail Alembic autogenerate.
`HostForeignKey` marks the column as a logical FK; the
`emit_host_foreign_keys` autogen processor materialises the actual
constraint:

```python
# host model
from app.host_sdk.db import HostForeignKey

class League(Base):
    __tablename__ = "league"
    owner_id: Mapped[int] = mapped_column(HostForeignKey("users.id"))

# host's alembic/env.py
from app.host_sdk.alembic import emit_host_foreign_keys
context.configure(
    ...,
    process_revision_directives=emit_host_foreign_keys,
)
```

Defined in [`backend/app/host_sdk/db.py`](../backend/app/host_sdk/db.py)
and [`backend/app/host_sdk/alembic.py`](../backend/app/host_sdk/alembic.py).
Available since atrium 0.14.

---

## Test helpers
<a id="test-helpers"></a>

The [`@brendanbank/atrium-test-utils`](../packages/test-utils/src/index.ts)
package stubs the atrium globals a host bundle expects at import
time, so host unit tests don't reinvent the same fixture file each
time. Pinned in lockstep with the runtime image.

```ts
import { mockAtriumRegistry, renderWithAtrium, fireAtriumEvent } from '@brendanbank/atrium-test-utils';

const handles = mockAtriumRegistry();   // installs window.__ATRIUM_REGISTRY__
import('../src/main');                  // host bundle's import-time side effects run here

expect(handles.adminTabs).toHaveLength(1);
expect(handles.adminTabs[0]?.key).toBe('leagues');

const { getByText } = renderWithAtrium(<MyComponent />, { me: { permissions: ['league.manage'] } });
fireAtriumEvent('match.scheduled', { match_id: 1 });
```

A Python sibling for stubbing `app.db` / `app.services.app_config` /
`app.services.audit` is on the roadmap (see issue #132); for now,
host backend tests stub these per-test.

---

## What atrium does *not* expose

Several things look like they should be host extension points but
deliberately aren't. If you find yourself wanting one of these, file
an issue rather than monkey-patching:

- **Custom audit-log writers** - everything goes through
  `app.services.audit.record(...)` so the impersonator-context
  lookup stays consistent. Hosts emit audit rows by calling
  `record(...)` directly with a host-defined `action` string.
- **Custom auth flows** - the password / TOTP / email-OTP /
  WebAuthn matrix is fixed. Host apps tune *behaviour* via the
  `auth` config namespace (password policy, role-mandatory 2FA,
  signup defaults) but do not add new factor types.
- **Custom email backends** - `MAIL_BACKEND` env picks one of
  `console` / `smtp` / `dummy`. Hosts that need bespoke delivery
  (e.g. an internal mail relay with custom auth) wrap atrium's
  SMTP backend at the network layer rather than swapping the
  Python sender.
- **Replacing built-in routes** - a host's `init_app` runs *after*
  atrium's routers register, so a host route at the same path
  collides at startup rather than overriding silently. Host
  routers must use a `prefix="/api/<host-pkg>/..."` to stay clear
  of atrium's URL space (since 0.19.0).
