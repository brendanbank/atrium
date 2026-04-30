// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/** Dedicated /hello route — same widget, plus a tiny detail line so
 *  the page is visibly different from the home card. Demonstrates the
 *  registerRoute slot. */
import {
  Container,
  MantineProvider,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { useAtriumColorScheme } from '@brendanbank/atrium-host-bundle-utils/react';

import { getHelloState } from './api';
import { HelloWidget } from './HelloWidget';
import { queryClient } from './queryClient';

function HelloPageInner() {
  const { data } = useQuery({
    queryKey: ['hello', 'state'],
    queryFn: getHelloState,
  });
  return (
    <Container size={680}>
      <Stack gap="md">
        <Title order={2}>Hello World page</Title>
        <Text c="dimmed" size="sm">
          Registered via{' '}
          <code>window.__ATRIUM_REGISTRY__.registerRoute</code>. Atrium's
          router renders this element when the path matches.
        </Text>
        <HelloWidget />
        {data && (
          <Text size="xs" c="dimmed" data-testid="hello-page-counter-line">
            counter is {data.counter}
          </Text>
        )}
      </Stack>
    </Container>
  );
}

export function HelloPage() {
  const scheme = useAtriumColorScheme();
  return (
    <MantineProvider defaultColorScheme={scheme}>
      <QueryClientProvider client={queryClient}>
        <HelloPageInner />
      </QueryClientProvider>
    </MantineProvider>
  );
}
