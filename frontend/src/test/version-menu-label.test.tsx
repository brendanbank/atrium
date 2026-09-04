// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Coverage for the version block in the user menu.
 *
 * The feature exists so an operator can answer "which atrium, and
 * which build of the app on top of it?" without exec-ing into a
 * container, so the cases that matter are the degraded ones: an
 * untagged build (commit is the identity), a host image that stamped
 * a version but no name, and an unreachable / unstamped backend where
 * the block must vanish entirely rather than render an empty label
 * with a stray divider under it.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { Menu, MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import { VersionMenuLabel } from '@/components/VersionMenuLabel';
import type { VersionInfo } from '@/hooks/useVersion';
import { api } from '@/lib/api';

const testI18n = i18n.createInstance();
void testI18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  resources: {
    en: { translation: { version: { atrium: 'Atrium', app: 'App' } } },
  },
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderMenu(appName?: string) {
  // Fresh client per render — the hook caches with staleTime Infinity,
  // so a shared one would serve the previous test's payload.
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={testI18n}>
        <QueryClientProvider client={qc}>
          <Menu opened>
            <Menu.Target>
              <button type="button">menu</button>
            </Menu.Target>
            <Menu.Dropdown>
              <VersionMenuLabel appName={appName} />
            </Menu.Dropdown>
          </Menu>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

function mockVersion(payload: VersionInfo) {
  vi.spyOn(api, 'get').mockResolvedValue({ data: payload });
}

describe('VersionMenuLabel', () => {
  it('shows the atrium tag above the app tag', async () => {
    mockVersion({
      atrium: { name: 'Atrium', version: 'v0.29.1', commit: 'a'.repeat(40) },
      app: { name: 'West Monroe', version: '1.4.0', commit: 'b'.repeat(40) },
    });
    renderMenu();

    const block = await screen.findByTestId('version-info');
    // Tags render verbatim — the ``v`` is part of what you'd type
    // into ``git checkout``, so it isn't cosmetically stripped.
    expect(block).toHaveTextContent('Atrium v0.29.1');
    expect(block).toHaveTextContent('West Monroe 1.4.0');
    // Order is part of the contract — the base layer reads first.
    expect(block.textContent).toMatch(/Atrium v0\.29\.1.*West Monroe 1\.4\.0/s);
  });

  it('falls back to "name: sha" when the build carried no tag', async () => {
    mockVersion({
      atrium: { name: 'Atrium', version: 'v0.29.1', commit: 'a'.repeat(40) },
      app: { name: 'atrium-pa', version: null, commit: '22d2801deadbeef' },
    });
    renderMenu();

    const block = await screen.findByTestId('version-info');
    // The colon distinguishes a sha from a version — without it
    // "atrium-pa 22d2801" reads like a strange version number.
    expect(block).toHaveTextContent('atrium-pa: 22d2801');
    // Both layers stay visible; losing the tag on one doesn't hide
    // the other.
    expect(block).toHaveTextContent('Atrium v0.29.1');
    // Full sha stays reachable for `git show`.
    expect(block.querySelector('[title="22d2801deadbeef"]')).not.toBeNull();
  });

  it('labels an unnamed host image with the brand name', async () => {
    mockVersion({
      atrium: { name: 'Atrium', version: 'v0.29.1', commit: null },
      app: { name: null, version: '2.0.0', commit: null },
    });
    renderMenu('West Monroe');

    const block = await screen.findByTestId('version-info');
    expect(block).toHaveTextContent('West Monroe 2.0.0');
  });

  it('renders nothing — not even a divider — when /version fails', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('boom'));
    const { container } = renderMenu();

    await waitFor(() =>
      expect(screen.queryByTestId('version-info')).toBeNull(),
    );
    expect(container.querySelector('.mantine-Menu-divider')).toBeNull();
  });

  it('renders nothing when the image carries no stamp at all', async () => {
    mockVersion({
      atrium: { name: 'Atrium', version: null, commit: null },
      app: null,
    });
    const { container } = renderMenu();

    await waitFor(() =>
      expect(screen.queryByTestId('version-info')).toBeNull(),
    );
    expect(container.querySelector('.mantine-Menu-divider')).toBeNull();
  });
});
