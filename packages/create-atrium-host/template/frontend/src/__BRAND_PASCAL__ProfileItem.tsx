import { Card, MantineProvider, Stack, Text, Title } from '@mantine/core';
import { QueryClientProvider } from '@tanstack/react-query';
import {
  AtriumProvider,
  useAtriumColorScheme,
  useMe,
} from '@brendanbank/atrium-host-bundle-utils/react';

import { queryClient } from './queryClient';

function __BRAND_PASCAL__ProfileItemInner() {
  const { data: me } = useMe();
  return (
    <Card withBorder padding="lg" radius="md">
      <Stack gap="xs">
        <Title order={4}>__BRAND_NAME__</Title>
        <Text size="sm" c="dimmed">
          Per-user host extension card slotted after the role list.
          Use this slot for app-specific identity bits — preferred
          location, notification preferences, opt-in features.
        </Text>
        {me && (
          <Text size="sm">
            Signed in as <strong>{me.email}</strong>.
          </Text>
        )}
      </Stack>
    </Card>
  );
}

export function __BRAND_PASCAL__ProfileItem() {
  const scheme = useAtriumColorScheme();
  return (
    <MantineProvider defaultColorScheme={scheme}>
      <QueryClientProvider client={queryClient}>
        <AtriumProvider>
          <__BRAND_PASCAL__ProfileItemInner />
        </AtriumProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
