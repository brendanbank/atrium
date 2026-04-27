// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import { loginAndPassTOTP } from './helpers';

/**
 * End-to-end coverage for logout. We verify the *effect* (auth-cookie
 * cleared, protected routes bounced to /login) rather than driving the
 * avatar-menu trigger, which has no stable accessible name. The hook
 * the UI button calls — ``POST /auth/jwt/logout`` — is exercised
 * directly from the page's APIRequestContext, so the same code path a
 * real click would take is what's under test.
 *
 * Required env (set by ``make smoke-up``):
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET
 */

const email = process.env.E2E_ADMIN_EMAIL;
const password = process.env.E2E_ADMIN_PASSWORD;
const totpSecret = process.env.E2E_ADMIN_TOTP_SECRET;
const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

test.beforeAll(() => {
  if (!email || !password || !totpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD and E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
});

test('logout drops the auth cookie and bounces protected routes', async ({
  page,
}) => {
  await loginAndPassTOTP(page, email!, password!, totpSecret!);
  await expect(page.getByRole('heading', { name: /Welcome/i })).toBeVisible();

  // While authenticated, the admin shell is reachable.
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/admin/);

  // Drive the same endpoint the UI Logout menu-item invokes.
  const logoutResp = await page.request.post(`${API_URL}/auth/jwt/logout`);
  expect([200, 204].includes(logoutResp.status())).toBe(true);

  // The atrium_auth cookie must be gone (or expired). Browsers vary
  // on whether a cleared cookie shows up; either case is acceptable.
  const cookies = await page.context().cookies();
  const auth = cookies.find((c) => c.name === 'atrium_auth');
  expect(auth === undefined || auth.value === '').toBe(true);

  // A fresh navigation to a protected route bounces straight to /login.
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/login/);
});
