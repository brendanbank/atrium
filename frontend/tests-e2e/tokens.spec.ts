// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Phase 3 PATs — UI smoke for the create / reveal / revoke loop.
 *
 * The load-bearing assertion is end-to-end: a token created via the
 * UI works as an Authorization: Bearer credential against a real
 * endpoint, and stops working as soon as the UI revokes it. The
 * frontend code paths covered are:
 *
 *  - `/profile/tokens` route renders + lists empty
 *  - TokenCreateModal submit hands plaintext to TokenRevealModal
 *  - The plaintext is selectable and can be copied (here we read it
 *    from the readonly input value)
 *  - The freshly-created row appears in the table without a manual
 *    refetch
 *  - Revoke flips status to "revoked" and the row's revoke button
 *    disappears
 *  - The /admin/tokens admin tab renders the same row and (where the
 *    spec covers it) the audit drawer fetches without erroring
 *
 * Setup: enable ``pats`` (defaults to off) via the admin app-config
 * PUT. Teardown disables it again so subsequent specs that don't
 * expect PAT auth see the same starting state.
 */
import { expect, test } from '@playwright/test';

import { API_URL, loginAsSuperAdmin } from './helpers';

async function setPatsConfig(
  request: import('@playwright/test').APIRequestContext,
  patch: { enabled?: boolean },
): Promise<void> {
  const cur = await request.get(`${API_URL}/admin/app-config`);
  if (!cur.ok()) {
    throw new Error(
      `app-config read failed: ${cur.status()} ${await cur.text()}`,
    );
  }
  const body = (await cur.json()) as { pats?: Record<string, unknown> };
  const merged = { ...(body.pats ?? {}), ...patch };
  const resp = await request.put(`${API_URL}/admin/app-config/pats`, {
    data: merged,
  });
  if (!resp.ok()) {
    throw new Error(`pats put failed: ${resp.status()} ${await resp.text()}`);
  }
}

test.describe('Personal Access Tokens — profile + admin', () => {
  test.describe.configure({ timeout: 30_000 });

  test('create → use → revoke → use fails 401', async ({ page }) => {
    await loginAsSuperAdmin(page);
    await setPatsConfig(page.request, { enabled: true });

    try {
      await page.goto('/profile/tokens');
      // The page heading proves the route mounted; we anchor on it
      // before any interaction so a redirect to /login (smoke admin
      // missing perm) fails early with a clear error.
      await expect(
        page.getByRole('heading', { name: /personal access tokens/i }),
      ).toBeVisible();

      // ---- Create
      await page.getByTestId('token-create-open').click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();

      // Name field — Mantine renders required labels with " *" so
      // anchor on the testid we ship on the input.
      await dialog.getByTestId('token-create-name').fill('e2e bearer');

      // Scope picker — open the MultiSelect, click the option,
      // press Escape to close the dropdown. ``audit.read`` is a
      // permission the seeded super_admin holds, so the intersection
      // at auth time keeps it. Mantine's MultiSelect leaves the
      // dropdown open after pick (closeOnSelect defaults to false);
      // Escape closes the dropdown without dismissing the modal
      // (the modal's Escape handler runs in a parent overlay layer).
      await dialog.getByTestId('token-create-scopes').click();
      await page.getByRole('option', { name: 'audit.read' }).click();
      await page.keyboard.press('Escape');

      await dialog.getByTestId('token-create-submit').click();

      // ---- Reveal modal pops up; capture plaintext from the readonly
      // PasswordInput. The value lives in the ``value`` attribute so
      // we read it directly rather than relying on visible text (the
      // input is type=password by default until the user toggles).
      const revealInput = page.getByTestId('token-reveal-input');
      await expect(revealInput).toBeVisible();
      const plaintext = await revealInput.inputValue();
      expect(plaintext, 'plaintext token should be present').toMatch(
        /^atr_pat_/,
      );

      await page.getByTestId('token-reveal-dismiss').click();
      await expect(revealInput).toHaveCount(0);

      // ---- The new row should be listed.
      await expect(page.getByText('e2e bearer').first()).toBeVisible();
      const prefix = plaintext.slice(0, 12);
      await expect(
        page.getByText(`${prefix}…`).first(),
        'token prefix should be visible in the list',
      ).toBeVisible();

      // ---- Use the bearer token against a permission-gated endpoint.
      // ``/admin/audit`` requires ``audit.read`` (held by super_admin)
      // — the PAT carries it as a scope, so the intersection succeeds.
      // PAT middleware runs first in the auth chain, so the bearer
      // takes precedence even though the page context still carries
      // the admin cookie.
      const usedOk = await page.request.get(
        `${API_URL}/admin/audit?limit=1`,
        {
          headers: {
            Authorization: `Bearer ${plaintext}`,
          },
        },
      );
      expect(
        usedOk.status(),
        'bearer should authenticate while active',
      ).toBe(200);

      // ---- Revoke via UI. Find the row by its name button, then
      // walk to the row's revoke action.
      const row = page
        .getByTestId(/^token-row-\d+$/)
        .filter({ hasText: 'e2e bearer' });
      await expect(row).toBeVisible();
      // The revoke icon button has aria-label "Revoke"; click it then
      // confirm in the second-stage modal.
      await row.getByLabel('Revoke').click();
      const revokeDialog = page.getByRole('dialog').filter({
        hasText: /revoke "?e2e bearer"?/i,
      });
      await expect(revokeDialog).toBeVisible();
      await revokeDialog.getByTestId('token-revoke-submit').click();

      // The list refetch should drop the row's "Active" badge for a
      // "Revoked" badge. We anchor on the row itself.
      await expect(row.getByText(/^Revoked$/i)).toBeVisible();

      // ---- Re-use the same plaintext → 401 / token_revoked. The
      // middleware short-circuits before any cookie auth runs, so
      // even though the page context still has the admin cookie the
      // bearer's revoked status produces 401.
      const usedAfter = await page.request.get(
        `${API_URL}/admin/audit?limit=1`,
        {
          headers: {
            Authorization: `Bearer ${plaintext}`,
          },
        },
      );
      expect(
        usedAfter.status(),
        'bearer should fail after revoke',
      ).toBe(401);
    } finally {
      await setPatsConfig(page.request, { enabled: false });
    }
  });

  test('admin tokens tab lists tokens across users', async ({ page }) => {
    await loginAsSuperAdmin(page);
    await setPatsConfig(page.request, { enabled: true });

    try {
      // Mint a token via the API (faster than driving the full UI
      // again — this test is about the admin tab, not the create flow)
      // and then assert it shows up in /admin/tokens.
      const create = await page.request.post(`${API_URL}/auth/tokens`, {
        data: {
          name: 'admin-tab fixture',
          scopes: ['audit.read'],
          expires_in_days: 30,
        },
      });
      expect(create.status(), 'API create should return 201').toBe(201);

      await page.goto('/admin/tokens');
      await expect(
        page.getByRole('heading', { name: /personal access tokens/i }),
      ).toBeVisible();

      // The token row should be visible. The admin variant's table
      // adds a "User" column — the seeded admin's email is in the env.
      const adminEmail = process.env.E2E_ADMIN_EMAIL!;
      const row = page
        .getByTestId(/^token-row-\d+$/)
        .filter({ hasText: 'admin-tab fixture' });
      await expect(row).toBeVisible();
      await expect(row).toContainText(adminEmail);

      // The audit drawer fires a real GET against
      // /admin/auth/tokens/{id}/audit — clicking it should produce a
      // visible drawer with at least the create entry.
      await row.getByLabel('Audit trail').click();
      const drawer = page.getByRole('dialog').filter({
        hasText: /Audit trail/i,
      });
      await expect(drawer).toBeVisible();
      await expect(drawer.getByText('create').first()).toBeVisible();
    } finally {
      await setPatsConfig(page.request, { enabled: false });
    }
  });
});
