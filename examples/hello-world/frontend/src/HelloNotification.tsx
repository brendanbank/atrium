// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Per-kind notification renderer registered by the Hello World host
 * bundle.
 *
 * Demonstrates the ``registerNotificationKind`` extension point.
 * Atrium emits ``{kind, payload}`` rows but ships no built-in
 * formatting; the host names the kinds it cares about and decides
 * what each one looks like in the bell + inbox.
 *
 * The bundle registers a renderer for ``hello.toggled`` (the kind
 * the backend writes when the Hello World counter is flipped).
 * Atrium calls:
 *
 *   - ``title(n)``     → the row line + modal title
 *   - ``render(n)``    → the detail-modal body
 *   - ``href(n)``      → omitted here; clicking the row opens the
 *                        modal so visitors can see the rich render
 *
 * Atrium is unchanged for any kind we don't claim — the fallback
 * raw-payload modal still renders for unregistered kinds.
 */
import {
  Badge,
  Group,
  MantineProvider,
  Paper,
  Stack,
  Text,
} from '@mantine/core';

interface HelloToggledPayload {
  enabled?: boolean;
  counter?: number;
  actor_user_id?: number;
}

export function helloToggledTitle(n: { payload: Record<string, unknown> }): string {
  const payload = n.payload as HelloToggledPayload;
  const verb = payload.enabled ? 'enabled' : 'disabled';
  return `Hello World ${verb} (counter: ${payload.counter ?? '?'})`;
}

function HelloToggledNotificationInner({
  payload,
  createdAt,
}: {
  payload: HelloToggledPayload;
  createdAt: string;
}) {
  return (
    <Paper withBorder p="md" radius="md" data-testid="hello-notification">
      <Stack gap="xs">
        <Group justify="space-between" align="center">
          <Text fw={500}>Hello World counter</Text>
          <Badge color={payload.enabled ? 'teal' : 'gray'} variant="light">
            {payload.enabled ? 'enabled' : 'disabled'}
          </Badge>
        </Group>
        <Text size="sm">
          Counter is now <strong>{payload.counter ?? '?'}</strong>.
        </Text>
        <Text size="xs" c="dimmed">
          Toggled by user #{payload.actor_user_id ?? '?'} ·{' '}
          {new Date(
            createdAt + (createdAt.endsWith('Z') ? '' : 'Z'),
          ).toLocaleString()}
        </Text>
      </Stack>
    </Paper>
  );
}

export function HelloToggledNotification({
  payload,
  createdAt,
}: {
  payload: HelloToggledPayload;
  createdAt: string;
}) {
  return (
    <MantineProvider>
      <HelloToggledNotificationInner payload={payload} createdAt={createdAt} />
    </MantineProvider>
  );
}
