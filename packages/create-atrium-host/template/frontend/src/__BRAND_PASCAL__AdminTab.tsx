import { MantineProvider, Stack, Text, Title } from '@mantine/core';
import { QueryClientProvider } from '@tanstack/react-query';
import { AtriumProvider } from '@brendanbank/atrium-host-bundle-utils/react';

import { __BRAND_PASCAL__Widget } from './__BRAND_PASCAL__Widget';
import { queryClient } from './queryClient';

function __BRAND_PASCAL__AdminTabInner() {
  return (
    <Stack gap="md">
      <Title order={3}>__BRAND_NAME__ admin</Title>
      <Text c="dimmed" size="sm">
        Permission-gated tab in the admin shell. Atrium hides this tab
        for users without ``__HOST_PKG__.write``; the API enforces the
        same on every write.
      </Text>
      <__BRAND_PASCAL__Widget />
    </Stack>
  );
}

export function __BRAND_PASCAL__AdminTab() {
  return (
    <MantineProvider>
      <QueryClientProvider client={queryClient}>
        <AtriumProvider>
          <__BRAND_PASCAL__AdminTabInner />
        </AtriumProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
