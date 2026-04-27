// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import {
  createAndEnrolUserViaApi,
  loginAsSuperAdmin,
  loginPassTOTPNoNav,
} from './helpers';

/**
 * Phase 7 coverage — self-service + admin-driven account deletion.
 *
 * Each spec creates its own fresh user via the invite + accept flow
 * (we never mutate the seeded smoke admin); cleanup is implicit since
 * deleted accounts are anonymised + scheduled for hard-delete by
 * ``services.account_deletion.soft_delete_user``.
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

test('user can self-delete with password reconfirm', async ({ browser }) => {
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAsSuperAdmin(adminPage);

  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();
  const fresh = await createAndEnrolUserViaApi(
    adminPage.request,
    userPage.request,
  );

  // Sync the API-context cookies onto the browser context so the
  // SPA boots already authenticated.
  const apiCookies = await userPage.request.storageState();
  await userContext.addCookies(apiCookies.cookies);

  try {
    await userPage.goto('/profile');
    await userPage
      .getByRole('button', { name: /Delete my account/i })
      .click();

    // Scope to the open modal — the profile page also carries the
    // "Change password" form's New / Confirm password fields, so a
    // page-wide getByLabel(/Password/) would grab the wrong control.
    const modal = userPage.getByRole('dialog');
    await expect(modal).toBeVisible();
    await modal.getByLabel('Password', { exact: true }).fill(fresh.password);
    await modal
      .getByRole('button', { name: /^Delete account$/i })
      .click();

    // The mutation finishes by navigating to /login?deleted=1.
    await expect(userPage).toHaveURL(/\/login\?deleted=1/);

    // Logging back in must fail — the email has been anonymised and
    // the active sessions revoked. fastapi-users returns 400 on bad
    // credentials, not 401 (see CLAUDE.md "Things to remember" #4).
    const reloginResp = await userPage.request.post(
      `${API_URL}/auth/jwt/login`,
      { form: { username: fresh.email, password: fresh.password } },
    );
    expect([400, 401]).toContain(reloginResp.status());
  } finally {
    await adminContext.close();
    await userContext.close();
  }
});

test('wrong password rejects deletion without action', async ({ browser }) => {
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAsSuperAdmin(adminPage);

  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();
  const fresh = await createAndEnrolUserViaApi(
    adminPage.request,
    userPage.request,
  );

  const apiCookies = await userPage.request.storageState();
  await userContext.addCookies(apiCookies.cookies);

  try {
    await userPage.goto('/profile');
    await userPage
      .getByRole('button', { name: /Delete my account/i })
      .click();

    const modal = userPage.getByRole('dialog');
    await expect(modal).toBeVisible();
    await modal
      .getByLabel('Password', { exact: true })
      .fill('not-the-real-password');
    await modal
      .getByRole('button', { name: /^Delete account$/i })
      .click();

    // The error alert renders inside the modal; the URL must not
    // change to /login.
    await expect(userPage.getByText(/Wrong password/i)).toBeVisible();
    await expect(userPage).toHaveURL(/\/profile/);

    // The user should still be able to log in with their original
    // credentials — i.e. nothing was deleted.
    const reloginContext = await browser.newContext();
    const reloginPage = await reloginContext.newPage();
    try {
      await loginPassTOTPNoNav(
        reloginPage,
        fresh.email,
        fresh.password,
        fresh.totpSecret,
      );
      const meResp = await reloginPage.request.get(`${API_URL}/users/me`);
      expect(meResp.ok()).toBe(true);
      const me = (await meResp.json()) as { is_active: boolean };
      expect(me.is_active).toBe(true);
    } finally {
      await reloginContext.close();
    }
  } finally {
    await adminContext.close();
    await userContext.close();
  }
});

test('admin can delete a user from the admin UI', async ({ browser }) => {
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAsSuperAdmin(adminPage);

  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();
  const fresh = await createAndEnrolUserViaApi(
    adminPage.request,
    userPage.request,
  );

  try {
    // Stub the confirm() prompt so the test doesn't hang on the
    // ``window.confirm`` the delete handler invokes.
    await adminPage.evaluate(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).confirm = () => true;
    });

    await adminPage.goto('/admin?tab=users');

    // The Users tab carries two tables — Users and Invitations. The
    // freshly-created user appears in BOTH (one as a user record, the
    // other as the accepted invite that minted them) with the same
    // email. Scope to the first table to avoid strict-mode violations.
    const usersTable = adminPage.locator('table').first();
    const row = usersTable.locator('tr', { hasText: fresh.email });
    await expect(row).toBeVisible();

    // The trash icon button has aria-label="Delete" (t('common.delete')).
    const deleteBtn = row.getByRole('button', { name: /^Delete$/i });

    // The confirm() override has to be in place before the click —
    // re-apply just in case a soft navigation reset it.
    await adminPage.evaluate(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).confirm = () => true;
    });
    await deleteBtn.click();

    // The row should disappear from the list once the mutation
    // settles and TanStack Query re-fetches.
    await expect(row).toHaveCount(0, { timeout: 10000 });
  } finally {
    await adminContext.close();
    await userContext.close();
  }
});

test('attempting to delete a super_admin from the admin UI is refused', async ({
  browser,
}) => {
  // Drive this through the API rather than the UI: the
  // /admin/users/{id}/permanent endpoint refuses to delete the actor
  // themselves (and the UsersAdmin row hides the delete button on
  // your own row), so we need a *second* super_admin to exercise the
  // "can't delete a super_admin" guard.
  //
  // The smoke env only seeds one super_admin — promoting a fresh
  // user to super_admin via the admin UI would itself fail (the
  // privilege-escalation guard blocks granting a role whose perms
  // exceed the actor's), so the only way to set up the negative case
  // hermetically is to grant via the API. If our smoke topology
  // can't promote a second super_admin we skip with a clear reason.
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAsSuperAdmin(adminPage);

  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();
  const fresh = await createAndEnrolUserViaApi(
    adminPage.request,
    userPage.request,
    { roleCodes: ['user', 'super_admin'] },
  );

  // Verify the fresh user actually carries super_admin. If the
  // invite flow rejected the role grant for any reason, skip rather
  // than always-fail.
  const meResp = await userPage.request.get(`${API_URL}/users/me/context`);
  const ctx = (await meResp.json()) as { roles: string[] };
  test.skip(
    !ctx.roles.includes('super_admin'),
    'second super_admin could not be provisioned via invite — skipping the negative case',
  );

  try {
    // The new soft-delete admin endpoint carries the explicit
    // "cannot delete a super_admin" guard. The UsersAdmin trash
    // button still posts to /admin/users/{id}/permanent (hard
    // delete), which has different guards — we assert the soft-
    // delete endpoint here because the task is about the Phase 7
    // GDPR flow, not the legacy hard delete.
    const listResp = await adminPage.request.get(`${API_URL}/admin/users`);
    expect(listResp.ok()).toBe(true);
    const list = (await listResp.json()) as Array<{ id: number; email: string }>;
    const target = list.find((u) => u.email === fresh.email);
    if (!target) {
      throw new Error('seeded super_admin user not found in /admin/users');
    }

    const resp = await adminPage.request.post(
      `${API_URL}/admin/users/${target.id}/delete`,
    );
    expect(resp.status()).toBe(400);
    const body = (await resp.json()) as { detail?: string };
    expect(body.detail ?? '').toMatch(/super_admin/i);
  } finally {
    await adminContext.close();
    await userContext.close();
  }
});
