// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { randomBytes } from 'crypto';

import { expect, test } from '@playwright/test';

import { API_URL, loginAsSuperAdmin } from './helpers';

/**
 * RolesAdmin (`/admin/roles`) coverage. Backend pytest already exercises
 * the underlying RBAC permission attach/detach + system-role guards;
 * this spec proves the admin UI's create / edit / delete actions wire
 * correctly and that system roles render as protected (no trash icon).
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(adminEmail && adminPassword && adminTotpSecret);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

function uniqueCode(): string {
  // Lowercase, underscores, digits — matches the role-code validator.
  return `e2e_role_${randomBytes(3).readUIntBE(0, 3)}`;
}

async function autoConfirm(page: import('@playwright/test').Page) {
  await page.evaluate(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).confirm = () => true;
  });
}

test.describe('Roles admin', () => {
  test.describe.configure({ mode: 'serial' });

  test('admin creates a role with permissions, edits it, deletes it', async ({
    page,
  }) => {
    await loginAsSuperAdmin(page);
    await page.goto('/admin/roles');

    // Wait for the existing system roles to render — at minimum
    // super_admin / admin / user should be visible from the migration
    // seed.
    const table = page.locator('table').first();
    await expect(table.getByText('Super admin')).toBeVisible();
    await expect(table.getByText(/^Admin$/)).toBeVisible();
    await expect(table.getByText(/^User$/)).toBeVisible();

    // ---- Create ------------------------------------------------------
    const code = uniqueCode();
    const initialName = `E2E Role ${code}`;
    const renamed = `Renamed ${code}`;

    await page.getByRole('button', { name: /new role/i }).click();

    const createDialog = page.getByRole('dialog');
    await createDialog.getByLabel(/^code/i).fill(code);
    await createDialog.getByLabel(/^name/i).fill(initialName);
    // Attach two permissions — pick two that always exist via the
    // 0001 seed: ``user.manage`` and ``audit.read``.
    await createDialog
      .getByRole('checkbox', { name: /user\.manage/ })
      .check();
    await createDialog
      .getByRole('checkbox', { name: /audit\.read/ })
      .check();
    await createDialog.getByRole('button', { name: /save/i }).click();

    // Modal closes, new row appears.
    await expect(createDialog).toHaveCount(0);
    const newRow = table.locator('tr', { hasText: initialName });
    await expect(newRow).toBeVisible();
    // No system badge on a fresh role — only seeded super_admin/admin/user
    // carry the badge.
    await expect(newRow.getByText(/^system$/)).toHaveCount(0);

    // ---- Edit (rename + toggle a permission off) ---------------------
    await newRow.getByRole('button', { name: initialName }).click();
    const editDialog = page.getByRole('dialog');
    await editDialog.getByLabel(/^name/i).fill(renamed);
    // Drop user.manage; keep audit.read so the role still has at least
    // one permission attached.
    await editDialog
      .getByRole('checkbox', { name: /user\.manage/ })
      .uncheck();
    await editDialog.getByRole('button', { name: /save/i }).click();
    await expect(editDialog).toHaveCount(0);

    // Row updates in place with the new label.
    const renamedRow = table.locator('tr', { hasText: renamed });
    await expect(renamedRow).toBeVisible();

    // Verify the API state matches what we set.
    const rolesResp = await page.request.get(`${API_URL}/admin/roles`);
    const roles = (await rolesResp.json()) as Array<{
      code: string;
      name: string;
      permissions: string[];
    }>;
    const created = roles.find((r) => r.code === code);
    expect(created).toBeTruthy();
    expect(created!.name).toBe(renamed);
    expect(created!.permissions).toEqual(['audit.read']);

    // ---- Delete ------------------------------------------------------
    await autoConfirm(page);
    await renamedRow
      .getByRole('button', { name: /delete/i })
      .click();

    // Row gone after the mutation lands.
    await expect(table.locator('tr', { hasText: renamed })).toHaveCount(0);
  });

  test('system roles cannot be deleted from the UI', async ({ page }) => {
    await loginAsSuperAdmin(page);
    await page.goto('/admin/roles');

    // Anchor each row by its role-name button (an exact-text Mantine
    // Button, unique per role) and walk to the enclosing <tr>. The
    // ``hasText`` filter on ``tr`` matches the whole row's text and
    // can't disambiguate "Admin" from "Super admin" with a regex.
    for (const exactName of ['Super admin', 'Admin', 'User']) {
      const nameButton = page.getByRole('button', { name: exactName, exact: true });
      await expect(nameButton).toBeVisible();
      const row = nameButton.locator('xpath=ancestor::tr[1]');
      // The trash button is conditionally rendered only for non-system
      // roles. Asserting count=0 proves the gate holds.
      await expect(row.getByRole('button', { name: /delete/i })).toHaveCount(
        0,
      );
      // The "system" badge confirms the row is the system row.
      await expect(row.getByText(/^system$/i)).toBeVisible();
    }
  });

  test('system role name field is read-only when editing', async ({
    page,
  }) => {
    await loginAsSuperAdmin(page);
    await page.goto('/admin/roles');

    // Open the ``admin`` system role's edit modal — anchor by exact
    // button text so we don't pick up "Super admin".
    await page.getByRole('button', { name: 'Admin', exact: true }).click();

    const dialog = page.getByRole('dialog');
    // The system-rename guard renders the name field disabled; the
    // explanatory description (``roles.systemRoleNoRename``) is
    // attached to the input.
    const nameInput = dialog.getByLabel(/^name/i);
    await expect(nameInput).toBeDisabled();
    await expect(
      dialog.getByText(/system roles can't be renamed/i),
    ).toBeVisible();

    // Cancel out — no changes.
    await dialog.getByRole('button', { name: /cancel/i }).click();
    await expect(dialog).toHaveCount(0);
  });
});
