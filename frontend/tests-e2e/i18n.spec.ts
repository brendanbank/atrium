// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import {
  API_URL,
  loginAsAdmin,
  loginAsUser,
  resetBrandAndI18n,
  setI18nConfig,
} from './helpers';

/**
 * Phase 9 — i18n + Translations admin tab. Covers:
 *
 *   1. The header language switcher exposes the locales declared in
 *      ``app-config.i18n.enabled_locales`` (default ``en`` + ``nl``).
 *   2. Selecting NL re-renders user-facing strings into Dutch.
 *   3. An admin can register an override for ``nav.home`` and the new
 *      string lands on the next page mount.
 *   4. A non-admin doesn't see the Translations tab.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

test.describe('Phase 9 — i18n', () => {
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
    await resetBrandAndI18n(request);
  });

  test('language switcher shows the enabled locales from app_config', async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto('/');

    // The Mantine Select in the header carries
    // ``aria-label={t('common.language')}`` — "Language" in EN, "Taal"
    // in NL. Mantine v9 attaches the same aria-label to both the
    // combobox input AND the listbox container; pick the input
    // explicitly via the ``combobox`` role.
    const langSelect = page.getByRole('combobox', { name: /Language|Taal/i });
    await expect(langSelect).toBeVisible();

    // The current displayed value is the upper-cased locale code.
    // Click to expand, then assert each enabled locale is offered.
    await langSelect.click();
    await expect(page.getByRole('option', { name: 'EN' })).toBeVisible();
    await expect(page.getByRole('option', { name: 'NL' })).toBeVisible();
  });

  test('switching language re-renders the UI', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/');

    // Confirm we start in EN — Profile button shows the EN string.
    await expect(
      page.getByRole('link', { name: /^Profile$/ }).first(),
    ).toBeVisible();

    // Switch to NL via the header Select. ``getByLabel`` matches
    // both the combobox input AND the listbox div in Mantine v9
    // (both carry aria-label); use the combobox role to be precise.
    const langSelect = page.getByRole('combobox', { name: /Language|Taal/i });
    await langSelect.click();
    await page.getByRole('option', { name: 'NL' }).click();

    // The home heading should now be Dutch ("Welkom" prefix). Use a
    // regex so the welcomeNamed variant ("Welkom, Smoke Admin") also
    // matches.
    await expect(
      page.getByRole('heading', { name: /Welkom/ }),
    ).toBeVisible();

    // And the Profile nav link in the sidebar swaps to "Profiel".
    await expect(
      page.getByRole('link', { name: /Profiel/ }).first(),
    ).toBeVisible();

    // i18next-browser-languagedetector persists the choice to
    // localStorage; switch back to EN so a sibling spec running
    // afterwards starts from a known baseline.
    await page
      .getByRole('combobox', { name: /Language|Taal/i })
      .click();
    await page.getByRole('option', { name: 'EN' }).click();
  });

  test('admin can add a translation override and see it after reload', async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto('/admin?tab=translations');

    // The TranslationsAdmin renders one row per i18n key. Filter by
    // ``nav.home`` so we don't hunt through ~150 rows. The TextInput
    // for the override lives in the third <td> of that row.
    const search = page.getByLabel(/^Key$|^Sleutel$/).first();
    await search.fill('nav.home');

    // Active locale must be EN — that's the default that the seeded
    // smoke admin lands in. (The active-locale Select is a separate
    // Mantine combobox; the default selection is the first enabled
    // entry, which is "en".)
    const overrideRow = page.locator('tr', { hasText: 'nav.home' });
    await expect(overrideRow).toBeVisible();
    const overrideInput = overrideRow.locator('input').last();
    await overrideInput.fill('Custom Home');

    const savePromise = page.waitForResponse(
      (resp) =>
        resp.url().endsWith('/admin/app-config/i18n') &&
        resp.request().method() === 'PUT' &&
        resp.ok(),
    );
    await page.getByRole('button', { name: /^Save$|^Opslaan$/ }).click();
    await savePromise;

    // Reload — the i18n bootstrap fetches /app-config and merges the
    // override into the EN bundle before the first render.
    await page.reload();
    await expect(
      page.getByRole('link', { name: 'Custom Home' }).first(),
    ).toBeVisible();
  });

  test('non-admin does not see the Translations tab', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin');

    await expect(
      page.getByRole('tab', { name: /Users|Gebruikers/i }),
    ).toBeVisible();
    await expect(
      page.getByRole('tab', { name: /Translations|Vertalingen/i }),
    ).toHaveCount(0);
  });
});

// Same trick as branding.spec — keep ``setI18nConfig`` referenced so
// later refactors don't drop it silently.
void setI18nConfig;
