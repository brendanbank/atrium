// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect } from '@playwright/test';

import { loginAndPassTOTP } from './helpers';

/**
 * End-to-end smoke: logs in as the seeded admin, clears the mandatory
 * TOTP challenge using the fixed smoke secret, and asserts the
 * authenticated home page renders. Deeper flows are covered by API
 * tests and Vitest; this one just proves the app boots in a real
 * browser against the real stack.
 *
 * Required env vars:
 *   E2E_ADMIN_EMAIL        — email of the seeded admin
 *   E2E_ADMIN_PASSWORD     — password for that account
 *   E2E_ADMIN_TOTP_SECRET  — base32 TOTP secret seeded on the user
 */

const email = process.env.E2E_ADMIN_EMAIL;
const password = process.env.E2E_ADMIN_PASSWORD;
const totpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

test.beforeAll(() => {
  if (!email || !password || !totpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD and E2E_ADMIN_TOTP_SECRET must be set to run the smoke test.',
    );
  }
});

test('user can log in and sees the home page', async ({ page }) => {
  await loginAndPassTOTP(page, email!, password!, totpSecret!);

  // Redirected to /, the welcome heading is visible.
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('heading', { name: /Welcome/i })).toBeVisible();

  // Sidebar exposes the main sections — proves the shell mounted.
  await expect(page.getByRole('link', { name: 'Profile' })).toBeVisible();
});
