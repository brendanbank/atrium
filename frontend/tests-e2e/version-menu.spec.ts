// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import { API_URL, loginAsSuperAdmin } from './helpers';

/**
 * The deployment's build stamps in the user menu.
 *
 * Two things this pins that the unit tests can't: the endpoint is
 * actually mounted (a router that isn't wired into ``create_app``
 * type-checks fine), and the stamp survives the image build — the
 * e2e stack builds the runtime target with the Makefile's git-derived
 * build args, so a broken ARG/ENV chain in the Dockerfile shows up
 * here as a missing line rather than in production.
 */

const haveSmokeEnv = Boolean(
  process.env.E2E_ADMIN_EMAIL &&
    process.env.E2E_ADMIN_PASSWORD &&
    process.env.E2E_ADMIN_TOTP_SECRET,
);

test.describe('Version in the user menu', () => {
  test.describe.configure({ timeout: 15_000 });

  test('the avatar menu names the atrium build', async ({ page }) => {
    test.skip(!haveSmokeEnv, 'Run via `make smoke-extended`.');
    await loginAsSuperAdmin(page);

    await page.getByTestId('user-menu').click();

    const versions = page.getByTestId('version-info');
    await expect(versions).toBeVisible();
    // Either a tag ("Atrium 0.29.1") or the short commit fallback —
    // which of the two depends on whether the build was tagged, and
    // that's exactly the behaviour under test, so match either.
    await expect(versions).toContainText(/Atrium\s+\S+/);

    // Above the account email, per the menu's information order:
    // deployment first, then the account.
    const dropdown = page.getByRole('menu');
    await expect(dropdown).toContainText(process.env.E2E_ADMIN_EMAIL!);
    const text = (await dropdown.textContent()) ?? '';
    expect(text.indexOf('Atrium')).toBeLessThan(
      text.indexOf(process.env.E2E_ADMIN_EMAIL!),
    );
  });

  test('an anonymous caller cannot read the version', async ({ request }) => {
    // Issue #179's argument applied to this endpoint: a version string
    // handed to an unauthenticated scanner is free CVE matching.
    const r = await request.get(`${API_URL}/version`);
    expect([401, 403]).toContain(r.status());
  });
});
