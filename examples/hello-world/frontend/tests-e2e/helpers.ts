// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/** Slim copy of the helpers atrium's frontend smoke uses, scoped to
 *  what the Hello World spec needs. Vendored rather than imported
 *  across project boundaries so Playwright's module resolver has all
 *  the npm deps in one ``node_modules`` tree (the example's
 *  ``examples/hello-world/frontend``).
 *
 *  Source of truth: ``frontend/tests-e2e/helpers.ts``. Keep these in
 *  rough parity if atrium's helpers grow new logic the example
 *  benefits from. */
import { randomBytes } from 'crypto';

import type { Page } from '@playwright/test';
import { generate as generateTOTP } from 'otplib';

export const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

// crypto-backed uniqueness for fixture data — keeps the email
// local-part unique across parallel runs without reaching for
// Math.random (flagged by js/insecure-randomness even in tests).
function uniqueSuffix(): string {
  return `${Date.now()}-${randomBytes(4).readUInt32BE(0)}`;
}

/** Log in via API as the smoke-seeded super_admin and pass the TOTP
 *  challenge. Mirrors the auth + verify shape atrium's smoke uses. */
export async function loginAsSuperAdmin(page: Page): Promise<void> {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  const totpSecret = process.env.E2E_ADMIN_TOTP_SECRET;
  if (!email || !password || !totpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
  const loginResp = await page.request.post(`${API_URL}/auth/jwt/login`, {
    form: { username: email, password },
  });
  if (!loginResp.ok() && loginResp.status() !== 204) {
    throw new Error(`login failed: ${loginResp.status()}`);
  }
  const code = await generateTOTP({ secret: totpSecret });
  const verifyResp = await page.request.post(`${API_URL}/auth/totp/verify`, {
    data: { code },
  });
  if (!verifyResp.ok() && verifyResp.status() !== 204) {
    throw new Error(
      `totp verify failed: ${verifyResp.status()} ${await verifyResp.text()}`,
    );
  }
  // Some Playwright versions keep the APIRequestContext jar separate
  // from the browser context; copy cookies over so navigation carries
  // the auth cookie.
  const cookies = await page.context().cookies();
  if (!cookies.some((c) => c.name === 'atrium_auth')) {
    const apiCookies = await page.request.storageState();
    await page.context().addCookies(apiCookies.cookies);
  }
  await page.goto('/');
}

/** Provision a fresh non-admin user (``user`` role only) via invite +
 *  accept + TOTP-confirm, leaving ``page`` logged in as that user
 *  with a full-2FA session. */
export async function loginAsUser(page: Page): Promise<void> {
  const adminEmail = process.env.E2E_ADMIN_EMAIL;
  const adminPassword = process.env.E2E_ADMIN_PASSWORD;
  const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;
  if (!adminEmail || !adminPassword || !adminTotpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
  const browserContext = page.context();
  const reqCtx = browserContext.request;

  // 1. Authenticate as admin so we can mint an invite.
  const adminLogin = await reqCtx.post(`${API_URL}/auth/jwt/login`, {
    form: { username: adminEmail, password: adminPassword },
  });
  if (!adminLogin.ok() && adminLogin.status() !== 204) {
    throw new Error(`admin login failed: ${adminLogin.status()}`);
  }
  const adminVerify = await reqCtx.post(`${API_URL}/auth/totp/verify`, {
    data: { code: await generateTOTP({ secret: adminTotpSecret }) },
  });
  if (!adminVerify.ok() && adminVerify.status() !== 204) {
    throw new Error(`admin totp verify failed: ${adminVerify.status()}`);
  }

  const email = `e2e-user-${uniqueSuffix()}@example.com`;
  const password = 'User-Pw-12345!';
  const inviteResp = await reqCtx.post(`${API_URL}/invites`, {
    data: { email, full_name: 'E2E User', role_codes: ['user'] },
  });
  if (inviteResp.status() !== 201) {
    throw new Error(
      `invite create failed: ${inviteResp.status()} ${await inviteResp.text()}`,
    );
  }
  const invite = (await inviteResp.json()) as { token: string };

  // 2. Drop admin cookies, accept invite as the new user.
  await browserContext.clearCookies();
  const acceptResp = await reqCtx.post(`${API_URL}/invites/accept`, {
    data: { token: invite.token, password },
  });
  if (!acceptResp.ok() && acceptResp.status() !== 204) {
    throw new Error(
      `invite accept failed: ${acceptResp.status()} ${await acceptResp.text()}`,
    );
  }

  // 3. Log in + enrol TOTP + confirm to flip totp_passed=True.
  const userLogin = await reqCtx.post(`${API_URL}/auth/jwt/login`, {
    form: { username: email, password },
  });
  if (!userLogin.ok() && userLogin.status() !== 204) {
    throw new Error(`user login failed: ${userLogin.status()}`);
  }
  const setupResp = await reqCtx.post(`${API_URL}/auth/totp/setup`);
  if (!setupResp.ok()) {
    throw new Error(
      `totp setup failed: ${setupResp.status()} ${await setupResp.text()}`,
    );
  }
  const { secret } = (await setupResp.json()) as { secret: string };
  const confirmResp = await reqCtx.post(`${API_URL}/auth/totp/confirm`, {
    data: { code: await generateTOTP({ secret }) },
  });
  if (!confirmResp.ok() && confirmResp.status() !== 204) {
    throw new Error(
      `totp confirm failed: ${confirmResp.status()} ${await confirmResp.text()}`,
    );
  }

  const cookies = await browserContext.cookies();
  if (!cookies.some((c) => c.name === 'atrium_auth')) {
    const apiCookies = await reqCtx.storageState();
    await browserContext.addCookies(apiCookies.cookies);
  }
  await page.goto('/');
}
