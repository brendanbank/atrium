// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/** Admin-tab rendering of the Hello World state.
 *
 * Registered with ``perm: 'hello.toggle'`` so atrium hides the tab
 * for users who don't hold it — see ``getAdminTabs().filter`` in
 * AdminPage.tsx. This component is therefore only ever mounted when
 * the viewer has the permission.
 */
import { Card, MantineProvider, Stack, Text, Title } from '@mantine/core';
import { QueryClientProvider } from '@tanstack/react-query';
import { useAtriumColorScheme } from '@brendanbank/atrium-host-bundle-utils/react';

import { HelloWidget } from './HelloWidget';
import { queryClient } from './queryClient';

function HelloAdminTabInner() {
  return (
    <Stack gap="md" data-testid="hello-admin-tab">
      <Title order={3}>Hello World admin</Title>
      <Text size="sm" c="dimmed">
        This tab is registered via{' '}
        <code>window.__ATRIUM_REGISTRY__.registerAdminTab</code> and gated
        on the <code>hello.toggle</code> permission. Users without it
        won't see the tab in the admin sidebar.
      </Text>
      <Card withBorder padding="md" radius="md">
        <HelloWidget />
      </Card>
    </Stack>
  );
}

export function HelloAdminTab() {
  const scheme = useAtriumColorScheme();
  return (
    <MantineProvider defaultColorScheme={scheme}>
      <QueryClientProvider client={queryClient}>
        <HelloAdminTabInner />
      </QueryClientProvider>
    </MantineProvider>
  );
}
