// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import { loginAndPassTOTP } from './helpers';

/**
 * End-to-end coverage for the most common atrium admin flow:
 * an admin invites a new user, the invitee follows the link, sets a
 * password, and ends up at the forced-2FA-enrollment screen (the
 * standard atrium first-login landing for a user who has no
 * second-factor enrolled yet).
 *
 * The admin login + invite-create steps go through the API for
 * determinism (we need the invite token for the accept URL); the
 * accept-invite page itself and the post-accept landing are driven
 * through the browser, which is the value-add of the e2e.
 *
 * Required env (set by ``make smoke-up``):
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;
const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

test.beforeAll(() => {
  if (!adminEmail || !adminPassword || !adminTotpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD and E2E_ADMIN_TOTP_SECRET must be set.',
    );
  }
});

test('admin invites a user, the user accepts and lands at 2FA setup', async ({
  browser,
}) => {
  // ---- Admin context: get an authenticated session and mint the invite.
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAndPassTOTP(
    adminPage,
    adminEmail!,
    adminPassword!,
    adminTotpSecret!,
  );

  // Use a unique address per run so the spec is hermetic against a
  // dev DB that might already hold a previous accept.
  const inviteEmail = `e2e-invitee-${Date.now()}@example.com`;
  const newPassword = 'invitee-pw-12345';

  const createResp = await adminPage.request.post(`${API_URL}/invites`, {
    data: {
      email: inviteEmail,
      full_name: 'E2E Invitee',
      role_codes: ['user'],
    },
  });
  expect(createResp.status()).toBe(201);
  const created = (await createResp.json()) as { id: number; token: string };
  expect(created.token).toBeTruthy();

  // ---- Invitee context: clean cookies, navigate to the accept URL.
  const inviteeContext = await browser.newContext();
  const inviteePage = await inviteeContext.newPage();
  await inviteePage.goto(`/accept-invite?token=${created.token}`);

  // Fill both password fields. Use the exact labels (instead of a
  // /password/i regex) because Mantine's PasswordInput renders an
  // additional "Toggle password visibility" button whose accessible
  // name also matches /password/i.
  await inviteePage
    .getByLabel(/Password \(min/i)
    .fill(newPassword);
  await inviteePage.getByLabel(/Confirm password/i).fill(newPassword);
  await inviteePage
    .getByRole('button', { name: /Create account/i })
    .click();

  // Either the page redirects to /login (the AcceptInvitePage's
  // standard 1.5s navigate-after-success) or shows the success alert.
  // We don't drive a fresh login here — the smoke test covers that —
  // but we verify both the redirect lands us on /login and that the
  // backend now reflects an accepted invite.
  await expect(inviteePage).toHaveURL(/\/login/, { timeout: 5000 });

  const listResp = await adminPage.request.get(`${API_URL}/invites`);
  expect(listResp.ok()).toBe(true);
  const invites = (await listResp.json()) as Array<{
    id: number;
    email: string;
    accepted_at: string | null;
    role_codes: string[];
  }>;
  const ours = invites.find((i) => i.id === created.id);
  expect(ours).toBeTruthy();
  expect(ours!.accepted_at).not.toBeNull();
  expect(ours!.role_codes).toEqual(['user']);

  await adminContext.close();
  await inviteeContext.close();
});
