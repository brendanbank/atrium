/** Home-widget rendering of the demo state.
 *
 * Wraps itself in MantineProvider + QueryClientProvider + AtriumProvider
 * so the host bundle's Mantine instance, TanStack cache, and atrium
 * user-context query stay isolated from atrium's own copies. Two
 * MantineProviders nested in the DOM is supported by Mantine.
 *
 * Permission gating uses `usePerm()` from
 * `@brendanbank/atrium-host-bundle-utils/react` — a single TanStack
 * Query subscription against atrium's `/users/me/context`, shared
 * across this widget, the dedicated page, and the admin tab.
 */
import {
  Badge,
  Button,
  Card,
  Group,
  Loader,
  MantineProvider,
  Stack,
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
  AtriumProvider,
  useAtriumColorScheme,
  usePerm,
} from '@brendanbank/atrium-host-bundle-utils/react';

import {
  bump__BRAND_PASCAL__,
  get__BRAND_PASCAL__State,
  type __BRAND_PASCAL__State,
} from './api';
import { queryClient } from './queryClient';

const STATE_KEY = ['__HOST_PKG__', 'state'] as const;

function __BRAND_PASCAL__WidgetInner() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: STATE_KEY,
    queryFn: get__BRAND_PASCAL__State,
  });
  const hasPerm = usePerm();
  const canBump = hasPerm('__HOST_PKG__.write');
  const bumpMutation = useMutation({
    mutationFn: bump__BRAND_PASCAL__,
    onSuccess: (next: __BRAND_PASCAL__State) => {
      qc.setQueryData(STATE_KEY, next);
    },
  });

  return (
    <Card withBorder padding="lg" radius="md" data-testid="__HOST_NAME__-card">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={4}>__BRAND_NAME__</Title>
          <Badge color={canBump ? 'teal' : 'gray'} variant="light">
            {canBump ? 'editor' : 'viewer'}
          </Badge>
        </Group>
        {isLoading && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">Loading…</Text>
          </Group>
        )}
        {error && (
          <Text c="red" size="sm">
            Error: {(error as Error).message}
          </Text>
        )}
        {data && (
          <>
            <Text size="lg" fw={500} data-testid="__HOST_NAME__-message">
              {data.message}
            </Text>
            <Text
              ff="monospace"
              size="xl"
              fw={700}
              data-testid="__HOST_NAME__-counter"
            >
              {data.counter}
            </Text>
            <Button
              onClick={() => bumpMutation.mutate()}
              disabled={!canBump || bumpMutation.isPending}
              data-testid="__HOST_NAME__-bump"
              fullWidth
            >
              {canBump ? 'Bump counter' : 'Bump (admin only)'}
            </Button>
          </>
        )}
      </Stack>
    </Card>
  );
}

export function __BRAND_PASCAL__Widget() {
  const scheme = useAtriumColorScheme();
  return (
    <MantineProvider defaultColorScheme={scheme}>
      <QueryClientProvider client={queryClient}>
        <AtriumProvider>
          <__BRAND_PASCAL__WidgetInner />
        </AtriumProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
