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
 *  - Empty registry: greeting + intro + nav action buttons render
 *    (preserves the fresh-starter zero-widget experience and gives
 *    the user a way into Profile / Notifications / Admin).
 *  - Any host widget registered: the entire welcome container drops
 *    as a unit — greeting, intro, and the Profile / Notifications /
 *    Admin buttons. The buttons read as orphan atrium chrome above
 *    a host widget; Profile / Notifications / Admin are still
 *    reachable from the navbar in either case (issue #100).
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

  it('drops the nav action buttons with the welcome container when a host widget is registered', () => {
    registerHomeWidget({
      key: 'host-card',
      render: () => <div>host</div>,
    });
    renderHome();
    // The welcome container ships greeting + intro + Profile /
    // Notifications / Admin buttons together; once a host widget
    // registers it drops as a unit so atrium chrome doesn't sit
    // above the host's content. Profile / Notifications / Admin are
    // still reachable from the navbar.
    expect(
      screen.queryByRole('link', { name: /profile/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: /notifications/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: /admin/i }),
    ).not.toBeInTheDocument();
  });

  it('renders the nav action buttons on a fresh starter (zero widgets)', () => {
    renderHome();
    // Empty-registry case: the buttons must still be there so a
    // fresh starter has a way into the rest of the app.
    expect(screen.getByRole('link', { name: /profile/i })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /notifications/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /admin/i })).toBeInTheDocument();
  });
});
