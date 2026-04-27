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
  getHelloState,
  getMeContext,
  postHelloToggle,
  type HelloState,
} from './api';
import { queryClient } from './queryClient';

const STATE_KEY = ['hello', 'state'] as const;
const ME_KEY = ['hello', 'me-context'] as const;

function HelloWidgetInner() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: STATE_KEY,
    queryFn: getHelloState,
  });
  const { data: me } = useQuery({
    queryKey: ME_KEY,
    queryFn: getMeContext,
  });
  const canToggle = me?.permissions.includes('hello.toggle') ?? false;
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
        {isLoading && <Loader size="xs" />}
        {error && (
          <Text c="red" size="sm">
            Failed to load: {(error as Error).message}
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
  return (
    <MantineProvider>
      <QueryClientProvider client={queryClient}>
        <HelloWidgetInner />
      </QueryClientProvider>
    </MantineProvider>
  );
}
