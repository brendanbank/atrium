// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Button, Group, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { IconUserOff } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useMe } from '@/hooks/useAuth';
import { stopImpersonating } from '@/lib/auth';

export function ImpersonationBanner() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const qc = useQueryClient();

  if (!me?.impersonating_from) return null;

  const handleStop = async () => {
    try {
      await stopImpersonating();
      // Invalidate every cached query so pages rerender under the
      // original identity. invalidateQueries (not clear()) both marks
      // queries stale and awaits active-observer refetches — clear()
      // wipes the query entry, so a subsequent refetchQueries would
      // find nothing to refetch and the banner would stay on stale me.
      await qc.invalidateQueries();
      notifications.show({
        color: 'teal',
        message: t('impersonate.stopped'),
      });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('impersonate.stopFailed'),
      });
    }
  };

  return (
    <Group
      justify="space-between"
      wrap="wrap"
      gap="xs"
      px="md"
      py={6}
      style={{
        background: 'var(--mantine-color-orange-light)',
        borderBottom: '1px solid var(--mantine-color-orange-5)',
      }}
    >
      <Text size="sm" style={{ flex: '1 1 240px', minWidth: 0 }}>
        {t('impersonate.banner', {
          name: me.full_name,
          original: me.impersonating_from.full_name,
        })}
      </Text>
      <Button
        size="xs"
        variant="filled"
        color="orange"
        leftSection={<IconUserOff size={14} />}
        onClick={handleStop}
        style={{ flexShrink: 0 }}
      >
        {t('impersonate.stop')}
      </Button>
    </Group>
  );
}
