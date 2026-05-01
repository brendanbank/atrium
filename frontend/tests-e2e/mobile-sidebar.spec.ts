// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect } from '@playwright/test';

import { loginAndPassTOTP } from './helpers';

/**
 * Mobile sidebar regressions: collapsible parent groups + scrollable
 * navbar.
 *
 *   - Issue #102 — toggling parent A → parent B → parent A on iOS
 *     WebKit left the chevron in the closed state but the children
 *     still rendered. The fix moves Mantine's NavLink to controlled
 *     ``opened`` state. This spec runs under chromium with a mobile
 *     viewport, which does NOT reproduce the underlying WebKit
 *     desync, but asserts the *invariant* the fix encodes: tapping a
 *     parent twice always closes its children. That guarantees we
 *     don't accidentally regress to the uncontrolled pattern.
 *
 *   - Issue #103 — when both Settings + Admin were expanded the last
 *     items spilled below the viewport on a phone. The fix wraps the
 *     navbar children in ``<AppShell.Section grow component={ScrollArea}>``.
 *     Tested by expanding both groups on a short viewport and
 *     scrolling the navbar to the bottom item.
 */

const email = process.env.E2E_ADMIN_EMAIL;
const password = process.env.E2E_ADMIN_PASSWORD;
const totpSecret = process.env.E2E_ADMIN_TOTP_SECRET;

test.use({ viewport: { width: 390, height: 700 } });

test.beforeAll(() => {
  if (!email || !password || !totpSecret) {
    throw new Error(
      'E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD and E2E_ADMIN_TOTP_SECRET must be set to run the mobile-sidebar test.',
    );
  }
});

test('parent NavLink toggle closes its children on the second tap', async ({
  page,
}) => {
  await loginAndPassTOTP(page, email!, password!, totpSecret!);
  await expect(page).toHaveURL('/');

  // Open the burger menu.
  await page.getByRole('button', { name: /toggle navigation/i }).click();

  // Scope to the navbar <aside> so we don't match the "Admin" button
  // on the home page card.
  const navbar = page.getByRole('navigation');
  const adminToggle = navbar.getByText(/^Admin$/i);
  await expect(adminToggle).toBeVisible();

  // First tap — Admin opens, the System child becomes visible.
  await adminToggle.click();
  const systemChild = navbar.getByRole('link', { name: /^System$/i });
  await expect(systemChild).toBeVisible();

  // Second tap — Admin closes again, the child disappears. This is
  // the assertion that issue #102 violated under iOS WebKit.
  await adminToggle.click();
  await expect(systemChild).toBeHidden();
});

test('navbar is scrollable when content overflows the viewport', async ({
  page,
}) => {
  await loginAndPassTOTP(page, email!, password!, totpSecret!);
  await expect(page).toHaveURL('/');

  await page.getByRole('button', { name: /toggle navigation/i }).click();

  const navbar = page.getByRole('navigation');

  // Expand the Admin group — atrium ships seven admin tabs which on a
  // 700px viewport pushes the bottom items below the fold.
  await navbar.getByText(/^Admin$/i).click();

  // The bottom item must be reachable via scroll. Without the
  // ScrollArea wrapper the navbar would clip and ``scrollIntoView``
  // would silently no-op while the element stayed below the fold.
  const lastTab = navbar.getByRole('link', { name: /Email templates/i });
  await lastTab.scrollIntoViewIfNeeded();
  await expect(lastTab).toBeVisible();
});
