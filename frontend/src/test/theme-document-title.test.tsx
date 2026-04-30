// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for ``ThemedApp``'s ``document.title`` sync (issue
 * #99). The browser tab title was stuck on the literal "Atrium" baked
 * into ``frontend/index.html`` even after an admin renamed the brand,
 * so a tenant on ``app.example.com`` renamed to "Acme" still shipped
 * ``<title>Atrium</title>`` in view-source. ``ThemedApp`` now mirrors
 * ``brand.name`` from the public ``/app-config`` bundle into
 * ``document.title`` whenever the bundle refetches.
 *
 * The contract:
 *  - On mount, the title becomes the loaded brand name.
 *  - A subsequent rename in the cache propagates without a reload.
 *  - An unloaded / blank / whitespace-only name leaves the existing
 *    title alone (preserves the index.html default).
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ThemedApp } from '@/theme/ThemedApp';

// Mirrors the local ``PUBLIC_KEY`` in ``@/hooks/useAppConfig`` — not
// exported, so the test inlines it.
const APP_CONFIG_KEY = ['app-config'] as const;

const INDEX_HTML_DEFAULT = 'Atrium';

function makeClient(brand?: { name?: string; preset?: string }): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (brand) {
    qc.setQueryData(APP_CONFIG_KEY, {
      brand: { preset: 'default', ...brand },
      system: {},
      i18n: {},
    });
  }
  return qc;
}

function renderThemed(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <ThemedApp>
        <div />
      </ThemedApp>
    </QueryClientProvider>,
  );
}

describe('ThemedApp document.title sync', () => {
  beforeEach(() => {
    cleanup();
    document.title = INDEX_HTML_DEFAULT;
  });

  afterEach(() => {
    cleanup();
    document.title = INDEX_HTML_DEFAULT;
  });

  it('mirrors brand.name into document.title on mount', async () => {
    renderThemed(makeClient({ name: 'Acme' }));
    await waitFor(() => expect(document.title).toBe('Acme'));
  });

  it('updates document.title when brand.name changes in the cache', async () => {
    const qc = makeClient({ name: 'Acme' });
    renderThemed(qc);
    await waitFor(() => expect(document.title).toBe('Acme'));

    qc.setQueryData(APP_CONFIG_KEY, {
      brand: { name: 'Casa del Leone', preset: 'default' },
      system: {},
      i18n: {},
    });
    await waitFor(() => expect(document.title).toBe('Casa del Leone'));
  });

  it('leaves document.title alone while the bundle is still loading', () => {
    // Empty cache — useAppConfig returns ``data === undefined``. The
    // index.html default must survive the first render so a
    // disconnected backend doesn't flash a blank tab.
    renderThemed(makeClient(undefined));
    expect(document.title).toBe(INDEX_HTML_DEFAULT);
  });

  it('ignores blank / whitespace-only brand names', async () => {
    renderThemed(makeClient({ name: '   ' }));
    // No assertion on a delayed transition — just confirm the existing
    // title isn't overwritten with whitespace. waitFor a microtask so
    // the effect has a chance to run.
    await Promise.resolve();
    expect(document.title).toBe(INDEX_HTML_DEFAULT);
  });
});
