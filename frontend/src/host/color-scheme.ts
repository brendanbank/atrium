// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Atrium color-scheme bridge for host bundles.
 *
 * Mantine providers don't inherit a parent provider's color scheme —
 * a nested ``<MantineProvider>`` defaults to ``"light"`` regardless
 * of what the outer provider resolves. Atrium's outer provider is
 * driven by the brand preset (``"auto"`` for every preset except
 * ``dark-glass``, which forces ``"dark"``); a host bundle that
 * mounts its own ``<MantineProvider>`` therefore renders in light
 * mode while atrium's chrome flips to dark, producing a two-tone UI
 * on systems set to dark mode (atrium #96).
 *
 * To close the gap atrium publishes the resolved scheme on
 * ``window.__ATRIUM_COLOR_SCHEME__`` synchronously and dispatches an
 * ``atrium:colorschemechange`` CustomEvent on every transition. Host
 * bundles read the global on first paint (no flicker) and subscribe
 * to the event for subsequent admin-side preset changes via
 * ``useAtriumColorScheme()`` in
 * ``@brendanbank/atrium-host-bundle-utils/react``.
 */
import { useEffect, useRef } from 'react';

import { useAppConfig } from '@/hooks/useAppConfig';
import { colorSchemeForPreset } from '@/theme';

export type AtriumColorScheme = 'auto' | 'light' | 'dark';

export type AtriumColorSchemeChangeDetail = {
  /** Scheme before the change. ``null`` on the first dispatch (no
   *  prior value observed in this tab). */
  previous: AtriumColorScheme | null;
  /** Scheme after the change. */
  current: AtriumColorScheme;
  /** Monotonic counter, incremented atomically by atrium on every
   *  ``atrium:colorschemechange`` dispatch. */
  nonce: number;
};

export const ATRIUM_COLOR_SCHEME_EVENT = 'atrium:colorschemechange';
export const ATRIUM_COLOR_SCHEME_GLOBAL = '__ATRIUM_COLOR_SCHEME__';

let nextNonce = 0;

function writeWindowScheme(scheme: AtriumColorScheme): void {
  if (typeof window === 'undefined') return;
  (window as unknown as Record<string, AtriumColorScheme>)[
    ATRIUM_COLOR_SCHEME_GLOBAL
  ] = scheme;
}

/** Fire a single ``atrium:colorschemechange`` event on ``window`` and
 *  refresh the ``__ATRIUM_COLOR_SCHEME__`` global. The helper adds a
 *  fresh monotonic nonce. */
export function dispatchColorSchemeChange(
  detail: Omit<AtriumColorSchemeChangeDetail, 'nonce'>,
): void {
  if (typeof window === 'undefined') return;
  writeWindowScheme(detail.current);
  const nonce = ++nextNonce;
  window.dispatchEvent(
    new CustomEvent<AtriumColorSchemeChangeDetail>(ATRIUM_COLOR_SCHEME_EVENT, {
      detail: { ...detail, nonce },
    }),
  );
}

/** Mounts inside the atrium SPA. On first observation it stamps the
 *  resolved scheme onto ``window.__ATRIUM_COLOR_SCHEME__`` without
 *  dispatching (a host bundle that mounts later reads the current
 *  value off the global). Subsequent changes — operator flips the
 *  brand preset in app-config — fire ``atrium:colorschemechange``. */
export function ColorSchemeBridge(): null {
  const { data } = useAppConfig();
  const preset = data?.brand?.preset ?? 'default';
  const scheme = colorSchemeForPreset(preset);
  // ``undefined`` on the first render — distinguishes "no scheme
  // observed yet" (write-only baseline) from "we already published a
  // scheme and it's changing now" (write + dispatch).
  const lastSchemeRef = useRef<AtriumColorScheme | undefined>(undefined);

  useEffect(() => {
    const previous = lastSchemeRef.current;
    if (previous === undefined) {
      lastSchemeRef.current = scheme;
      writeWindowScheme(scheme);
      return;
    }
    if (previous === scheme) return;
    lastSchemeRef.current = scheme;
    dispatchColorSchemeChange({ previous, current: scheme });
  }, [scheme]);

  return null;
}

/** Test-only: reset the module-level nonce counter so each test
 *  starts from a known baseline. Production code never calls this. */
export function __resetColorSchemeNonceForTests(): void {
  nextNonce = 0;
}
