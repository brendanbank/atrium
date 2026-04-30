// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import {
  createAndEnrolUserViaApi,
  loginAndPassTOTP,
  loginAsSuperAdmin,
  loginPassTOTPNoNav,
  setSystemConfig,
} from './helpers';

/**
 * Phase 5 coverage — maintenance mode + announcement banner.
 *
 * Setup / teardown of the ``system`` namespace happens through the
 * admin API (we don't drive the SystemAdmin form for state we aren't
 * actively asserting on); the assertions themselves go through the
 * browser so the rendered MaintenancePage / AnnouncementBanner is
 * actually exercised.
 *
 * Each spec leaves the ``system`` namespace in its starting shape
 * regardless of pass / fail — see the ``finally`` blocks.
 *
 * Required env (set by ``make smoke-up``):
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

test.beforeAll(() => {
  if (!adminEmail || !adminPassword || !adminTotpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD and E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
});

test('super_admin can flip maintenance mode and a regular user sees the maintenance page', async ({
  browser,
}) => {
  // ---- Super-admin context: flip maintenance on via the admin API.
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAsSuperAdmin(adminPage);

  // ---- Regular-user context: invite + accept a fresh ``user`` who
  // has no super_admin powers, so the middleware blocks them.
  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();
  // We only need the cookie state on userPage.request — the credentials
  // themselves aren't asserted on, so the return value is discarded.
  await createAndEnrolUserViaApi(adminPage.request, userPage.request);

  try {
    await setSystemConfig(adminPage.request, {
      maintenance_mode: true,
      maintenance_message:
        'Scheduled maintenance — back in a few minutes.',
    });

    // The middleware caches the flag for ~2s; wait for the cache to
    // expire by polling /users/me until it stops 503-ing OR the
    // regular-user request 503s. We don't sleep — we hit the API.
    await expect
      .poll(
        async () => {
          const resp = await userPage.request.get(
            `${process.env.E2E_API_URL ?? 'http://localhost:8000/api'}/notifications`,
          );
          return resp.status();
        },
        {
          message: 'maintenance flag should propagate to a regular user',
          timeout: 10000,
        },
      )
      .toBe(503);

    // Sync cookies onto the browser context so the navigation lands
    // authenticated, then navigate. The ``/users/me`` probe is on
    // the bypass list; the SPA will boot, read app-config, and swap
    // in the MaintenancePage for non-super_admin users.
    const apiCookies = await userPage.request.storageState();
    await userContext.addCookies(apiCookies.cookies);
    await userPage.goto('/');

    await expect(
      userPage.getByRole('heading', { name: /offline for maintenance/i }),
    ).toBeVisible();
    await expect(
      userPage.getByText(/back in a few minutes/i),
    ).toBeVisible();

    // The super-admin tab should still load /admin normally — they
    // bypass the gate.
    await adminPage.goto('/admin');
    await expect(adminPage).toHaveURL(/\/admin/);
    await expect(
      adminPage.getByRole('heading', { name: /offline for maintenance/i }),
    ).toHaveCount(0);
  } finally {
    await setSystemConfig(adminPage.request, {
      maintenance_mode: false,
    });
    await adminContext.close();
    await userContext.close();
  }
});

test('announcement banner renders with the configured severity colour', async ({
  page,
}) => {
  await loginAsSuperAdmin(page);

  try {
    await setSystemConfig(page.request, {
      announcement: 'Migration tonight',
      announcement_level: 'warning',
    });

    await page.goto('/');

    // The banner is rendered as a Mantine ``Alert`` (role=alert) above
    // the AppShell. Mantine writes the level colour onto a CSS
    // variable on the alert element — in the warning case that's the
    // yellow palette.
    const alert = page.getByRole('alert').filter({ hasText: 'Migration tonight' });
    await expect(alert).toBeVisible();

    // The component carries the announcement level on ``data-level``
    // — see the comment in AnnouncementBanner.tsx for why we don't
    // assert against the computed CSS variable.
    await expect(alert).toHaveAttribute('data-level', 'warning');
  } finally {
    await setSystemConfig(page.request, { announcement: null });
  }
});

test('login still works during maintenance for super_admin', async ({
  browser,
}) => {
  // Use a dedicated context so we control the cookie state between
  // the maintenance-on flip and the fresh login.
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAsSuperAdmin(adminPage);

  try {
    await setSystemConfig(adminPage.request, { maintenance_mode: true });

    // Drop the auth cookie. ``POST /auth/jwt/logout`` is on the
    // maintenance bypass list, so this still succeeds.
    const logoutResp = await adminPage.request.post(
      `${process.env.E2E_API_URL ?? 'http://localhost:8000/api'}/auth/jwt/logout`,
    );
    expect([200, 204].includes(logoutResp.status())).toBe(true);
    await adminContext.clearCookies();

    // Fresh login on a brand-new context — the bypass list (login +
    // totp/verify + users/me/context) keeps the auth flow reachable
    // even with the gate on.
    const freshContext = await browser.newContext();
    const freshPage = await freshContext.newPage();
    try {
      await loginAndPassTOTP(
        freshPage,
        adminEmail!,
        adminPassword!,
        adminTotpSecret!,
      );
      await freshPage.goto('/admin');
      await expect(freshPage).toHaveURL(/\/admin/);
      // Super_admins bypass the gate, so they see the admin shell —
      // not the maintenance page.
      await expect(
        freshPage.getByRole('heading', { name: /offline for maintenance/i }),
      ).toHaveCount(0);
    } finally {
      await freshContext.close();
    }

    // Re-establish an admin session to flip maintenance back off.
    const teardownContext = await browser.newContext();
    const teardownPage = await teardownContext.newPage();
    try {
      await loginPassTOTPNoNav(
        teardownPage,
        adminEmail!,
        adminPassword!,
        adminTotpSecret!,
      );
      await setSystemConfig(teardownPage.request, {
        maintenance_mode: false,
      });
    } finally {
      await teardownContext.close();
    }
  } finally {
    await adminContext.close();
  }
});
