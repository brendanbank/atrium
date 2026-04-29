// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react';
import {
  Badge,
  Button,
  Code,
  Group,
  Pagination,
  Paper,
  SegmentedControl,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconSend } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import {
  useDrainOutboxRow,
  useEmailOutbox,
  type EmailOutboxRow,
  type EmailOutboxStatus,
} from '@/hooks/useEmailOutbox';

const PAGE_SIZE = 50;

const STATUS_FILTERS: Array<{ value: 'all' | EmailOutboxStatus; key: string }> = [
  { value: 'all', key: 'emailOutbox.statusAll' },
  { value: 'pending', key: 'emailOutbox.statusPending' },
  { value: 'sending', key: 'emailOutbox.statusSending' },
  { value: 'sent', key: 'emailOutbox.statusSent' },
  { value: 'dead', key: 'emailOutbox.statusDead' },
];

const STATUS_COLORS: Record<EmailOutboxStatus, string> = {
  pending: 'yellow',
  sending: 'blue',
  sent: 'teal',
  dead: 'red',
};

export function EmailOutboxAdmin() {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<'all' | EmailOutboxStatus>(
    'pending',
  );
  const [page, setPage] = useState(1);

  const { data, isLoading } = useEmailOutbox({
    status: statusFilter === 'all' ? null : statusFilter,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <Stack>
      <Group justify="space-between" align="flex-end">
        <Title order={3}>{t('emailOutbox.title')}</Title>
        <SegmentedControl
          size="xs"
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v as 'all' | EmailOutboxStatus);
            setPage(1);
          }}
          data={STATUS_FILTERS.map((f) => ({
            value: f.value,
            label: t(f.key),
          }))}
        />
      </Group>

      <Paper withBorder>
        <Table.ScrollContainer minWidth={760}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('emailOutbox.template')}</Table.Th>
                <Table.Th>{t('emailOutbox.toAddr')}</Table.Th>
                <Table.Th>{t('emailOutbox.locale')}</Table.Th>
                <Table.Th>{t('emailOutbox.status')}</Table.Th>
                <Table.Th>{t('emailOutbox.attempts')}</Table.Th>
                <Table.Th>{t('emailOutbox.nextAttempt')}</Table.Th>
                <Table.Th w={80} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {isLoading && (
                <Table.Tr>
                  <Table.Td colSpan={7}>
                    <Text c="dimmed">{t('common.loading')}</Text>
                  </Table.Td>
                </Table.Tr>
              )}
              {!isLoading && (data?.items.length ?? 0) === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={7}>
                    <Text c="dimmed">{t('emailOutbox.empty')}</Text>
                  </Table.Td>
                </Table.Tr>
              )}
              {data?.items.map((row) => (
                <OutboxRow key={row.id} row={row} />
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>

      {data && data.total > PAGE_SIZE && (
        <Group justify="center">
          <Pagination total={totalPages} value={page} onChange={setPage} />
        </Group>
      )}
    </Stack>
  );
}

function OutboxRow({ row }: { row: EmailOutboxRow }) {
  const { t } = useTranslation();
  const drain = useDrainOutboxRow();
  const nextAttempt = new Date(
    row.next_attempt_at + (row.next_attempt_at.endsWith('Z') ? '' : 'Z'),
  );
  const canDrain = row.status === 'pending';

  const onDrain = async () => {
    try {
      const result = await drain.mutateAsync(row.id);
      const messageKey =
        result.status === 'sent'
          ? 'emailOutbox.drainSent'
          : result.status === 'dead'
            ? 'emailOutbox.drainDead'
            : 'emailOutbox.drainPending';
      notifications.show({
        color:
          result.status === 'sent'
            ? 'teal'
            : result.status === 'dead'
              ? 'red'
              : 'yellow',
        message: t(messageKey),
      });
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      notifications.show({
        color: 'red',
        message: detail ?? t('emailOutbox.drainFailed'),
      });
    }
  };

  return (
    <>
      <Table.Tr>
        <Table.Td>
          <Text ff="monospace" size="sm">
            {row.template}
          </Text>
        </Table.Td>
        <Table.Td>
          <Text size="sm">{row.to_addr}</Text>
        </Table.Td>
        <Table.Td>
          <Text size="sm" ff="monospace" c="dimmed">
            {row.locale}
          </Text>
        </Table.Td>
        <Table.Td>
          <Badge color={STATUS_COLORS[row.status]} variant="light" size="sm">
            {row.status}
          </Badge>
        </Table.Td>
        <Table.Td>
          <Text size="sm">{row.attempts}</Text>
        </Table.Td>
        <Table.Td>
          <Text size="xs">{nextAttempt.toLocaleString()}</Text>
        </Table.Td>
        <Table.Td>
          <Tooltip
            label={
              canDrain
                ? t('emailOutbox.drainTooltip')
                : t('emailOutbox.drainDisabledTooltip')
            }
          >
            <span>
              <Button
                size="xs"
                variant="light"
                leftSection={<IconSend size={12} />}
                disabled={!canDrain}
                loading={drain.isPending && drain.variables === row.id}
                onClick={onDrain}
              >
                {t('emailOutbox.drainAction')}
              </Button>
            </span>
          </Tooltip>
        </Table.Td>
      </Table.Tr>
      {row.last_error && (
        <Table.Tr>
          <Table.Td colSpan={7}>
            <Code block style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>
              {row.last_error}
            </Code>
          </Table.Td>
        </Table.Tr>
      )}
    </>
  );
}
