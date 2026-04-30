// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for the color-scheme bridge.
 *
 * Pins down the contract host bundles rely on (atrium #96):
 *
 *  - On mount the bridge stamps the resolved scheme onto
 *    ``window.__ATRIUM_COLOR_SCHEME__`` synchronously and does NOT
 *    dispatch (a host that mounts later reads the global).
 *  - Subsequent preset changes refresh the global AND fire one
 *    ``atrium:colorschemechange`` CustomEvent with
 *    ``{previous, current, nonce}``.
 *  - The same scheme re-rendering is a no-op.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import {
  ATRIUM_COLOR_SCHEME_EVENT,
  ATRIUM_COLOR_SCHEME_GLOBAL,
  ColorSchemeBridge,
  __resetColorSchemeNonceForTests,
  dispatchColorSchemeChange,
  type AtriumColorScheme,
  type AtriumColorSchemeChangeDetail,
} from '@/host/color-scheme';

// Mirrors the local `PUBLIC_KEY` in `@/hooks/useAppConfig` — not
// exported, so the test inlines it.
const APP_CONFIG_KEY = ['app-config'] as const;

type Capture = AtriumColorSchemeChangeDetail[];

function captureEvents(): { events: Capture; off: () => void } {
  const events: Capture = [];
  const handler = (e: Event) => {
    const detail = (e as CustomEvent<AtriumColorSchemeChangeDetail>).detail;
    events.push({ ...detail });
  };
  window.addEventListener(ATRIUM_COLOR_SCHEME_EVENT, handler);
  return {
    events,
    off: () => window.removeEventListener(ATRIUM_COLOR_SCHEME_EVENT, handler),
  };
}

function makeClient(preset: 'default' | 'dark-glass' | 'classic'): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  qc.setQueryData(APP_CONFIG_KEY, {
    brand: { preset },
    system: {},
    i18n: {},
  });
  return qc;
}

function renderBridge(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <ColorSchemeBridge />
    </QueryClientProvider>,
  );
}

function readGlobal(): AtriumColorScheme | undefined {
  return (window as unknown as Record<string, AtriumColorScheme | undefined>)[
    ATRIUM_COLOR_SCHEME_GLOBAL
  ];
}

describe('ColorSchemeBridge', () => {
  beforeEach(() => {
    cleanup();
    __resetColorSchemeNonceForTests();
    delete (window as unknown as Record<string, unknown>)[
      ATRIUM_COLOR_SCHEME_GLOBAL
    ];
  });

  afterEach(() => {
    cleanup();
  });

  it('stamps the global on mount without dispatching (default preset → "auto")', async () => {
    const cap = captureEvents();
    try {
      renderBridge(makeClient('default'));
      await waitFor(() => expect(readGlobal()).toBe('auto'));
      expect(cap.events).toHaveLength(0);
    } finally {
      cap.off();
    }
  });

  it('stamps the global on mount for dark-glass preset → "dark"', async () => {
    const cap = captureEvents();
    try {
      renderBridge(makeClient('dark-glass'));
      await waitFor(() => expect(readGlobal()).toBe('dark'));
      expect(cap.events).toHaveLength(0);
    } finally {
      cap.off();
    }
  });

  it('dispatches when the preset flip changes the resolved scheme', async () => {
    const cap = captureEvents();
    try {
      const qc = makeClient('default');
      renderBridge(qc);
      await waitFor(() => expect(readGlobal()).toBe('auto'));

      qc.setQueryData(APP_CONFIG_KEY, {
        brand: { preset: 'dark-glass' },
        system: {},
        i18n: {},
      });

      await waitFor(() => expect(cap.events).toHaveLength(1));
      expect(cap.events[0]).toEqual({
        previous: 'auto',
        current: 'dark',
        nonce: 1,
      });
      expect(readGlobal()).toBe('dark');
    } finally {
      cap.off();
    }
  });

  it('does not dispatch when a preset change resolves to the same scheme', async () => {
    // ``default`` and ``classic`` both resolve to ``"auto"`` — switching
    // between them must not produce a colorschemechange event.
    const cap = captureEvents();
    try {
      const qc = makeClient('default');
      renderBridge(qc);
      await waitFor(() => expect(readGlobal()).toBe('auto'));

      qc.setQueryData(APP_CONFIG_KEY, {
        brand: { preset: 'classic' },
        system: {},
        i18n: {},
      });
      // Give the effect a chance to fire and any latent dispatch
      // a chance to land.
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(cap.events).toHaveLength(0);
    } finally {
      cap.off();
    }
  });

  it('attaches a monotonically-increasing nonce to every event', () => {
    const cap = captureEvents();
    try {
      dispatchColorSchemeChange({ previous: 'auto', current: 'dark' });
      dispatchColorSchemeChange({ previous: 'dark', current: 'auto' });
      dispatchColorSchemeChange({ previous: 'auto', current: 'dark' });

      const nonces = cap.events.map((e) => e.nonce);
      expect(nonces.length).toBe(3);
      expect(nonces[1]).toBeGreaterThan(nonces[0]);
      expect(nonces[2]).toBeGreaterThan(nonces[1]);
    } finally {
      cap.off();
    }
  });

  it('refreshes window.__ATRIUM_COLOR_SCHEME__ on every dispatch', () => {
    const cap = captureEvents();
    try {
      dispatchColorSchemeChange({ previous: null, current: 'dark' });
      expect(readGlobal()).toBe('dark');
      dispatchColorSchemeChange({ previous: 'dark', current: 'auto' });
      expect(readGlobal()).toBe('auto');
    } finally {
      cap.off();
    }
  });
});
