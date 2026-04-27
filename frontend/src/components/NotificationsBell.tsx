// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Code,
  Divider,
  Group,
  Indicator,
  Modal,
  Popover,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { IconBell, IconCheck, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useMe } from '@/hooks/useAuth';
import {
  useDeleteNotification,
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useUnreadCount,
  type AppNotification,
} from '@/hooks/useNotifications';
import { useNotificationStream } from '@/hooks/useNotificationStream';
import { renderNotificationBody } from '@/lib/notifications';

function formatRelative(iso: string): string {
  const then = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  const diffMs = Date.now() - then.getTime();
  const s = Math.round(diffMs / 1000);
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return then.toLocaleDateString();
}

export function NotificationsBell() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const { data: unread = 0, refetch: refetchUnread } = useUnreadCount();
  const { data: list = [], refetch: refetchList } = useNotifications();
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();
  const delNotif = useDeleteNotification();
  const [opened, setOpened] = useState(false);
  const [payloadOpen, setPayloadOpen] = useState<AppNotification | null>(null);

  const handleNotifClick = (n: AppNotification) => {
    if (n.read_at === null) markRead.mutate(n.id);
    setPayloadOpen(n);
    setOpened(false);
  };

  // Subscribe to the SSE stream while the user is logged in; EventSource
  // invalidates the bell queries on every push so updates land instantly.
  useNotificationStream(Boolean(me));

  // Force a fresh pull on every open so the user sees the latest state
  // even if the cached background poll is still within its interval.
  const handleOpenChange = (next: boolean) => {
    setOpened(next);
    if (next) {
      void refetchUnread();
      void refetchList();
    }
  };

  return (
    <>
      <Popover
        width={360}
        position="bottom-end"
        shadow="md"
        withArrow
        opened={opened}
        onChange={handleOpenChange}
      >
        <Popover.Target>
          <Indicator
            inline
            label={unread > 99 ? '99+' : unread}
            size={16}
            color="red"
            disabled={unread === 0}
            offset={4}
          >
            <ActionIcon
              variant="subtle"
              size="lg"
              aria-label={t('notifs.title')}
              onClick={() => handleOpenChange(!opened)}
            >
              <IconBell size={18} />
            </ActionIcon>
          </Indicator>
        </Popover.Target>
        <Popover.Dropdown p="xs">
          <Group justify="space-between" mb="xs" px="xs">
            <Text fw={600}>{t('notifs.title')}</Text>
            {unread > 0 && (
              <Button
                size="xs"
                variant="subtle"
                leftSection={<IconCheck size={12} />}
                onClick={() => markAllRead.mutate()}
                loading={markAllRead.isPending}
              >
                {t('notifs.markAllRead')}
              </Button>
            )}
          </Group>
          <Divider />
          {list.length === 0 ? (
            <Text c="dimmed" ta="center" size="sm" py="md">
              {t('notifs.empty')}
            </Text>
          ) : (
            <ScrollArea h={360}>
              <Stack gap={0}>
                {list.map((n) => {
                  const isUnread = n.read_at === null;
                  return (
                    <Group
                      key={n.id}
                      wrap="nowrap"
                      align="flex-start"
                      gap="xs"
                      p="xs"
                      style={{
                        background: isUnread
                          ? 'light-dark(var(--mantine-color-teal-0), var(--mantine-color-teal-9))'
                          : undefined,
                        borderRadius: 4,
                      }}
                    >
                      <UnstyledButton
                        onClick={() => handleNotifClick(n)}
                        style={{ flex: 1, textAlign: 'left' }}
                      >
                        <Stack gap={2}>
                          <Group gap={6}>
                            {isUnread && (
                              <Badge color="teal" size="xs" variant="filled" radius="sm">
                                {t('notifs.new')}
                              </Badge>
                            )}
                            <Text size="xs" c="dimmed">
                              {formatRelative(n.created_at)}
                            </Text>
                          </Group>
                          <Text size="sm" ff="monospace">
                            {renderNotificationBody(n)}
                          </Text>
                        </Stack>
                      </UnstyledButton>
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        color="gray"
                        aria-label={t('common.delete')}
                        onClick={() => delNotif.mutate(n.id)}
                      >
                        <IconX size={12} />
                      </ActionIcon>
                    </Group>
                  );
                })}
              </Stack>
            </ScrollArea>
          )}
        </Popover.Dropdown>
      </Popover>
      <NotificationPayloadModal
        notif={payloadOpen}
        onClose={() => setPayloadOpen(null)}
      />
    </>
  );
}

export function NotificationPayloadModal({
  notif,
  onClose,
}: {
  notif: AppNotification | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      opened={notif !== null}
      onClose={onClose}
      title={notif?.kind ?? ''}
      size="lg"
    >
      {notif && (
        <Stack>
          <Text size="xs" c="dimmed">
            {t('notifs.payloadHint')}
          </Text>
          <Code
            block
            style={{
              fontSize: 12,
              lineHeight: 1.45,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {JSON.stringify(notif.payload, null, 2)}
          </Code>
        </Stack>
      )}
    </Modal>
  );
}
