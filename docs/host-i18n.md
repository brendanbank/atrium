# Host i18n

Atrium translates a small set of structural strings (verbs, labels,
confirmation patterns) and exposes them to host bundles through the
shared `common.*` namespace. A host that calls
`__atrium_t__('common.save')` gets the right string in every locale
atrium ships, and any new locale atrium adds upstream (e.g. a future
`pt-BR`) reaches every host on the next package update — no host
release required.

The helper is the i18n complement to the [stable theme
tokens](theme.md): atrium picks a small, opinionated subset and
commits to it; the host depends on the subset and contributes its
own domain-specific strings on top.

## Available since

`__atrium_t__` is exported from
`@brendanbank/atrium-host-bundle-utils@>=0.14.0` (both the package
root and the `/react` subpath). It reads
`window.__atrium_i18n__`, populated by atrium 0.14.0 from the SPA's
i18n module before the host bundle imports.

On older atrium images the global is undefined and the helper falls
back to returning the key. Hosts pinning `^0.14` in
`backend/pyproject.toml` get the helper everywhere.

## Usage

```tsx
import { __atrium_t__ } from '@brendanbank/atrium-host-bundle-utils';

<Button onClick={save}>{__atrium_t__('common.save')}</Button>
<Text>{__atrium_t__('common.welcomeNamed', { name: me.full_name })}</Text>
```

Plain function — call it directly from a render. It is **not** a
hook, so it does not subscribe to locale changes; a host page that
needs to re-render on language switch should use react-i18next's
`useTranslation` against atrium's instance, or call `__atrium_t__`
inside a tree that already re-renders on the host's own locale state.

The function returns a `string`. Resolution order:

1. The active locale on `window.__atrium_i18n__`.
2. English (atrium's `fallbackLng`).
3. The literal key (so a typo is visible in the rendered output, not
   silently empty).

Interpolation uses `{{name}}` placeholders; pass values as the second
arg.

## The `common.*` keys

Verbs:

| Key                | English       |
| ------------------ | ------------- |
| `common.save`      | Save          |
| `common.cancel`    | Cancel        |
| `common.delete`    | Delete        |
| `common.edit`      | Edit          |
| `common.new`       | New           |
| `common.close`     | Close         |
| `common.confirm`   | Confirm       |
| `common.back`      | Back          |

Structural / status:

| Key               | English                  |
| ----------------- | ------------------------ |
| `common.loading`  | Loading…                 |
| `common.empty`    | Nothing here yet.        |
| `common.error`    | Something went wrong.    |
| `common.search`   | Search                   |
| `common.required` | Required                 |
| `common.language` | Language                 |

Confirmation patterns:

| Key                       | English                                          |
| ------------------------- | ------------------------------------------------ |
| `common.confirmDelete`    | Delete this item? This cannot be undone.         |
| `common.confirmDiscard`   | Discard unsaved changes?                         |

Translations ship for every locale atrium supports today: `en`,
`nl`, `de`, `fr`. Add a locale upstream and it appears for every
host on the next package update.

## What does **not** belong here

`common.*` is verbs and structural labels only. Anything
domain-shaped goes in the host's own i18n bundle:

- `common.user`, `common.role`, `common.invoice` — domain semantics
  drift across hosts (a "role" in casa is not a "role" in atrium).
- `common.welcome` outside of a generic shell context — host
  homepages have their own voice.
- Anything plural or count-aware — i18next plurals are locale-aware
  and the host should own the domain noun the count attaches to.

When in doubt: if removing the key from atrium would surprise a
host integrator, it belongs here; otherwise it doesn't.

## Adding a key

1. Add the new key to every locale JSON under
   `frontend/src/i18n/locales/{en,nl,de,fr}.json` in the `common`
   section. Translations should ship together — landing an English
   key without translations puts every non-English host on the
   English fallback until a follow-up.
2. Update the table in this file.
3. Bump the docstring in
   `packages/host-bundle-utils/src/i18n.ts` if the key requires
   special interpolation rules; otherwise no code change is needed.

The package version that exposes the key has to be `>=` the atrium
version that ships the locale JSONs. We bump in lockstep — one
release covers both.

## Adding a locale

Follow the same pattern as adding the four locales atrium ships
today:

1. Drop a `frontend/src/i18n/locales/<code>.json` with every key the
   existing locales carry. The `common.*` namespace is the
   minimum; the rest of the chrome strings are the bulk of the file.
2. Wire the locale into `frontend/src/i18n/index.ts` — add it to the
   `SUPPORTED` tuple and to the `resources` block.
3. Bump `backend/pyproject.toml`, publish a new atrium image, and
   the new locale reaches every host on the next image pull.

The `i18n.enabled_locales` admin control in
`/admin/app-config` filters which locales the SPA exposes in the
language picker — atrium can ship more locales than a given
deployment chooses to expose.
