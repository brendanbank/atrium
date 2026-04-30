import { Container, Stack, Text, Title } from '@mantine/core';
import { MantineProvider } from '@mantine/core';
import { QueryClientProvider } from '@tanstack/react-query';
import {
  AtriumProvider,
  useAtriumColorScheme,
} from '@brendanbank/atrium-host-bundle-utils/react';

import { __BRAND_PASCAL__Widget } from './__BRAND_PASCAL__Widget';
import { queryClient } from './queryClient';

function __BRAND_PASCAL__PageInner() {
  return (
    <Container size="md" py="xl">
      <Stack gap="md">
        <Title order={2}>__BRAND_NAME__</Title>
        <Text c="dimmed">
          Dedicated route registered by the host bundle. Replace this
          page with your real domain UI.
        </Text>
        <__BRAND_PASCAL__Widget />
      </Stack>
    </Container>
  );
}

export function __BRAND_PASCAL__Page() {
  const scheme = useAtriumColorScheme();
  return (
    <MantineProvider defaultColorScheme={scheme}>
      <QueryClientProvider client={queryClient}>
        <AtriumProvider>
          <__BRAND_PASCAL__PageInner />
        </AtriumProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
