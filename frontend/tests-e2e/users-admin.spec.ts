// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { randomBytes } from 'crypto';

import { expect, test } from '@playwright/test';

import {
  API_URL,
  createAndEnrolUserViaApi,
  loginAsSuperAdmin,
  readLatestEmailLogEntry,
} from './helpers';

/**
 * UsersAdmin (`/admin/users`) coverage. Backend pytest already exercises
 * the underlying RBAC + impersonation routes; these specs prove the
 * admin UI's row actions wire to the right endpoints and the
 * impersonation banner appears + dismisses correctly.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(adminEmail && adminPassword && adminTotpSecret);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

function uniqueSuffix(): string {
  return `${Date.now()}-${randomBytes(4).readUInt32BE(0)}`;
}

/** Stub window.confirm so the row actions don't hang on the prompt. */
async function autoConfirm(page: import('@playwright/test').Page) {
  await page.evaluate(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).confirm = () => true;
  });
}

test.describe('Users admin', () => {
  test.describe.configure({ mode: 'serial' });

  test('admin edits a user name + email via the modal', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const targetContext = await browser.newContext();
    const fresh = await createAndEnrolUserViaApi(
      adminPage.request,
      targetContext.request,
    );
    await targetContext.close();

    try {
      await adminPage.goto('/admin/users');
      const usersTable = adminPage.locator('table').first();
      const row = usersTable.locator('tr', { hasText: fresh.email });
      await expect(row).toBeVisible();

      // Clicking the name (UnstyledButton wrapping the Text + pencil)
      // opens the edit modal. Use the pencil's aria-label as the
      // anchor — the wrapped text isn't a button role.
      await row.getByRole('button', { name: /edit/i }).first().click();

      const newName = `E2E Renamed ${uniqueSuffix()}`;
      const newEmail = `e2e-renamed-${uniqueSuffix()}@example.com`;
      const dialog = adminPage.getByRole('dialog');
      await dialog.getByLabel(/full name/i).fill(newName);
      await dialog.getByLabel(/email/i).fill(newEmail);
      await dialog.getByRole('button', { name: /save/i }).click();

      // Modal closes; row updates with the new name + email.
      await expect(dialog).toHaveCount(0);
      const newRow = usersTable.locator('tr', { hasText: newEmail });
      await expect(newRow).toBeVisible();
      await expect(newRow).toContainText(newName);
    } finally {
      await adminContext.close();
    }
  });

  test('admin assigns a role via the row MultiSelect', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const targetContext = await browser.newContext();
    const fresh = await createAndEnrolUserViaApi(
      adminPage.request,
      targetContext.request,
    );
    await targetContext.close();

    try {
      await adminPage.goto('/admin/users');
      const row = adminPage
        .locator('table')
        .first()
        .locator('tr', { hasText: fresh.email });
      await expect(row).toBeVisible();

      // The row's Roles cell carries a Mantine MultiSelect. The cell
      // contains both a visible combobox input and hidden value-tracker
      // inputs — anchor on the placeholder which is unique to the
      // visible combobox.
      await row.getByPlaceholder(/Pick roles/i).click();
      await adminPage.getByRole('option', { name: /^admin$/i }).click();
      // Click outside to close the dropdown.
      await adminPage.locator('body').click({ position: { x: 5, y: 5 } });

      // Confirm the change persisted by reading the user back.
      await expect
        .poll(async () => {
          const resp = await adminPage.request.get(`${API_URL}/admin/users`);
          const list = (await resp.json()) as Array<{
            id: number;
            email: string;
            roles: string[];
          }>;
          const me = list.find((u) => u.email === fresh.email);
          return me?.roles ?? [];
        })
        .toEqual(expect.arrayContaining(['admin', 'user']));
    } finally {
      await adminContext.close();
    }
  });

  test('admin triggers a password-reset email', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const targetContext = await browser.newContext();
    const fresh = await createAndEnrolUserViaApi(
      adminPage.request,
      targetContext.request,
    );
    await targetContext.close();

    try {
      await autoConfirm(adminPage);
      await adminPage.goto('/admin/users');
      await autoConfirm(adminPage);

      const row = adminPage
        .locator('table')
        .first()
        .locator('tr', { hasText: fresh.email });
      await row
        .getByRole('button', { name: /Send password reset/i })
        .click();

      // The success notification carries the i18n string; wait for it
      // before scraping the api logs (the email is enqueued + sent
      // synchronously by ``send_and_log``).
      await expect(
        adminPage.getByText(/password reset email sent/i),
      ).toBeVisible();

      // The console mail backend logs the sent email — verify the
      // recipient + template match.
      const entry = readLatestEmailLogEntry('password_reset', fresh.email);
      expect(entry.subject).toBeTruthy();
    } finally {
      await adminContext.close();
    }
  });

  test('admin resets a user 2FA enrollment', async ({ browser }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const targetContext = await browser.newContext();
    const fresh = await createAndEnrolUserViaApi(
      adminPage.request,
      targetContext.request,
    );
    await targetContext.close();

    try {
      await autoConfirm(adminPage);
      await adminPage.goto('/admin/users');
      await autoConfirm(adminPage);

      const row = adminPage
        .locator('table')
        .first()
        .locator('tr', { hasText: fresh.email });
      await row.getByRole('button', { name: /Reset 2FA/i }).click();

      await expect(
        adminPage.getByText(/2FA reset — user will re-enroll/i),
      ).toBeVisible();
    } finally {
      await adminContext.close();
    }
  });

  test('super_admin impersonates a user and exits via the banner', async ({
    browser,
  }) => {
    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await loginAsSuperAdmin(adminPage);

    const targetContext = await browser.newContext();
    const fresh = await createAndEnrolUserViaApi(
      adminPage.request,
      targetContext.request,
    );
    await targetContext.close();

    try {
      await autoConfirm(adminPage);
      await adminPage.goto('/admin/users');
      await autoConfirm(adminPage);

      const row = adminPage
        .locator('table')
        .first()
        .locator('tr', { hasText: fresh.email });
      await row.getByRole('button', { name: /^Impersonate$/i }).click();

      // The handler invalidates queries + navigates to /. The
      // ImpersonationBanner mounts with the target's full_name +
      // the original admin's full_name.
      await expect(adminPage).toHaveURL(/\/$/);
      // The "logged in as ..." phrase is unique to the banner — the
      // success toast just says "Now viewing as ...".
      const banner = adminPage.getByText(/logged in as Smoke Admin/i);
      await expect(banner).toBeVisible();

      // Verify server-side: /users/me/context now reports the target
      // identity with impersonating_from populated.
      const ctxResp = await adminPage.request.get(
        `${API_URL}/users/me/context`,
      );
      const ctx = (await ctxResp.json()) as {
        email: string;
        impersonating_from?: { email: string };
      };
      expect(ctx.email).toBe(fresh.email);
      expect(ctx.impersonating_from?.email).toBe(adminEmail);

      // Click the banner's Stop button — handler hits
      // /admin/impersonate/stop and invalidates queries.
      await adminPage
        .getByRole('button', { name: /^Stop$/i })
        .click();

      // Banner clears once /users/me re-fetches.
      await expect(
        adminPage.getByText(/logged in as Smoke Admin/i),
      ).toHaveCount(0);

      // /users/me/context now reports the admin again.
      const after = await adminPage.request.get(
        `${API_URL}/users/me/context`,
      );
      const restored = (await after.json()) as {
        email: string;
        impersonating_from?: unknown;
      };
      expect(restored.email).toBe(adminEmail);
      expect(restored.impersonating_from).toBeFalsy();
    } finally {
      await adminContext.close();
    }
  });
});
