// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for ``HomePage``'s host-widget gate (issue #100).
 * Once a host has registered ≥ 1 home widget, the starter shell's
 * "Welcome, <name>" greeting + integrator-onboarding intro read as
 * orphan chrome above whatever the widget itself owns. This pins the
 * gate so a future refactor can't silently re-introduce the ghost
 * heading.
 *
 * The contract:
 *  - Empty registry: greeting + intro render (preserves the
 *    fresh-starter zero-widget experience).
 *  - Any host widget registered: both lines disappear; the widget's
 *    own content is the page.
 *  - The action buttons (Profile / Notifications / Admin) stay either
 *    way — they're nav, not chrome.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import '@/i18n';
import { HomePage } from '@/routes/HomePage';
import { ME_QUERY_KEY } from '@/hooks/useAuth';
import type { CurrentUser } from '@/lib/auth';
import {
  __resetRegistryForTests,
  registerHomeWidget,
} from '@/host/registry';

function makeUser(): CurrentUser {
  return {
    id: 1,
    email: 'alice@example.com',
    full_name: 'Alice Example',
    is_active: true,
    is_verified: true,
    is_superuser: false,
    phone: null,
    preferred_language: 'en',
    roles: ['admin'],
    permissions: [],
    impersonating_from: null,
  } as CurrentUser;
}

function renderHome() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  qc.setQueryData(ME_QUERY_KEY, makeUser());
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('HomePage — host-widget gate (#100)', () => {
  beforeEach(() => {
    cleanup();
    __resetRegistryForTests();
  });

  afterEach(() => {
    cleanup();
    __resetRegistryForTests();
  });

  it('renders the greeting + intro on a fresh starter (zero widgets)', () => {
    renderHome();
    expect(
      screen.getByRole('heading', { level: 2, name: /welcome, alice/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'This is the Atrium starter shell. Hook your domain pages onto the routes from here.',
      ),
    ).toBeInTheDocument();
  });

  it('hides both greeting and intro when a host widget is registered', () => {
    registerHomeWidget({
      key: 'host-card',
      render: () => <div data-testid="host-card">host content</div>,
    });
    renderHome();
    expect(screen.getByTestId('host-card')).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { level: 2, name: /welcome/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        'This is the Atrium starter shell. Hook your domain pages onto the routes from here.',
      ),
    ).not.toBeInTheDocument();
  });

  it('keeps the nav action buttons even when a host widget is registered', () => {
    registerHomeWidget({
      key: 'host-card',
      render: () => <div>host</div>,
    });
    renderHome();
    // Profile / Notifications are unconditional; Admin shows because
    // the seeded user has the ``admin`` role. The buttons render as
    // links via ``<Button component={Link}>`` so probe them by role.
    expect(screen.getByRole('link', { name: /profile/i })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /notifications/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /admin/i })).toBeInTheDocument();
  });
});
