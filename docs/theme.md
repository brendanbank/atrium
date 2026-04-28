# Theme tokens — what hosts can rely on

Atrium renders its UI through Mantine v9, which injects a large set of
`--mantine-*` CSS custom properties on `:root` from the active theme.
Host bundles inherit those variables for free — colour-scheme switching
included — but the wire surface is large and hosts have no built-in
signal as to which tokens atrium commits to keeping stable across
minor releases.

This page is the contract: which subset of the rendered tokens atrium
treats as a public interface, which ones hosts may safely override,
and which ones are internal and may be renamed without a major-version
bump.

For the wider host extension contract, see
[`published-images.md`](published-images.md). For the per-release delta
on registry hooks and wire formats, see
[`compat-matrix.md`](compat-matrix.md).

---

## Stable tokens

The following tokens are **stable across minor atrium releases**. They
are governed either by Mantine's own naming conventions (which atrium
inherits without renaming) or by atrium's branding contract. A host
bundle may depend on these in CSS, in styled-component literals, or as
the read side of a runtime computation; atrium will not break them in
a `0.X.Y` release.

### Palette

- `--mantine-color-{name}-{0..9}` — the full Mantine colour scale for
  every named palette (`teal`, `red`, `blue`, `cyan`, `gray`, `dark`,
  `pink`, `grape`, `violet`, `indigo`, `green`, `lime`, `yellow`,
  `orange`). Shade indices `0` (lightest) through `9` (darkest) are
  Mantine's stability guarantee, not atrium's — but atrium will never
  rename or remove a Mantine palette while the underlying Mantine
  major version supports it.
- `--mantine-color-{name}-light` / `--mantine-color-{name}-light-hover`
  / `--mantine-color-{name}-filled` and friends — the variant tokens
  Mantine emits per palette. Same Mantine-governed stability.
- `--mantine-primary-color-{0..9}` — alias of the active primary
  palette, set by `BrandConfig.preset` + `BrandConfig.overrides.primaryColor`.
  Shade indices are stable; the *value* changes with branding, which
  is the whole point.

### Spacing, sizing, typography

- `--mantine-spacing-{xs,sm,md,lg,xl}` — spacing scale.
- `--mantine-font-size-{xs,sm,md,lg,xl}` — body font-size scale.
- `--mantine-line-height-{xs,sm,md,lg,xl}` — line-height scale.
- `--mantine-radius-{xs,sm,md,lg,xl}` — border-radius scale (the named
  steps; the active default is `BrandConfig.overrides.defaultRadius`).
- `--mantine-font-family` — the active body font stack, derived from
  `BrandConfig.overrides.fontFamily` (or the active preset's default).
- `--mantine-font-family-headings` — the active headings font stack,
  derived from `BrandConfig.overrides.headingsFontFamily`.
- `--mantine-font-family-monospace` — Mantine's default mono stack.

### Color scheme

- `[data-mantine-color-scheme="light" | "dark"]` on `<html>` — the
  active scheme attribute. Use this in CSS as the canonical
  light/dark switch (`@media (prefers-color-scheme: …)` is *not*
  authoritative because atrium can force the scheme per preset — see
  `colorSchemeForPreset` in [`frontend/src/theme/index.ts`](../frontend/src/theme/index.ts)).
  Mantine's `light-dark()` CSS function works against the same
  attribute.

If atrium needs to break any of the above, it will be called out in
the [compat matrix](compat-matrix.md) and treated as a
breaking change.

---

## Override-friendly

The following tokens are the **intended channel for runtime branding**.
Operators set them through the admin UI (Branding tab), which writes
to `app_settings['brand']`; the SPA rebuilds its Mantine theme on the
next `/app-config` poll.

| `BrandConfig.overrides` key | Effect on Mantine theme |
|-----------------------------|------------------------|
| `primaryColor`              | `theme.primaryColor` — selects the active palette name from the Mantine set listed under Stable tokens. |
| `primaryShade`              | `theme.primaryShade` — integer 0..9 picking the shade used as the default fill. |
| `defaultRadius`             | `theme.defaultRadius` — one of `xs`/`sm`/`md`/`lg`/`xl`. |
| `fontFamily`                | `theme.fontFamily` — body font stack. |
| `headingsFontFamily`        | `theme.headings.fontFamily` — headings font stack. |

Five keys, five form fields. Anything outside this list is dropped
silently when the theme is built (see `ALLOWED_OVERRIDE_KEYS` in
[`frontend/src/theme/index.ts`](../frontend/src/theme/index.ts)) —
the `app_settings.brand.overrides` JSON column is intentionally
permissive (so an admin editing the raw row can't inject CSS) and only
these five tokens roundtrip through the form.

Host bundles **should not** ship their own raw-CSS overrides for the
same palette / radius / font tokens — that fights the admin UI and
desyncs operator-facing branding from what the host renders. If your
host needs branding the admin UI doesn't expose today, file an issue
against atrium proposing a new `BrandConfig` field; the goal is to
keep the override surface narrow and Pydantic-validated.

Hosts that mount their own MantineProvider inside the host subtree
(the bundled-React pattern documented in
[`published-images.md`](published-images.md)) are unaffected — that
provider's theme is local to the host's subtree and doesn't reach
atrium's shell. Read `BrandConfig` from `/app-config` if you want the
host's local theme to follow the operator's branding.

---

## Don't touch

Anything **not** in the two sections above is internal. Atrium reserves
the right to rename, remove, or repurpose these tokens without a major
version bump.

In particular:

- **Component-internal Mantine custom properties** — `--button-…`,
  `--paper-…`, `--input-…`, and any other token Mantine emits for a
  specific component. Mantine governs these and they may move between
  Mantine majors; atrium does not promise to absorb Mantine renames.
- **Layout-specific custom properties** scoped to atrium's shell —
  the AppLayout, header, sidebar, and admin pages may use ad-hoc
  custom properties for one-off spacing or accent colours. These are
  implementation detail, not a contract.
- **Anything inside `[data-atrium-internal]`** if you see it. Atrium
  doesn't ship such a marker today, but if one appears later it's a
  red flag for "this exists for atrium's own layout, do not depend on
  it."

There are currently **no `--atrium-*`-prefixed CSS custom properties**
shipped by atrium. If a host bundle depends on a hand-rolled
`--atrium-…` variable it has either invented its own naming
convention (fine, but it's the host's contract) or imported a value
that doesn't actually exist (the usual cause: copying a snippet from
an early TODO that never landed). Use the tokens listed above instead.

---

## How this contract is versioned

The token classification on this page is part of atrium's host
contract. Tokens listed under **Stable** or **Override-friendly** will
not change incompatibly between two atrium releases that share a
`MAJOR.MINOR` prefix. A change that promotes an internal token to
stable is additive and goes out in a regular minor release; a change
that demotes a stable token requires a major bump and a row in the
[compat matrix](compat-matrix.md) calling it out.

If you're unsure whether a token is stable, grep this page first; if
it's not listed, treat it as internal.
