// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for the admin-sections perm gating.
 *
 * Atrium's built-in admin tabs must hide for users who don't hold the
 * matching ``*.manage`` / ``audit.read`` permission, the same way
 * host-registered tabs are filtered via the ``perm`` field on
 * ``registerAdminTab``. Without gating, the SPA renders Users / Roles
 * / Reminders / Email Templates / etc. for non-admin viewers and they
 * get back-to-back 403s when those routes try to fetch — see #86.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { renderHook, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAdminSectionItems } from '@/admin/sections';
import { ME_QUERY_KEY } from '@/hooks/useAuth';
import type { CurrentUser } from '@/lib/auth';
import { __resetRegistryForTests } from '@/host/registry';

function makeUser(perms: string[]): CurrentUser {
  return {
    id: 1,
    email: 'u@example.com',
    full_name: 'U',
    is_active: true,
    is_verified: true,
    is_superuser: false,
    phone: null,
    preferred_language: 'en',
    roles: [],
    permissions: perms,
    impersonating_from: null,
  } as CurrentUser;
}

function withClient(user: CurrentUser | null) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  qc.setQueryData(ME_QUERY_KEY, user);
  // Wrapper component for renderHook.
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return wrapper;
}

function tabKeys(items: ReturnType<typeof useAdminSectionItems>): string[] {
  return items.map((i) => i.key);
}

describe('useAdminSectionItems — built-in tab perm gating (#86)', () => {
  beforeEach(() => {
    cleanup();
    __resetRegistryForTests();
  });

  it('hides every gated built-in tab from a user with no relevant perms', () => {
    // The "agent" persona from the bug report holds zero atrium-side
    // *.manage perms — the entire admin sidebar should be empty so
    // there's no link they can click that 403s.
    const { result } = renderHook(() => useAdminSectionItems(), {
      wrapper: withClient(makeUser([])),
    });
    expect(tabKeys(result.current)).toEqual([]);
  });

  it('shows the Users tab only when user.manage is held', () => {
    const without = renderHook(() => useAdminSectionItems(), {
      wrapper: withClient(makeUser([])),
    });
    expect(tabKeys(without.result.current)).not.toContain('users');
    cleanup();

    const withPerm = renderHook(() => useAdminSectionItems(), {
      wrapper: withClient(makeUser(['user.manage'])),
    });
    expect(tabKeys(withPerm.result.current)).toContain('users');
  });

  it('shows the Reminders tab only when reminder_rule.manage is held', () => {
    const without = renderHook(() => useAdminSectionItems(), {
      wrapper: withClient(makeUser([])),
    });
    expect(tabKeys(without.result.current)).not.toContain('reminders');
    cleanup();

    const withPerm = renderHook(() => useAdminSectionItems(), {
      wrapper: withClient(makeUser(['reminder_rule.manage'])),
    });
    expect(tabKeys(withPerm.result.current)).toContain('reminders');
  });

  it('shows the full set of built-ins to a user holding every relevant perm', () => {
    const allPerms = [
      'user.manage',
      'role.manage',
      'reminder_rule.manage',
      'email_template.manage',
      'email_outbox.manage',
      'app_setting.manage',
      'audit.read',
    ];
    const { result } = renderHook(() => useAdminSectionItems(), {
      wrapper: withClient(makeUser(allPerms)),
    });
    expect(tabKeys(result.current)).toEqual([
      'system',
      'auth',
      'users',
      'branding',
      'roles',
      'translations',
      'emails',
      'outbox',
      'reminders',
      'audit',
    ]);
  });

  it('does not regress existing gates (audit / roles / email templates / outbox / app config)', () => {
    // Each gate is wired to a single permission code — make sure the
    // tabs disappear independently when only one perm is missing. This
    // pins down the contract that future builds can't accidentally
    // collapse two gates onto the same perm.
    const cases: Array<{ tab: string; perm: string }> = [
      { tab: 'roles', perm: 'role.manage' },
      { tab: 'audit', perm: 'audit.read' },
      { tab: 'emails', perm: 'email_template.manage' },
      { tab: 'outbox', perm: 'email_outbox.manage' },
      { tab: 'system', perm: 'app_setting.manage' },
    ];
    for (const { tab, perm } of cases) {
      cleanup();
      const { result } = renderHook(() => useAdminSectionItems(), {
        wrapper: withClient(makeUser([perm])),
      });
      expect(tabKeys(result.current)).toContain(tab);
    }
  });
});
