// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Worked example of testing a host bundle component with
 * `@brendanbank/atrium-test-utils`.
 *
 * The widget calls `usePerm()` to gate the toggle on the
 * `hello.toggle` permission and reads `__atrium_t__('common.loading')`
 * for the spinner caption. Both come from atrium's host SDK; the
 * test installs the fakes once via `mockAtriumRegistry` and asserts
 * the gating + the translation without standing up the SPA.
 *
 * Note on the wrapping pattern: HelloWidget self-wraps in its own
 * `<MantineProvider><QueryClientProvider><AtriumProvider>` stack — the
 * canonical host-bundle shape, since the bundle has no enclosing
 * providers in production. The widget's inner `<AtriumProvider>` uses
 * the default fetch-based fetcher, so the test stubs
 * `/users/me/context` directly. The configured `me` from
 * `mockAtriumRegistry` reaches both the outer ``renderWithAtrium``
 * provider and (via the same fetch stub) the inner one, exactly the
 * way casa tests will end up structured.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { cleanup, screen, waitFor } from '@testing-library/react';

import {
  mockAtriumRegistry,
  renderWithAtrium,
  type MockAtriumHandles,
  type UserContext,
} from '@brendanbank/atrium-test-utils';

import { HelloWidget } from '../HelloWidget';
import { queryClient } from '../queryClient';

const ALICE_OWNER: UserContext = {
  id: 1,
  email: 'alice@example.com',
  full_name: 'Alice',
  is_active: true,
  roles: ['admin'],
  permissions: ['hello.toggle'],
  impersonating_from: null,
};

const BOB_VIEWER: UserContext = {
  id: 2,
  email: 'bob@example.com',
  full_name: 'Bob',
  is_active: true,
  roles: [],
  permissions: [],
  impersonating_from: null,
};

let handles: MockAtriumHandles;
let currentMe: UserContext | null = null;

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/users/me/context')) {
        if (!currentMe) return new Response(null, { status: 401 });
        return new Response(JSON.stringify(currentMe), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/hello/state')) {
        return new Response(
          JSON.stringify({
            message: 'Hello, atrium!',
            counter: 3,
            enabled: false,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response('{}', { status: 200 });
    }),
  );
}

beforeEach(() => {
  stubFetch();
});

afterEach(() => {
  cleanup();
  handles?.cleanup();
  // The widget self-wraps in a module-singleton QueryClient (the
  // canonical host-bundle pattern), so clear it between tests
  // otherwise the previous test's `me` leaks via the cache.
  queryClient.clear();
  currentMe = null;
  vi.unstubAllGlobals();
});

describe('HelloWidget', () => {
  test('users with hello.toggle can flip the switch', async () => {
    currentMe = ALICE_OWNER;
    handles = mockAtriumRegistry({ me: ALICE_OWNER });
    renderWithAtrium(<HelloWidget />);
    const input = (await screen.findByTestId('hello-toggle')) as HTMLInputElement;
    await waitFor(() => expect(input).not.toBeDisabled());
    expect(screen.getByText('Increment counter')).toBeInTheDocument();
  });

  test('users without hello.toggle see the disabled label', async () => {
    currentMe = BOB_VIEWER;
    handles = mockAtriumRegistry({ me: BOB_VIEWER });
    renderWithAtrium(<HelloWidget />);
    const input = (await screen.findByTestId('hello-toggle')) as HTMLInputElement;
    await waitFor(() =>
      expect(screen.getByText(/admin only/)).toBeInTheDocument(),
    );
    expect(input).toBeDisabled();
  });
});
