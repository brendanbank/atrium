// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Center, Container, Stack, Text, Title } from '@mantine/core';
import { IconTool } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useAppConfig } from '@/hooks/useAppConfig';

// Shown to non-super_admin users when system.maintenance_mode is on.
// The middleware enforces the same gate server-side; this is just the
// UI half so the user sees a friendly page instead of a stack of
// 503 toasts.
export function MaintenancePage() {
  const { t } = useTranslation();
  const { data } = useAppConfig();
  const message =
    data?.system?.maintenance_message ?? t('maintenance.defaultMessage');
  const brand = data?.brand?.name ?? 'Atrium';
  return (
    <Center h="100vh" px="md">
      <Container size="xs">
        <Stack align="center" gap="lg">
          <IconTool size={48} stroke={1.4} />
          <Title order={2} ta="center">
            {t('maintenance.title', { brand })}
          </Title>
          <Text ta="center" c="dimmed">
            {message}
          </Text>
        </Stack>
      </Container>
    </Center>
  );
}
