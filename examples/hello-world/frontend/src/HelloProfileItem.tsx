// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Profile-page item registered by the Hello World host bundle.
 *
 * Demonstrates the ``registerProfileItem`` extension point: the host
 * owns the card chrome (Paper / title / content) and renders inside
 * its own MantineProvider + QueryClientProvider, isolated from
 * atrium's React tree by the wrapper div in main.tsx.
 *
 * The item appears after the Roles summary on /profile (the default
 * slot for ``registerProfileItem``).
 */
import {
  MantineProvider,
  Paper,
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

function HelloProfileItemInner() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: STATE_KEY, queryFn: getHelloState });
  const { data: me } = useQuery({ queryKey: ME_KEY, queryFn: getMeContext });
  const canToggle = me?.permissions.includes('hello.toggle') ?? false;
  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => postHelloToggle(enabled),
    onSuccess: (next: HelloState) => qc.setQueryData(STATE_KEY, next),
  });

  return (
    <Paper withBorder p="sm" radius="md" data-testid="hello-profile-item">
      <Title order={5} mb={4}>
        Hello World preferences
      </Title>
      <Stack gap={6}>
        <Text size="sm" c="dimmed">
          Toggle the demo Hello World counter from your profile.
        </Text>
        <Switch
          checked={data?.enabled ?? false}
          disabled={!canToggle || toggleMutation.isPending}
          onChange={(e) => toggleMutation.mutate(e.currentTarget.checked)}
          label={canToggle ? 'Hello World enabled' : 'Hello World (admin only)'}
          data-testid="hello-profile-toggle"
        />
      </Stack>
    </Paper>
  );
}

export function HelloProfileItem() {
  return (
    <MantineProvider>
      <QueryClientProvider client={queryClient}>
        <HelloProfileItemInner />
      </QueryClientProvider>
    </MantineProvider>
  );
}
