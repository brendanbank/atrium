// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * /profile/tokens — per-user token management.
 *
 * Lists the calling user's PATs, lets them create / rotate / revoke.
 * Plaintext only ever appears in the reveal modal, which holds it in
 * component-local state and discards on dismiss.
 *
 * Hidden from PAT-authed sessions: ``principal.auth_method`` is
 * surfaced as ``me.auth_method`` on ``/users/me/context``; for now
 * we just gate on ``auth.pats.read_self`` (every user holds it) and
 * trust the backend's ``require_cookie_auth`` to refuse mutations
 * from a PAT-authed session. The link in AppLayout / the profile
 * card omits when the perm is missing.
 */
import { useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';

import { TokenCreateModal } from '@/components/tokens/TokenCreateModal';
import { TokenRevealModal } from '@/components/tokens/TokenRevealModal';
import { TokensTable } from '@/components/tokens/TokensTable';
import { useAppConfig } from '@/hooks/useAppConfig';
import { useMe, usePerm } from '@/hooks/useAuth';
import {
  useRevokeToken,
  useRotateToken,
  useTokens,
  type TokenCreated,
  type TokenSummary,
} from '@/hooks/useTokens';

export function TokensPage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canManage = usePerm('auth.pats.read_self');
  const tokens = useTokens();
  const rotate = useRotateToken();
  const revoke = useRevokeToken();
  const { data: appConfig } = useAppConfig();
  const [createOpen, setCreateOpen] = useState(false);
  const [revealed, setRevealed] = useState<TokenCreated | null>(null);

  if (!me) return <Loader />;
  if (!canManage) {
    return (
      <Alert color="red" data-testid="tokens-perm-denied">
        {t('tokens.notAllowed')}
      </Alert>
    );
  }

  // ``auth.pats.*`` config bundle is admin-only — the public bundle
  // doesn't expose ``max_lifetime_days``. The picker treats null as
  // "never allowed" only when the server actually caps it; without
  // visibility into the cap, we render the full set of options and
  // let the server downcap on submit. This matches how every other
  // public-config knob behaves.
  const maxLifetimeDays: number | null = null;

  const onRotate = async (row: TokenSummary) => {
    if (!window.confirm(t('tokens.rotate.confirm', { name: row.name }))) return;
    try {
      const created = await rotate.mutateAsync(row.id);
      setRevealed(created);
    } catch {
      notifications.show({
        color: 'red',
        message: t('tokens.errors.rotateFailed'),
      });
    }
  };

  const onRevoke = async (row: TokenSummary) => {
    try {
      await revoke.mutateAsync({ id: row.id });
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

  const userPerms = me.permissions ?? [];
  // The brand on the public bundle doubles as a sanity check that
  // /app-config resolved; nothing on the bundle gates the page.
  void appConfig;

  return (
    <Stack maw={1100} gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={2}>{t('tokens.profile.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('tokens.profile.intro')}
          </Text>
        </Stack>
        <Button
          onClick={() => setCreateOpen(true)}
          data-testid="token-create-open"
        >
          {t('tokens.profile.newToken')}
        </Button>
      </Group>

      <Paper withBorder p="sm" radius="md">
        <TokensTable
          variant="profile"
          tokens={tokens.data ?? []}
          loading={tokens.isLoading}
          empty={t('tokens.profile.empty')}
          onRotate={onRotate}
          onRevoke={onRevoke}
        />
      </Paper>

      <TokenCreateModal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        availableScopes={userPerms}
        maxLifetimeDays={maxLifetimeDays}
        onCreated={(created) => {
          setCreateOpen(false);
          setRevealed(created);
        }}
      />

      <TokenRevealModal
        opened={revealed !== null}
        token={revealed?.token ?? null}
        name={revealed?.name ?? null}
        onClose={() => setRevealed(null)}
      />
    </Stack>
  );
}
