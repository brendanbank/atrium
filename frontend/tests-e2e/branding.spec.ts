// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import {
  API_URL,
  loginAsAdmin,
  loginAsUser,
  resetBrandAndI18n,
  setBrandConfig,
} from './helpers';

/**
 * Phase 1 — Branding admin tab + theming. Covers:
 *
 *   1. An admin can rename the brand and the AppShell title picks the
 *      change up after a reload.
 *   2. Switching the theme preset to ``dark-glass`` flips the document
 *      colour scheme (visible via the ``data-mantine-color-scheme``
 *      attribute Mantine writes onto ``<html>``).
 *   3. A non-admin (``user`` role only — no ``app_setting.manage``)
 *      doesn't see the Branding tab on /admin.
 *
 * Each test snapshots the brand at start and restores it via the
 * admin API in afterAll, so reruns don't accumulate state.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

test.describe('Phase 1 — branding', () => {
  test.skip(
    !adminEmail || !adminPassword || !adminTotpSecret,
    'E2E_ADMIN_* env vars not set; run via `make smoke`.',
  );

  test.afterAll(async ({ request }) => {
    // Authenticate the request context so the reset PUT lands. The
    // per-test browser context is gone by now, so we drive the
    // top-level fixture-scoped APIRequestContext directly.
    const loginResp = await request.post(`${API_URL}/auth/jwt/login`, {
      form: { username: adminEmail!, password: adminPassword! },
    });
    if (!loginResp.ok() && loginResp.status() !== 204) return;
    // Generate a TOTP code via otplib — same approach helpers use.
    const { generate } = await import('otplib');
    const code = await generate({ secret: adminTotpSecret! });
    await request.post(`${API_URL}/auth/totp/verify`, { data: { code } });
    await resetBrandAndI18n(request);
  });

  test('admin can change brand name and see it in the header', async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto('/admin?tab=branding');

    const newName = `E2E Brand ${Date.now()}`;
    const nameInput = page.getByLabel(/Brand name|Merknaam/i).first();
    await expect(nameInput).toBeVisible();
    await nameInput.fill(newName);

    // Wait for the PUT to land before reloading; otherwise the next
    // /app-config GET races the save and the assertion flakes.
    const savePromise = page.waitForResponse(
      (resp) =>
        resp.url().endsWith('/admin/app-config/brand') &&
        resp.request().method() === 'PUT' &&
        resp.ok(),
    );
    await page.getByRole('button', { name: /^Save$|^Opslaan$/ }).click();
    await savePromise;

    await page.reload();
    // Header title is the AppShell <Title order={4}>{brand.name}</Title>.
    // Use ``getByRole('heading', { level: 4 })`` rather than a name
    // regex because the new value can be any string we passed in.
    const headerTitle = page.getByRole('heading', { level: 4 }).first();
    await expect(headerTitle).toHaveText(newName);
  });

  test('admin can switch theme preset and see the dark scheme apply', async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto('/admin?tab=branding');

    // Mantine renders Select as a combobox with the labelled trigger
    // exposing the current value. Click it, then click the option.
    const presetSelect = page
      .getByLabel(/Preset|Voorinstelling/i)
      .first();
    await presetSelect.click();
    await page.getByRole('option', { name: /Dark glass/i }).click();

    const savePromise = page.waitForResponse(
      (resp) =>
        resp.url().endsWith('/admin/app-config/brand') &&
        resp.request().method() === 'PUT' &&
        resp.ok(),
    );
    await page.getByRole('button', { name: /^Save$|^Opslaan$/ }).click();
    await savePromise;

    await page.reload();

    // Mantine writes ``data-mantine-color-scheme="dark"`` onto whichever
    // root element is closest to its provider — usually <html>, but
    // some configurations target <body>. Probe both rather than
    // hard-coding the element so a Mantine internal change can't
    // break this assertion silently. The ``dark-glass`` preset forces
    // dark via ``colorSchemeForPreset``.
    await expect
      .poll(async () => {
        return page.evaluate(() => {
          const html = document.documentElement.getAttribute(
            'data-mantine-color-scheme',
          );
          const body = document.body.getAttribute(
            'data-mantine-color-scheme',
          );
          return html ?? body;
        });
      })
      .toBe('dark');
  });

  test('non-admin does not see the Branding tab', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin');

    // The Users tab is universal — wait for it so we know the page
    // mounted before asserting the Branding tab is absent.
    await expect(
      page.getByRole('tab', { name: /Users|Gebruikers/i }),
    ).toBeVisible();
    await expect(
      page.getByRole('tab', { name: /Branding|Huisstijl/i }),
    ).toHaveCount(0);

    // Direct-URL access also falls through to the default tab — the
    // AdminPage validates ``?tab=branding`` against the user's perms.
    await page.goto('/admin?tab=branding');
    await expect(
      page.getByRole('tab', { name: /Users|Gebruikers/i }),
    ).toHaveAttribute('aria-selected', 'true');
  });
});

// Touch ``setBrandConfig`` so a future spec import doesn't error if
// the helper is renamed without updating callers — keeps the module
// graph honest.
void setBrandConfig;
