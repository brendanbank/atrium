// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { expect, test } from '@playwright/test';

import { API_URL, loginAsSuperAdmin } from './helpers';

/**
 * RemindersAdmin (`/admin/reminders`) coverage. Reminder rules drive
 * host-app reminder scheduling — atrium ships the storage + admin UI;
 * the host registers anchors. This spec proves the CRUD surface works
 * end-to-end via the admin UI.
 */

const adminEmail = process.env.E2E_ADMIN_EMAIL;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const adminTotpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

const haveSmokeEnv = Boolean(adminEmail && adminPassword && adminTotpSecret);

test.skip(
  !haveSmokeEnv,
  'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD / E2E_ADMIN_TOTP_SECRET must be set (run via `make smoke`).',
);

test.describe('Reminders admin', () => {
  test.describe.configure({ mode: 'serial' });
  // Fail fast on broken UI — every step in this spec should resolve
  // in <2 s on a healthy stack; 10 s is plenty.
  test.describe.configure({ timeout: 10_000 });

  test('admin creates, edits, deactivates, and deletes a reminder rule', async ({
    page,
  }) => {
    await loginAsSuperAdmin(page);
    await page.goto('/admin/reminders');

    await expect(
      page.getByRole('heading', { name: /reminder rules/i }),
    ).toBeVisible();

    // ---- Create -----------------------------------------------------
    const ruleName = `E2E Reminder ${Date.now()}`;
    const renamed = `${ruleName} (renamed)`;

    // Open the create modal via the page-header button. Two
    // ``RuleFormModal`` components are mounted (one for create, one
    // for edit) but only opened={true} renders the dialog body.
    const newBtn = page.getByRole('button', { name: /^New reminder$/i });
    await expect(newBtn).toBeVisible();
    // ``getByRole('button', name)`` matches BOTH the page-header
    // button and the modal's submit "Save" button when the modal is
    // mounted (it isn't yet, but matchers race) — use ``.first()`` so
    // we click the page-header button only.
    await newBtn.click();
    const modal = page.getByRole('dialog');
    await expect(modal).toBeVisible();
    // Mantine renders required labels as "Name *". Match with an
    // optional-asterisk regex so the test isn't brittle to that
    // detail across Mantine versions.
    await modal.getByLabel(/^Name(\s*\*)?$/).fill(ruleName);
    // Pick the seeded ``invite`` template — every fresh atrium has it.
    await modal.getByLabel(/email template/i).click();
    await page.getByRole('option', { name: 'invite', exact: true }).click();
    await modal.getByLabel(/^Anchor(\s*\*)?$/).fill('e2e_anchor');
    await modal.getByLabel(/days offset/i).fill('-3');
    await modal.getByRole('button', { name: /^save$/i }).click();
    await expect(modal).toHaveCount(0);

    // Row appears in the table.
    const row = page.locator('tbody tr', { hasText: ruleName });
    await expect(row).toBeVisible();
    await expect(row).toContainText('invite');
    await expect(row).toContainText('e2e_anchor');
    await expect(row).toContainText('-3');
    await expect(row.getByText(/^active$/i)).toBeVisible();

    // ---- Edit (rename + flip active off) ----------------------------
    // The edit / delete ActionIcons in the row aren't aria-labeled —
    // anchor on row position. Two buttons: [0] edit, [1] delete.
    const rowButtons = row.getByRole('button');
    await rowButtons.nth(0).click();
    const editModal = page.getByRole('dialog');
    await expect(editModal).toBeVisible();
    await editModal.getByLabel(/^Name(\s*\*)?$/).fill(renamed);
    await editModal.getByLabel(/^Active$/).uncheck();
    await editModal.getByRole('button', { name: /^save$/i }).click();
    await expect(editModal).toHaveCount(0);

    const renamedRow = page.locator('tbody tr', { hasText: renamed });
    await expect(renamedRow).toBeVisible();
    await expect(renamedRow.getByText(/^inactive$/i)).toBeVisible();

    // Verify the API state matches what the UI shows.
    const listResp = await page.request.get(`${API_URL}/admin/reminder-rules`);
    const rules = (await listResp.json()) as Array<{
      name: string;
      template_key: string;
      anchor: string;
      days_offset: number;
      active: boolean;
    }>;
    const created = rules.find((r) => r.name === renamed);
    expect(created).toBeTruthy();
    expect(created!.template_key).toBe('invite');
    expect(created!.anchor).toBe('e2e_anchor');
    expect(created!.days_offset).toBe(-3);
    expect(created!.active).toBe(false);

    // ---- Delete -----------------------------------------------------
    await page.evaluate(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).confirm = () => true;
    });
    await renamedRow.getByRole('button').nth(1).click();
    await expect(
      page.locator('tbody tr', { hasText: renamed }),
    ).toHaveCount(0);
  });
});
