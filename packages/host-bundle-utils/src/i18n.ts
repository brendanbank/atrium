// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Shared-i18n helper for host bundles.
 *
 * Atrium ships a small ``common.*`` key set (verbs, structural labels,
 * confirmation patterns) translated to every locale atrium supports.
 * A host bundle that calls ``__atrium_t__('common.save')`` gets the
 * right string in nl / de / fr automatically, and any new locale
 * atrium adds upstream (e.g. a future ``pt-BR``) reaches every host
 * on the next package update — no host release required.
 *
 * Resolution path:
 *
 *   1. ``window.__atrium_i18n__`` — atrium's i18next instance,
 *      published since atrium 0.14.0 from the SPA's i18n module. Reads
 *      the active locale dynamically, so a user switching language in
 *      the profile page reaches the next ``__atrium_t__`` call without
 *      the host re-rendering.
 *   2. Fallback to English bundled in i18next via ``fallbackLng``. A
 *      key without a translation in the active locale resolves to the
 *      English string instead of the literal key.
 *   3. Final fallback: the literal key itself. This kicks in when the
 *      atrium image predates 0.14.0 (no ``window.__atrium_i18n__``)
 *      or when the key is unknown to atrium. Returning the key (not
 *      empty string) makes the missing-key visible at the call site so
 *      a typo is debuggable.
 *
 * The helper is a plain function, not a hook. Atrium's i18next
 * instance fires its own change events on locale switch; host
 * components that need to re-render on switch should consume
 * ``react-i18next``'s ``useTranslation`` against the shared instance,
 * or call ``__atrium_t__`` inside a component subscribed to atrium's
 * locale via the host's own state. The function is enough for the
 * static-render case which covers the bulk of host UI.
 */

interface MinimalI18n {
  /** The active locale code (e.g. ``'nl'``). */
  language?: string;
  /** i18next's ``t`` — `key` is a flat dot-path, ``vars`` are the
   *  interpolation values. ``defaultValue`` makes the key the safe
   *  fallback when the lookup misses. */
  t: (
    key: string,
    options?: Record<string, unknown> & { defaultValue?: string },
  ) => string;
}

/** Translate a shared atrium key against the running atrium image's
 *  i18next instance.
 *
 *  ```ts
 *  import { __atrium_t__ } from '@brendanbank/atrium-host-bundle-utils';
 *
 *  <Button>{__atrium_t__('common.save')}</Button>
 *  <Text>{__atrium_t__('common.welcome', { name: me.full_name })}</Text>
 *  ```
 *
 *  - Missing atrium image (pre-0.14): returns the literal key.
 *  - Missing key: returns the literal key (not empty string), so a
 *    typo is visible in the rendered output.
 *  - Missing translation in the active locale: falls back to English
 *    via i18next's ``fallbackLng``. */
export function __atrium_t__(
  key: string,
  vars?: Record<string, string | number>,
): string {
  if (typeof window === 'undefined') return key;
  const i18n = (window as unknown as { __atrium_i18n__?: MinimalI18n })
    .__atrium_i18n__;
  if (!i18n || typeof i18n.t !== 'function') return key;
  // ``defaultValue: key`` is the explicit "missing key → key" rule.
  // i18next's default behaviour already returns the key when the
  // lookup misses, but spelling it out makes the intent unambiguous
  // and survives any future i18next config change in atrium.
  const out = i18n.t(key, { ...vars, defaultValue: key });
  return typeof out === 'string' ? out : key;
}
