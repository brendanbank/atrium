// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { IconCheck, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { NotificationPayloadModal } from '@/components/NotificationsBell';
import { renderNotificationBody } from '@/lib/notifications';
import {
  useDeleteNotification,
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  type AppNotification,
} from '@/hooks/useNotifications';

function formatTimestamp(iso: string): string {
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  return d.toLocaleString();
}

/** Full-page inbox of every notification the user has received.
 *
 *  Atrium ships a kind-agnostic renderer: each row shows the kind
 *  string + a "View" button that opens the raw ``payload`` JSON in a
 *  modal. Host apps can swap in pretty per-kind rendering later. */
export function NotificationsPage() {
  const { t } = useTranslation();
  const { data: list = [], isLoading } = useNotifications();
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();
  const delNotif = useDeleteNotification();
  const [payloadOpen, setPayloadOpen] = useState<AppNotification | null>(null);

  const unreadCount = list.filter((n) => n.read_at === null).length;

  const view = (n: AppNotification) => {
    if (n.read_at === null) markRead.mutate(n.id);
    setPayloadOpen(n);
  };

  if (isLoading) {
    return (
      <Center h={200}>
        <Loader />
      </Center>
    );
  }

  return (
    <Container size={720}>
      <Group justify="space-between" mb="md" align="center">
        <Title order={2}>{t('notifs.inboxTitle')}</Title>
        {unreadCount > 0 && (
          <Button
            variant="light"
            leftSection={<IconCheck size={14} />}
            onClick={() => markAllRead.mutate()}
            loading={markAllRead.isPending}
          >
            {t('notifs.markAllRead')}
          </Button>
        )}
      </Group>

      {list.length === 0 ? (
        <Paper withBorder p="xl">
          <Text c="dimmed" ta="center">
            {t('notifs.empty')}
          </Text>
        </Paper>
      ) : (
        <Stack gap="xs">
          {list.map((n) => {
            const isUnread = n.read_at === null;
            return (
              <Paper
                key={n.id}
                withBorder
                p="sm"
                radius="md"
                style={{
                  background: isUnread
                    ? 'light-dark(var(--mantine-color-teal-0), var(--mantine-color-teal-9))'
                    : undefined,
                }}
              >
                <Group justify="space-between" wrap="nowrap" align="flex-start">
                  <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
                    <Group gap={6}>
                      {isUnread && (
                        <Badge color="teal" size="xs" variant="filled" radius="sm">
                          {t('notifs.new')}
                        </Badge>
                      )}
                      <Text size="xs" c="dimmed">
                        {formatTimestamp(n.created_at)}
                      </Text>
                    </Group>
                    <Text size="sm" ff="monospace">
                      {renderNotificationBody(n)}
                    </Text>
                  </Stack>
                  <Group gap={4} wrap="nowrap">
                    <Button size="xs" variant="subtle" onClick={() => view(n)}>
                      {t('notifs.view')}
                    </Button>
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      aria-label={t('common.delete')}
                      onClick={() => delNotif.mutate(n.id)}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Group>
                </Group>
              </Paper>
            );
          })}
        </Stack>
      )}

      <NotificationPayloadModal
        notif={payloadOpen}
        onClose={() => setPayloadOpen(null)}
      />
    </Container>
  );
}
