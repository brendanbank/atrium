// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Home-widget rendering of the Hello World state.
 *
 * Wraps itself in MantineProvider + QueryClientProvider so the host
 * bundle's Mantine instance and TanStack cache stay isolated from
 * atrium's. Two MantineProviders nested in the DOM is supported by
 * Mantine; theming inside this subtree won't follow atrium's brand
 * changes (acceptable for a demo).
 *
 * Permission gating uses `usePerm()` from
 * `@brendanbank/atrium-host-bundle-utils/react`
 * — a single TanStack Query subscription against atrium's
 * `/users/me/context`, shared across this widget, the dedicated
 * page, and the admin tab.
 */
import {
  Badge,
  Card,
  Group,
  Loader,
  MantineProvider,
  Stack,
  Switch,
  Text,
  Title,
} from '@mantine/core';
import {
  useMutation,
  useQuery,
  useQueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import {
  __atrium_t__,
  AtriumProvider,
  useAtriumColorScheme,
  usePerm,
} from '@brendanbank/atrium-host-bundle-utils/react';

import {
  getHelloState,
  postHelloToggle,
  type HelloState,
} from './api';
import { queryClient } from './queryClient';

const STATE_KEY = ['hello', 'state'] as const;

function HelloWidgetInner() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: STATE_KEY,
    queryFn: getHelloState,
  });
  const hasPerm = usePerm();
  const canToggle = hasPerm('hello.toggle');
  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => postHelloToggle(enabled),
    onSuccess: (next: HelloState) => {
      qc.setQueryData(STATE_KEY, next);
    },
  });

  return (
    <Card withBorder padding="lg" radius="md" data-testid="hello-card">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={4}>Hello World</Title>
          <Badge color={data?.enabled ? 'teal' : 'gray'} variant="light">
            {data?.enabled ? 'enabled' : 'disabled'}
          </Badge>
        </Group>
        {isLoading && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              {__atrium_t__('common.loading')}
            </Text>
          </Group>
        )}
        {error && (
          <Text c="red" size="sm">
            {__atrium_t__('common.error')}: {(error as Error).message}
          </Text>
        )}
        {data && (
          <>
            <Text size="lg" fw={500} data-testid="hello-message">
              {data.message}
            </Text>
            <Text
              ff="monospace"
              size="xl"
              fw={700}
              data-testid="hello-counter"
            >
              {data.counter}
            </Text>
            <Switch
              checked={data.enabled}
              disabled={!canToggle || toggleMutation.isPending}
              onChange={(e) => toggleMutation.mutate(e.currentTarget.checked)}
              label={canToggle ? 'Increment counter' : 'Increment (admin only)'}
              data-testid="hello-toggle"
            />
          </>
        )}
      </Stack>
    </Card>
  );
}

export function HelloWidget() {
  const scheme = useAtriumColorScheme();
  return (
    <MantineProvider defaultColorScheme={scheme}>
      <QueryClientProvider client={queryClient}>
        <AtriumProvider>
          <HelloWidgetInner />
        </AtriumProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
