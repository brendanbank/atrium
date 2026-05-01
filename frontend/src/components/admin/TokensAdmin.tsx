// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Admin tokens tab — cross-user PAT view + service-account creation.
 *
 * Lives under /admin/tokens via ``admin/sections.tsx``. Gated by
 * ``auth.pats.admin_read`` for read; revoke + create-SA need
 * ``auth.pats.admin_revoke`` and ``auth.service_accounts.manage``
 * respectively.
 */
import { useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Code,
  Divider,
  Drawer,
  Group,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';

import { ServiceAccountCreateModal } from '@/components/tokens/ServiceAccountCreateModal';
import { TokenRevealModal } from '@/components/tokens/TokenRevealModal';
import { TokensTable } from '@/components/tokens/TokensTable';
import { useMe, usePerm } from '@/hooks/useAuth';
import { useRoles } from '@/hooks/useRolesAdmin';
import {
  useAdminRevokeToken,
  useAdminTokenAudit,
  useAdminTokens,
  useServiceAccounts,
  type AdminTokenSummary,
  type ServiceAccountCreated,
  type TokenStatus,
} from '@/hooks/useTokens';

const STATUS_VALUES = ['all', 'active', 'expired', 'revoked'] as const;
type StatusFilter = (typeof STATUS_VALUES)[number];

export function TokensAdmin() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canRead = usePerm('auth.pats.admin_read');
  const canRevoke = usePerm('auth.pats.admin_revoke');
  const canManageSA = usePerm('auth.service_accounts.manage');

  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [emailFilter, setEmailFilter] = useState('');
  const [auditTokenId, setAuditTokenId] = useState<number | null>(null);
  const [auditTokenName, setAuditTokenName] = useState<string>('');
  const [saModalOpen, setSaModalOpen] = useState(false);
  const [revealed, setRevealed] = useState<ServiceAccountCreated | null>(null);

  const tokensQuery = useAdminTokens(
    statusFilter === 'all'
      ? { limit: 200 }
      : { status: statusFilter as TokenStatus, limit: 200 },
  );
  const audit = useAdminTokenAudit(auditTokenId);
  const revoke = useAdminRevokeToken();
  const serviceAccounts = useServiceAccounts();
  const rolesQuery = useRoles();

  const filteredItems = useMemo(() => {
    const items = tokensQuery.data?.items ?? [];
    if (!emailFilter.trim()) return items;
    const q = emailFilter.trim().toLowerCase();
    return items.filter(
      (r) =>
        r.user_email.toLowerCase().includes(q) ||
        r.user_full_name.toLowerCase().includes(q),
    );
  }, [tokensQuery.data, emailFilter]);

  if (!canRead) {
    return <Alert color="red">{t('tokens.notAllowed')}</Alert>;
  }

  const onRevoke = async (row: AdminTokenSummary, reason: string) => {
    try {
      await revoke.mutateAsync({ id: row.id, reason });
      notifications.show({
        color: 'teal',
        message: t('tokens.revoke.done'),
      });
    } catch {
      notifications.show({
        color: 'red',
        message: t('tokens.errors.revokeFailed'),
      });
    }
  };

  const onShowAudit = (row: AdminTokenSummary) => {
    setAuditTokenId(row.id);
    setAuditTokenName(row.name);
  };

  const userPerms = me?.permissions ?? [];
  const availableRoles = (rolesQuery.data ?? [])
    .map((r) => r.code)
    .filter((c) => c !== 'super_admin');

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Stack gap={2}>
          <Title order={2}>{t('tokens.admin.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('tokens.admin.intro')}
          </Text>
        </Stack>
        {canManageSA ? (
          <Button
            onClick={() => setSaModalOpen(true)}
            data-testid="sa-create-open"
          >
            {t('tokens.admin.newServiceAccount')}
          </Button>
        ) : null}
      </Group>

      <Paper withBorder p="sm" radius="md">
        <Stack gap="sm">
          <Group gap="sm" wrap="wrap">
            <SegmentedControl
              value={statusFilter}
              onChange={(v) => setStatusFilter(v as StatusFilter)}
              data={STATUS_VALUES.map((v) => ({
                value: v,
                label: t(`tokens.filters.status.${v}` as const),
              }))}
              data-testid="tokens-status-filter"
            />
            <TextInput
              placeholder={t('tokens.filters.userPlaceholder')}
              value={emailFilter}
              onChange={(e) => setEmailFilter(e.currentTarget.value)}
              w={260}
            />
            <Text c="dimmed" size="xs">
              {t('tokens.admin.shownTotal', {
                shown: filteredItems.length,
                total: tokensQuery.data?.total ?? 0,
              })}
            </Text>
          </Group>

          <TokensTable
            variant="admin"
            tokens={filteredItems}
            loading={tokensQuery.isLoading}
            empty={t('tokens.admin.empty')}
            onRevoke={canRevoke ? onRevoke : () => undefined}
            onShowAudit={onShowAudit}
          />
        </Stack>
      </Paper>

      {canManageSA ? (
        <Paper withBorder p="sm" radius="md">
          <Title order={4} mb="xs">
            {t('tokens.admin.serviceAccountsTitle')}
          </Title>
          {serviceAccounts.isLoading ? (
            <Text c="dimmed">{t('common.loading')}</Text>
          ) : (serviceAccounts.data ?? []).length === 0 ? (
            <Text c="dimmed" size="sm">
              {t('tokens.admin.serviceAccountsEmpty')}
            </Text>
          ) : (
            <Table striped withTableBorder verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('tokens.serviceAccount.name')}</Table.Th>
                  <Table.Th>{t('tokens.serviceAccount.email')}</Table.Th>
                  <Table.Th>{t('tokens.cols.status')}</Table.Th>
                  <Table.Th>{t('tokens.cols.created')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(serviceAccounts.data ?? []).map((sa) => (
                  <Table.Tr key={sa.id}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {sa.full_name}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{sa.email}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge
                        color={sa.is_active ? 'teal' : 'gray'}
                        variant="light"
                      >
                        {sa.is_active
                          ? t('admin.active')
                          : t('admin.inactive')}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">
                        {new Date(sa.created_at).toLocaleDateString()}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Paper>
      ) : null}

      {canManageSA ? (
        <ServiceAccountCreateModal
          opened={saModalOpen}
          onClose={() => setSaModalOpen(false)}
          availableScopes={userPerms}
          availableRoles={availableRoles}
          maxLifetimeDays={null}
          onCreated={(created) => {
            setSaModalOpen(false);
            setRevealed(created);
          }}
        />
      ) : null}

      {/* Reuse TokenRevealModal: it just renders the plaintext string. */}
      <TokenRevealModal
        opened={revealed !== null}
        token={revealed?.token.token ?? null}
        name={revealed?.account.full_name ?? null}
        onClose={() => setRevealed(null)}
      />

      <Drawer
        opened={auditTokenId !== null}
        onClose={() => setAuditTokenId(null)}
        position="right"
        size="lg"
        title={t('tokens.admin.auditTitle', { name: auditTokenName })}
      >
        {audit.isLoading ? (
          <Text c="dimmed">{t('common.loading')}</Text>
        ) : (audit.data?.items ?? []).length === 0 ? (
          <Text c="dimmed" size="sm">
            {t('tokens.admin.auditEmpty')}
          </Text>
        ) : (
          <ScrollArea h="80vh">
            <Stack gap="xs">
              {audit.data?.items.map((entry) => (
                <Paper key={entry.id} withBorder p="xs">
                  <Group gap="xs" wrap="wrap">
                    <Badge variant="light" color="blue">
                      {entry.action}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      {new Date(entry.created_at).toLocaleString()}
                    </Text>
                    {entry.actor_user_id !== null ? (
                      <Text size="xs" c="dimmed">
                        actor #{entry.actor_user_id}
                      </Text>
                    ) : null}
                  </Group>
                  {entry.diff ? (
                    <>
                      <Divider my="xs" />
                      <Code
                        block
                        style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}
                      >
                        {JSON.stringify(entry.diff, null, 2)}
                      </Code>
                    </>
                  ) : null}
                </Paper>
              ))}
            </Stack>
          </ScrollArea>
        )}
      </Drawer>
    </Stack>
  );
}

