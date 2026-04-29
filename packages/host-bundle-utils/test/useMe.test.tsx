// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { afterAll, afterEach, beforeAll, describe, expect, test } from 'vitest';
import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

import {
  AtriumProvider,
  ME_QUERY_KEY,
  useMe,
  usePerm,
  useRole,
  useUserContext,
} from '../src/react/index';
import type { UserContext } from '@brendanbank/atrium-host-types';

const ALICE: UserContext = {
  id: 7,
  email: 'alice@example.com',
  full_name: 'Alice Example',
  is_active: true,
  roles: ['admin', 'user'],
  permissions: ['user.manage', 'audit.read'],
  impersonating_from: null,
};

const server = setupServer(
  http.get('/api/users/me/context', () => HttpResponse.json(ALICE)),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());

function makeClient() {
  // Disable retries so a 401 surfaces immediately and tests don't
  // wait for backoff.
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function withProviders(node: React.ReactNode, client = makeClient()) {
  return (
    <QueryClientProvider client={client}>
      <AtriumProvider>{node}</AtriumProvider>
    </QueryClientProvider>
  );
}

function MeProbe() {
  const { data, isLoading } = useMe();
  if (isLoading) return <span>loading</span>;
  if (!data) return <span>signed-out</span>;
  return <span data-testid="email">{data.email}</span>;
}

function UserContextProbe() {
  const { data } = useUserContext();
  return <span data-testid="ctx">{data ? data.full_name : '—'}</span>;
}

function PermProbe({ codes }: { codes: string[] }) {
  const hasPerm = usePerm();
  return (
    <ul>
      {codes.map((c) => (
        <li key={c} data-testid={`perm-${c}`}>
          {hasPerm(c) ? 'yes' : 'no'}
        </li>
      ))}
    </ul>
  );
}

function RoleProbe({ code }: { code: string }) {
  const has = useRole(code);
  return <span data-testid={`role-${code}`}>{has ? 'yes' : 'no'}</span>;
}

describe('useMe', () => {
  test('fetches and exposes the user context', async () => {
    render(withProviders(<MeProbe />));
    await waitFor(() =>
      expect(screen.getByTestId('email').textContent).toBe('alice@example.com'),
    );
  });

  test('useUserContext is an alias for useMe', async () => {
    render(withProviders(<UserContextProbe />));
    await waitFor(() =>
      expect(screen.getByTestId('ctx').textContent).toBe('Alice Example'),
    );
  });

  test('returns null when atrium responds 401', async () => {
    server.use(
      http.get('/api/users/me/context', () => new HttpResponse(null, { status: 401 })),
    );
    render(withProviders(<MeProbe />));
    await waitFor(() =>
      expect(screen.getByText('signed-out')).toBeInTheDocument(),
    );
  });

  test('shares one query subscription across hooks', async () => {
    let calls = 0;
    server.use(
      http.get('/api/users/me/context', () => {
        calls += 1;
        return HttpResponse.json(ALICE);
      }),
    );

    function Multi() {
      // Three hook calls in one tree must share a single fetch.
      useMe();
      useMe();
      const { data } = useMe();
      return <span data-testid="multi">{data?.id ?? -1}</span>;
    }

    render(withProviders(<Multi />));
    await waitFor(() =>
      expect(screen.getByTestId('multi').textContent).toBe('7'),
    );
    expect(calls).toBe(1);
  });

  test('ME_QUERY_KEY is a stable referenced key', () => {
    // Hosts depend on this for invalidation after flows that change
    // the user's roles or permissions. The exported tuple must be
    // structurally stable across renders.
    expect(ME_QUERY_KEY).toEqual(['atrium', 'me']);
  });
});

describe('usePerm', () => {
  test('returns true for permissions the user holds and false otherwise', async () => {
    render(
      withProviders(
        <PermProbe codes={['user.manage', 'audit.read', 'role.manage']} />,
      ),
    );

    await waitFor(() =>
      expect(screen.getByTestId('perm-user.manage').textContent).toBe('yes'),
    );
    expect(screen.getByTestId('perm-audit.read').textContent).toBe('yes');
    expect(screen.getByTestId('perm-role.manage').textContent).toBe('no');
  });

  test('returns false for every code while loading', () => {
    render(withProviders(<PermProbe codes={['user.manage']} />));
    // Synchronous render — the query hasn't resolved yet, so the
    // predicate must default to "deny".
    expect(screen.getByTestId('perm-user.manage').textContent).toBe('no');
  });
});

describe('useRole', () => {
  test('returns true for roles the user holds and false otherwise', async () => {
    render(
      withProviders(
        <>
          <RoleProbe code="admin" />
          <RoleProbe code="super_admin" />
        </>,
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId('role-admin').textContent).toBe('yes'),
    );
    expect(screen.getByTestId('role-super_admin').textContent).toBe('no');
  });
});

describe('AtriumProvider', () => {
  test('apiBase override changes the fetch URL', async () => {
    let hit = false;
    server.use(
      http.get('/v2/users/me/context', () => {
        hit = true;
        return HttpResponse.json({ ...ALICE, email: 'v2@example.com' });
      }),
    );
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <AtriumProvider apiBase="/v2">
          <MeProbe />
        </AtriumProvider>
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('email').textContent).toBe('v2@example.com'),
    );
    expect(hit).toBe(true);
  });

  test('custom fetchUserContext bypasses fetch entirely', async () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <AtriumProvider
          fetchUserContext={async () => ({
            ...ALICE,
            email: 'injected@example.com',
          })}
        >
          <MeProbe />
        </AtriumProvider>
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('email').textContent).toBe(
        'injected@example.com',
      ),
    );
  });

  test('client prop wraps children in QueryClientProvider', async () => {
    // No outer QueryClientProvider — the provider supplies one itself.
    const client = makeClient();
    render(
      <AtriumProvider client={client}>
        <MeProbe />
      </AtriumProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('email').textContent).toBe('alice@example.com'),
    );
  });
});
