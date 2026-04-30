// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import {
  API_URL,
  createAndEnrolUserViaApi,
  loginAsSuperAdmin,
} from './helpers';

/**
 * AuditAdmin (`/admin/audit`) coverage. The audit *write* paths are
 * exercised everywhere — every admin mutation lands a row. This spec
 * proves the read UI: rows render, the entity filter narrows the
 * query, and clicking a row with a diff expands the JSON.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(adminEmail && adminPassword && adminTotpSecret);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

test.describe('Audit admin', () => {
  test.describe.configure({ mode: 'serial' });

  test('admin can view + filter the activity log', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    // Generate a known audit row: provisioning a fresh user via the
    // invite flow writes ``user`` + ``invite`` rows we can grep for.
    const userContext = await browser.newContext();
    await createAndEnrolUserViaApi(adminPage.request, userContext.request);
    await userContext.close();

    try {
      await adminPage.goto('/admin/audit');
      await expect(
        adminPage.getByRole('heading', { name: /activity log/i }),
      ).toBeVisible();

      // Fresh deployment has at least the seed rows (e.g. role
      // assignments, invite creates) plus the user we just provisioned
      // — the empty-state copy should not be visible.
      await expect(adminPage.getByText(/no activity recorded/i)).toHaveCount(
        0,
      );

      // Filter to ``user`` entity. The endpoint hits
      // /admin/audit?entity=user; assert via the API that the
      // result set is non-empty and every entry's entity matches.
      await adminPage
        .getByPlaceholder(/filter by entity/i)
        .fill('user');

      await expect
        .poll(async () => {
          const resp = await adminPage.request.get(
            `${API_URL}/admin/audit?entity=user&limit=10`,
          );
          if (!resp.ok()) return null;
          const body = (await resp.json()) as {
            items: Array<{ entity: string }>;
          };
          return body.items.length > 0 &&
            body.items.every((it) => it.entity === 'user');
        })
        .toBe(true);

      // The visible table now only contains ``user`` rows. Pick any
      // visible row and verify the entity column carries the prefix.
      const firstRow = adminPage.locator('tbody tr').first();
      await expect(firstRow).toContainText(/user #\d+/);
    } finally {
      await adminContext.close();
    }
  });

  test('admin can expand a row to inspect the JSON diff', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    // Trigger an admin write that lands an audit row with a non-null
    // diff: PUT brand config with a known field.
    const probe = `audit-spec-${Date.now()}`;
    const cur = await adminPage.request.get(`${API_URL}/admin/app-config`);
    const curBody = (await cur.json()) as { brand?: Record<string, unknown> };
    await adminPage.request.put(`${API_URL}/admin/app-config/brand`, {
      data: { ...(curBody.brand ?? {}), name: probe },
    });

    try {
      await adminPage.goto('/admin/audit');
      // Filter to app_setting so the freshly-written row floats up.
      await adminPage
        .getByPlaceholder(/filter by entity/i)
        .fill('app_setting');

      // Wait for at least one row to land in the filtered view.
      const firstRow = adminPage.locator('tbody tr').first();
      await expect(firstRow).toBeVisible();
      await expect(firstRow).toContainText(/app_setting/);

      // Click the row — it has a diff so the chevron expands and the
      // JSON renders in a follow-on <tr>.
      await firstRow.click();
      // The expanded row carries the namespace + fields the PUT
      // touched.
      await expect(
        adminPage.locator('tbody').getByText(/"namespace":\s*"brand"/),
      ).toBeVisible();
    } finally {
      // Restore brand defaults so we don't leak the probe name into
      // the next spec.
      await adminPage.request.put(`${API_URL}/admin/app-config/brand`, {
        data: {
          name: 'Atrium',
          logo_url: '/logo.svg',
          support_email: null,
          preset: 'default',
          overrides: {},
        },
      });
      await adminContext.close();
    }
  });
});
