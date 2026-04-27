// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import type { APIRequestContext } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { API_URL, loginAsAdmin } from './helpers';

/** Local helper — the shared ``setSystemConfig`` predates this branch
 *  and types its patch tightly. We need to set ``host_bundle_url``,
 *  which the shared signature doesn't accept yet, so this spec drives
 *  the PUT inline. */
async function patchSystem(
  request: APIRequestContext,
  patch: Record<string, unknown>,
): Promise<void> {
  const cur = await request.get(`${API_URL}/admin/app-config`);
  if (!cur.ok()) {
    throw new Error(
      `admin app-config read failed: ${cur.status()} ${await cur.text()}`,
    );
  }
  const body = (await cur.json()) as { system?: Record<string, unknown> };
  const merged = { ...(body.system ?? {}), ...patch };
  const resp = await request.put(`${API_URL}/admin/app-config/system`, {
    data: merged,
  });
  if (!resp.ok()) {
    throw new Error(
      `system put failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

/**
 * B1 verification — every host-extension registry slot reaches its
 * consumer. Covers home widgets, routes, nav items, and admin tabs.
 *
 * Setup is contained to two tweaks:
 *   1. PUT ``system.host_bundle_url`` to a synthetic same-origin path.
 *   2. ``page.route`` fulfils that path with a tiny ES module that
 *      calls ``window.__ATRIUM_REGISTRY__`` for one of each kind.
 *
 * The bundle relies on ``window.React`` — main.tsx pins React onto
 * the global so externalised host bundles can call ``createElement``
 * without re-bundling React. The test exercises that contract too.
 *
 * Restores ``system.host_bundle_url`` to null in afterAll so a stuck
 * URL doesn't bleed into other specs.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const TEST_BUNDLE_PATH = '/__test_host_bundle.js';

const TEST_BUNDLE_SOURCE = `
const reg = window.__ATRIUM_REGISTRY__;
const R = window.React;
if (reg && R) {
  reg.registerHomeWidget({
    key: 'test-home-widget',
    render: () =>
      R.createElement('div', { 'data-testid': 'host-home-widget' },
        'host-widget-marker'),
  });
  reg.registerRoute({
    key: 'test-route',
    path: '/__test_route',
    element: R.createElement('div', { 'data-testid': 'host-route' },
      'host-route-marker'),
  });
  reg.registerNavItem({
    key: 'test-nav',
    label: 'host-nav-marker',
    to: '/__test_route',
  });
  reg.registerAdminTab({
    key: 'test-admin-tab',
    label: 'host-admin-marker',
    element: R.createElement('div', { 'data-testid': 'host-admin-tab' },
      'host-admin-tab-marker'),
  });
}
`;

test.describe('host-bundle slot system', () => {
  test.skip(
    !adminEmail || !adminPassword || !adminTotpSecret,
    'E2E_ADMIN_* env vars not set; run via `make smoke`.',
  );

  test.afterAll(async ({ request }) => {
    const loginResp = await request.post(`${API_URL}/auth/jwt/login`, {
      form: { username: adminEmail!, password: adminPassword! },
    });
    if (!loginResp.ok() && loginResp.status() !== 204) return;
    const { generate } = await import('otplib');
    const code = await generate({ secret: adminTotpSecret! });
    await request.post(`${API_URL}/auth/totp/verify`, { data: { code } });
    await patchSystem(request, { host_bundle_url: null });
  });

  test('all four registry kinds reach their consumer', async ({ page }) => {
    await loginAsAdmin(page);
    await patchSystem(page.request, { host_bundle_url: TEST_BUNDLE_PATH });

    await page.route(`**${TEST_BUNDLE_PATH}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: TEST_BUNDLE_SOURCE,
      });
    });

    await page.goto('/');

    // 1. Home widget rendered on /.
    await expect(page.getByTestId('host-home-widget')).toBeVisible({
      timeout: 10_000,
    });

    // 2. Nav item appears in the sidebar (visible on widescreen
    // viewports; mobile drawer would need a Burger click first).
    await expect(
      page.getByRole('link', { name: 'host-nav-marker' }),
    ).toBeVisible();

    // 3. Visiting the registered route renders the registered element.
    await page.goto('/__test_route');
    await expect(page.getByTestId('host-route')).toBeVisible();

    // 4. Admin tab appears on /admin and renders its panel content.
    await page.goto('/admin');
    const adminTab = page.getByRole('tab', { name: 'host-admin-marker' });
    await expect(adminTab).toBeVisible();
    await adminTab.click();
    await expect(page.getByTestId('host-admin-tab')).toBeVisible();
  });
});
