// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Menu, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { formatComponentVersion, useVersionInfo } from '@/hooks/useVersion';

function Line({ text, commit }: { text: string | null; commit: string | null }) {
  if (!text) return null;
  return (
    <Text
      size="xs"
      c="dimmed"
      // Full sha on hover — the menu shows the short form so the
      // dropdown doesn't grow a scrollbar, but the whole sha is what
      // you paste into `git show`.
      title={commit ?? undefined}
    >
      {text}
    </Text>
  );
}

/**
 * Which builds this deployment is running — atrium's, and the host
 * app's when there is one. Rendered at the top of the signed-in user
 * menu, above the account's email:
 *
 *   Atrium v0.29.1
 *   West Monroe 1.4.0     (or "atrium-pa: 22d2801" when untagged)
 *
 * Owns its own `Menu.Label` + divider so it can disappear completely:
 * until `/version` resolves (or if the image carries no stamp at all)
 * there is nothing worth showing, and an empty label with a divider
 * under it reads as a rendering bug. This is reference information,
 * not a control — an "unknown" placeholder would be worse than no
 * line.
 */
export function VersionMenuLabel({ appName }: { appName?: string }) {
  const { t } = useTranslation();
  const { data } = useVersionInfo();
  if (!data) return null;

  // The host image stamps its own name; fall back to the brand name
  // (admin-editable) and then to a generic label so a version number
  // is never left orphaned.
  const appLabel = data.app?.name || appName || t('version.app');
  const atrium = formatComponentVersion(t('version.atrium'), data.atrium);
  const app = formatComponentVersion(appLabel, data.app);
  if (!atrium && !app) return null;

  return (
    <>
      <Menu.Label>
        <Stack gap={0} data-testid="version-info">
          <Line text={atrium} commit={data.atrium.commit} />
          <Line text={app} commit={data.app?.commit ?? null} />
        </Stack>
      </Menu.Label>
      <Menu.Divider />
    </>
  );
}
