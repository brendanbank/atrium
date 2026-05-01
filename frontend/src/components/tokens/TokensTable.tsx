// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Shared table for /profile/tokens and /admin/tokens.
 *
 * The two callers want the same column set with two differences:
 *   - the admin variant adds a "User" column showing who owns the token
 *   - the admin variant's revoke action requires a non-empty reason
 *     and does not offer rotate (admins shouldn't rotate someone
 *     else's token — the user's flow does that).
 *
 * Each row is selectable via the prefix cell; selection drives the
 * audit-trail panel in the admin view (parent owns the selected id).
 */
import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import {
  IconHistory,
  IconRefresh,
  IconTrash,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import type {
  AdminTokenSummary,
  TokenSummary,
} from '@/hooks/useTokens';

interface CommonProps {
  tokens: TokenSummary[];
  loading?: boolean;
  empty?: string;
}

interface ProfileVariantProps extends CommonProps {
  variant: 'profile';
  onRotate: (token: TokenSummary) => void;
  onRevoke: (token: TokenSummary) => void;
}

interface AdminVariantProps extends CommonProps {
  variant: 'admin';
  tokens: AdminTokenSummary[];
  onRevoke: (token: AdminTokenSummary, reason: string) => void;
  onShowAudit: (token: AdminTokenSummary) => void;
}

type TokensTableProps = ProfileVariantProps | AdminVariantProps;

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

function relativeFromNow(iso: string | null): string {
  if (!iso) return '';
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diff = now - then;
  if (diff < 0) return new Date(iso).toLocaleString();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  const month = Math.floor(day / 30);
  if (month < 12) return `${month}mo ago`;
  return `${Math.floor(month / 12)}y ago`;
}

function expiringSoon(iso: string | null): boolean {
  if (!iso) return false;
  const ms = new Date(iso).getTime() - Date.now();
  return ms > 0 && ms < SEVEN_DAYS_MS;
}

function StatusBadge({ status }: { status: TokenSummary['status'] }) {
  const { t } = useTranslation();
  const color =
    status === 'active' ? 'teal' : status === 'expired' ? 'gray' : 'red';
  return (
    <Badge color={color} variant="light">
      {t(`tokens.status.${status}` as const)}
    </Badge>
  );
}

export function TokensTable(props: TokensTableProps) {
  const { t } = useTranslation();
  const { tokens, loading, empty } = props;
  const [revokeTarget, setRevokeTarget] = useState<
    TokenSummary | AdminTokenSummary | null
  >(null);
  const [revokeReason, setRevokeReason] = useState('');

  const isAdmin = props.variant === 'admin';
  const adminProps = isAdmin ? props : null;
  const profileProps = !isAdmin ? props : null;

  if (loading) {
    return <Text c="dimmed">{t('common.loading')}</Text>;
  }
  if (tokens.length === 0) {
    return (
      <Text c="dimmed" size="sm">
        {empty ?? t('common.empty')}
      </Text>
    );
  }

  const closeRevokeModal = () => {
    setRevokeTarget(null);
    setRevokeReason('');
  };

  const submitRevoke = () => {
    if (!revokeTarget) return;
    if (isAdmin && adminProps) {
      adminProps.onRevoke(
        revokeTarget as AdminTokenSummary,
        revokeReason.trim(),
      );
    } else if (profileProps) {
      profileProps.onRevoke(revokeTarget);
    }
    closeRevokeModal();
  };

  return (
    <>
      <Table
        striped
        withTableBorder
        verticalSpacing="xs"
        data-testid="tokens-table"
      >
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('tokens.cols.name')}</Table.Th>
            <Table.Th>{t('tokens.cols.prefix')}</Table.Th>
            {isAdmin ? <Table.Th>{t('tokens.cols.user')}</Table.Th> : null}
            <Table.Th>{t('tokens.cols.scopes')}</Table.Th>
            <Table.Th>{t('tokens.cols.lastUsed')}</Table.Th>
            <Table.Th>{t('tokens.cols.created')}</Table.Th>
            <Table.Th>{t('tokens.cols.expires')}</Table.Th>
            <Table.Th>{t('tokens.cols.status')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {tokens.map((row) => {
            const expSoon = expiringSoon(row.expires_at);
            return (
              <Table.Tr key={row.id} data-testid={`token-row-${row.id}`}>
                <Table.Td>
                  <Text size="sm" fw={500}>
                    {row.name}
                  </Text>
                  {row.description ? (
                    <Text size="xs" c="dimmed" lineClamp={1}>
                      {row.description}
                    </Text>
                  ) : null}
                </Table.Td>
                <Table.Td>
                  <Text
                    size="xs"
                    ff="monospace"
                    style={{ userSelect: 'text' }}
                    data-testid={`token-prefix-${row.id}`}
                  >
                    {row.token_prefix}…
                  </Text>
                </Table.Td>
                {isAdmin ? (
                  <Table.Td>
                    <Text size="sm">
                      {(row as AdminTokenSummary).user_full_name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {(row as AdminTokenSummary).user_email}
                    </Text>
                  </Table.Td>
                ) : null}
                <Table.Td>
                  <Group gap={4} wrap="wrap">
                    {row.scopes.length === 0 ? (
                      <Text size="xs" c="dimmed">
                        —
                      </Text>
                    ) : (
                      row.scopes.map((s) => (
                        <Badge
                          key={s}
                          size="xs"
                          variant="light"
                          color="blue"
                          style={{ textTransform: 'none' }}
                        >
                          {s}
                        </Badge>
                      ))
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  {row.last_used_at ? (
                    <Tooltip
                      label={
                        row.last_used_ip
                          ? `${new Date(row.last_used_at).toLocaleString()} · ${row.last_used_ip}`
                          : new Date(row.last_used_at).toLocaleString()
                      }
                    >
                      <Text size="xs">{relativeFromNow(row.last_used_at)}</Text>
                    </Tooltip>
                  ) : (
                    <Text size="xs" c="dimmed">
                      {t('tokens.neverUsed')}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="xs">
                    {new Date(row.created_at).toLocaleDateString()}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {row.expires_at ? (
                    <Text
                      size="xs"
                      c={expSoon ? 'orange.7' : undefined}
                      fw={expSoon ? 500 : undefined}
                    >
                      {new Date(row.expires_at).toLocaleDateString()}
                    </Text>
                  ) : (
                    <Text size="xs" c="dimmed">
                      {t('tokens.never')}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <StatusBadge status={row.status} />
                </Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end" wrap="nowrap">
                    {isAdmin && adminProps ? (
                      <Tooltip label={t('tokens.actions.audit')}>
                        <ActionIcon
                          variant="subtle"
                          onClick={() =>
                            adminProps.onShowAudit(row as AdminTokenSummary)
                          }
                          aria-label={t('tokens.actions.audit')}
                          data-testid={`token-audit-${row.id}`}
                        >
                          <IconHistory size={16} />
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                    {!isAdmin && profileProps && row.status === 'active' ? (
                      <Tooltip label={t('tokens.actions.rotate')}>
                        <ActionIcon
                          variant="subtle"
                          onClick={() => profileProps.onRotate(row)}
                          aria-label={t('tokens.actions.rotate')}
                          data-testid={`token-rotate-${row.id}`}
                        >
                          <IconRefresh size={16} />
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                    {row.status === 'active' ? (
                      <Tooltip label={t('tokens.actions.revoke')}>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          onClick={() => setRevokeTarget(row)}
                          aria-label={t('tokens.actions.revoke')}
                          data-testid={`token-revoke-${row.id}`}
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                  </Group>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>

      <Modal
        opened={revokeTarget !== null}
        onClose={closeRevokeModal}
        title={t('tokens.revoke.title')}
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            {t('tokens.revoke.confirm', { name: revokeTarget?.name ?? '' })}
          </Text>
          {isAdmin ? (
            <Textarea
              required
              label={t('tokens.revoke.reasonLabel')}
              description={t('tokens.revoke.reasonHelp')}
              autosize
              minRows={2}
              maxRows={4}
              value={revokeReason}
              onChange={(e) => setRevokeReason(e.currentTarget.value)}
              data-testid="token-revoke-reason"
            />
          ) : null}
          <Group justify="flex-end">
            <Button variant="default" onClick={closeRevokeModal}>
              {t('common.cancel')}
            </Button>
            <Button
              color="red"
              onClick={submitRevoke}
              disabled={isAdmin && revokeReason.trim().length === 0}
              data-testid="token-revoke-submit"
            >
              {t('tokens.revoke.submit')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
