// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  CopyButton,
  Group,
  Modal,
  MultiSelect,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import {
  IconCheck,
  IconCopy,
  IconDeviceMobile,
  IconKey,
  IconPencil,
  IconPlus,
  IconTrash,
  IconUserShield,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { useMe, usePerm } from '@/hooks/useAuth';
import { impersonate } from '@/lib/auth';
import { useTOTPAdminReset } from '@/hooks/useTOTP';
import { useRoles } from '@/hooks/useRolesAdmin';
import {
  useAdminResetPassword,
  useAdminUsers,
  useCreateInvite,
  useDeleteUserPermanent,
  useInvites,
  useRevokeInvite,
  useUpdateAdminUser,
  type AdminUser,
  type Invite,
  type InvitePayload,
} from '@/hooks/useUsersAdmin';

function acceptUrl(token: string): string {
  return `${window.location.origin}/accept-invite?token=${token}`;
}

function InviteRow({
  invite,
  onRevoke,
}: {
  invite: Invite;
  onRevoke: (id: number) => void;
}) {
  const { t } = useTranslation();
  const expired = new Date(invite.expires_at) < new Date();
  const accepted = invite.accepted_at !== null;
  const revoked = invite.revoked_at !== null;
  const active = !accepted && !revoked && !expired;
  // Token isn't exposed in the invites list endpoint by design; we
  // surface the invite link only at creation time (see InviteModal).

  let statusEl;
  if (accepted) statusEl = <Badge color="teal">{t('users.accepted')}</Badge>;
  else if (revoked) statusEl = <Badge color="gray">{t('users.revoked')}</Badge>;
  else if (expired) statusEl = <Badge color="red">{t('users.expired')}</Badge>;
  else statusEl = <Badge color="yellow">{t('users.pending')}</Badge>;

  const roleLabel =
    invite.role_codes.length > 0 ? invite.role_codes.join(', ') : '—';

  return (
    <Table.Tr>
      <Table.Td>{invite.full_name}</Table.Td>
      <Table.Td>{invite.email}</Table.Td>
      <Table.Td>{roleLabel}</Table.Td>
      <Table.Td>{invite.expires_at.slice(0, 10)}</Table.Td>
      <Table.Td>{statusEl}</Table.Td>
      <Table.Td>
        {active && (
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={() => onRevoke(invite.id)}
            aria-label={t('common.delete')}
          >
            <IconTrash size={14} />
          </ActionIcon>
        )}
      </Table.Td>
    </Table.Tr>
  );
}

function InviteModal({
  opened,
  onClose,
}: {
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const create = useCreateInvite();
  const { data: roles = [] } = useRoles();
  const [createdToken, setCreatedToken] = useState<string | null>(null);

  const form = useForm({
    initialValues: {
      email: '',
      full_name: '',
      role_codes: [] as string[],
      expires_in_hours: 168,
    },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : t('login.invalidEmail')),
      full_name: (v) => (v.trim() ? null : t('common.required')),
      role_codes: (v) => (v.length > 0 ? null : t('common.required')),
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      const payload: InvitePayload = {
        email: values.email.trim(),
        full_name: values.full_name.trim(),
        role_codes: values.role_codes,
        expires_in_hours: values.expires_in_hours,
      };
      const created = await create.mutateAsync(payload);
      // Grab the token the backend just minted from the response payload
      // if the API ever exposes it. Today the list endpoint hides it,
      // so fall back to a generic success state.
      const token = (created as unknown as { token?: string }).token ?? null;
      setCreatedToken(token);
      if (!token) {
        notifications.show({
          color: 'teal',
          message: t('users.inviteCreated'),
        });
        onClose();
        form.reset();
      }
    } catch (err) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })
        .response;
      notifications.show({
        color: 'red',
        message:
          resp?.status === 409
            ? t('users.inviteConflict')
            : resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  });

  return (
    <Modal
      opened={opened}
      onClose={() => {
        onClose();
        setCreatedToken(null);
      }}
      title={t('users.newInvite')}
      centered
    >
      {createdToken ? (
        <Stack>
          <Alert color="teal" title={t('users.inviteCreated')}>
            {t('users.inviteLinkHint')}
          </Alert>
          <TextInput
            value={acceptUrl(createdToken)}
            readOnly
            rightSection={
              <CopyButton value={acceptUrl(createdToken)}>
                {({ copied, copy }) => (
                  <ActionIcon variant="subtle" onClick={copy}>
                    {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                  </ActionIcon>
                )}
              </CopyButton>
            }
          />
          <Group justify="flex-end">
            <Button
              onClick={() => {
                onClose();
                setCreatedToken(null);
              }}
            >
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      ) : (
        <form onSubmit={submit}>
          <Stack>
            <TextInput
              label={t('profile.fullName')}
              required
              {...form.getInputProps('full_name')}
            />
            <TextInput
              label={t('login.email')}
              required
              type="email"
              {...form.getInputProps('email')}
            />
            <MultiSelect
              label={t('users.roles')}
              data={roles.map((r) => ({ value: r.code, label: r.name }))}
              searchable
              required
              placeholder={t('users.rolesPlaceholder')}
              {...form.getInputProps('role_codes')}
            />
            <Select
              label={t('users.expiresIn')}
              data={[
                { value: '24', label: t('users.expire24h') },
                { value: '168', label: t('users.expire7d') },
                { value: '720', label: t('users.expire30d') },
              ]}
              value={String(form.values.expires_in_hours)}
              onChange={(v) =>
                v && form.setFieldValue('expires_in_hours', Number(v))
              }
            />
            <Group justify="flex-end">
              <Button variant="subtle" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" loading={create.isPending}>
                {t('users.sendInvite')}
              </Button>
            </Group>
          </Stack>
        </form>
      )}
    </Modal>
  );
}

export function UsersAdmin() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const { data: users = [], isLoading: loadingUsers } = useAdminUsers();
  const { data: invites = [], isLoading: loadingInvites } = useInvites();
  const revokeInvite = useRevokeInvite();
  const [inviteOpen, setInviteOpen] = useState(false);

  const handleRevoke = async (id: number) => {
    if (!window.confirm(t('users.confirmRevoke'))) return;
    try {
      await revokeInvite.mutateAsync(id);
      notifications.show({ color: 'teal', message: t('users.revoked') });
    } catch {
      notifications.show({ color: 'red', message: t('admin.deleteFailed') });
    }
  };

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('users.title')}</Title>
        <Button
          leftSection={<IconPlus size={14} />}
          onClick={() => setInviteOpen(true)}
        >
          {t('users.newInvite')}
        </Button>
      </Group>

      <Paper withBorder>
        <Table.ScrollContainer minWidth={720}>
        <Table verticalSpacing="sm" style={{ whiteSpace: 'nowrap' }}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('profile.fullName')}</Table.Th>
              <Table.Th>{t('login.email')}</Table.Th>
              <Table.Th>{t('users.roles')}</Table.Th>
              <Table.Th>{t('admin.status')}</Table.Th>
              <Table.Th w={100}></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loadingUsers && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed">{t('common.loading')}</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {!loadingUsers && users.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed">{t('users.emptyUsers')}</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {users.map((u) => (
              <UserRow
                key={u.id}
                user={u}
                isSelf={u.id === me?.id}
              />
            ))}
          </Table.Tbody>
        </Table>
        </Table.ScrollContainer>
      </Paper>

      <Title order={4} mt="md">
        {t('users.invitesTitle')}
      </Title>
      <Paper withBorder>
        <Table.ScrollContainer minWidth={780}>
        <Table verticalSpacing="sm" style={{ whiteSpace: 'nowrap' }}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('profile.fullName')}</Table.Th>
              <Table.Th>{t('login.email')}</Table.Th>
              <Table.Th>{t('users.roles')}</Table.Th>
              <Table.Th>{t('users.expiresAt')}</Table.Th>
              <Table.Th>{t('admin.status')}</Table.Th>
              <Table.Th w={60}></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loadingInvites && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed">{t('common.loading')}</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {!loadingInvites && invites.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed">{t('users.emptyInvites')}</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {invites.map((inv) => (
              <InviteRow
                key={inv.id}
                invite={inv}
                onRevoke={handleRevoke}
              />
            ))}
          </Table.Tbody>
        </Table>
        </Table.ScrollContainer>
      </Paper>

      <InviteModal opened={inviteOpen} onClose={() => setInviteOpen(false)} />
    </Stack>
  );
}

function UserEditModal({
  opened,
  onClose,
  user,
}: {
  opened: boolean;
  onClose: () => void;
  user: { id: number; email: string; full_name: string };
}) {
  const { t } = useTranslation();
  const update = useUpdateAdminUser(user.id);

  const form = useForm({
    initialValues: { full_name: user.full_name, email: user.email },
    validate: {
      full_name: (v) => (v.trim() ? null : t('common.required')),
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : t('login.invalidEmail')),
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      await update.mutateAsync({
        full_name: values.full_name.trim(),
        email: values.email.trim(),
      });
      notifications.show({ color: 'teal', message: t('admin.saved') });
      onClose();
    } catch (err) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message:
          resp?.status === 409
            ? resp?.data?.detail ?? t('users.inviteConflict')
            : resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title={t('users.editUser')} centered>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label={t('profile.fullName')}
            required
            {...form.getInputProps('full_name')}
          />
          <TextInput
            label={t('login.email')}
            required
            type="email"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            {...form.getInputProps('email')}
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={update.isPending}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function UserRow({
  user,
  isSelf,
}: {
  user: AdminUser;
  isSelf: boolean;
}) {
  const { t } = useTranslation();
  const update = useUpdateAdminUser(user.id);
  const deletePerm = useDeleteUserPermanent();
  const resetPw = useAdminResetPassword();
  const { data: roles = [] } = useRoles();
  const [editOpen, setEditOpen] = useState(false);
  const canImpersonate = usePerm('user.impersonate');
  const canResetTOTP = usePerm('user.totp.reset');
  const resetTOTP = useTOTPAdminReset();
  const qc = useQueryClient();
  const navigate = useNavigate();

  const handleDelete = async () => {
    if (!window.confirm(t('users.confirmDelete', { name: user.full_name }))) return;
    try {
      await deletePerm.mutateAsync(user.id);
      notifications.show({ color: 'teal', message: t('users.deleted') });
    } catch (err) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message:
          resp?.status === 409
            ? resp?.data?.detail ?? t('users.deleteConflict')
            : resp?.data?.detail ?? t('admin.deleteFailed'),
      });
    }
  };

  const toggle = async (next: boolean) => {
    try {
      await update.mutateAsync({ is_active: next });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  };

  const changeRoles = async (nextIds: string[]) => {
    try {
      await update.mutateAsync({
        role_ids: nextIds.map((v) => Number(v)),
      });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  };

  const handleImpersonate = async () => {
    if (!window.confirm(t('impersonate.confirm', { name: user.full_name })))
      return;
    try {
      await impersonate(user.id);
      // Invalidate every cached query so pages rerender under the
      // new identity, then bounce home. clear() would wipe
      // the queries instead of refetching them, causing observers
      // (like the banner) to briefly read stale data.
      await qc.invalidateQueries();
      navigate('/', { replace: true });
      notifications.show({
        color: 'teal',
        message: t('impersonate.started', { name: user.full_name }),
      });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('impersonate.failed'),
      });
    }
  };

  const handleResetPw = async () => {
    if (!window.confirm(t('users.confirmResetPw', { email: user.email }))) return;
    try {
      await resetPw.mutateAsync(user.id);
      notifications.show({ color: 'teal', message: t('users.resetPwSent') });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  };

  const handleResetTOTP = async () => {
    if (
      !window.confirm(t('twoFactor.adminResetConfirm', { name: user.full_name }))
    )
      return;
    try {
      await resetTOTP.mutateAsync(user.id);
      notifications.show({
        color: 'teal',
        message: t('twoFactor.adminResetSuccess'),
      });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  };

  return (
    <Table.Tr>
      <Table.Td>
        <UnstyledButton onClick={() => setEditOpen(true)}>
          <Group gap={4} wrap="nowrap">
            <Text>{user.full_name}</Text>
            <IconPencil
              size={12}
              style={{ opacity: 0.5 }}
              aria-label={t('common.edit')}
            />
          </Group>
        </UnstyledButton>
        {isSelf && (
          <Badge ml="xs" color="gray" variant="light" size="xs">
            {t('users.you')}
          </Badge>
        )}
        <UserEditModal
          opened={editOpen}
          onClose={() => setEditOpen(false)}
          user={user}
        />
      </Table.Td>
      <Table.Td>{user.email}</Table.Td>
      <Table.Td>
        <MultiSelect
          size="xs"
          value={user.role_ids.map(String)}
          onChange={changeRoles}
          data={roles.map((r) => ({ value: String(r.id), label: r.name }))}
          placeholder={t('users.rolesPlaceholder')}
          searchable
          w={220}
        />
      </Table.Td>
      <Table.Td>
        <Switch
          checked={user.is_active}
          onChange={(e) => toggle(e.currentTarget.checked)}
          disabled={isSelf}
          label={user.is_active ? t('admin.active') : t('admin.inactive')}
        />
      </Table.Td>
      <Table.Td>
        <Group gap={4} wrap="nowrap">
          {canImpersonate && !isSelf && (
            <Tooltip label={t('users.impersonateTooltip')} withArrow>
              <ActionIcon
                variant="subtle"
                color="orange"
                onClick={handleImpersonate}
                disabled={!user.is_active}
                aria-label={t('impersonate.action')}
              >
                <IconUserShield size={14} />
              </ActionIcon>
            </Tooltip>
          )}
          <Tooltip label={t('users.resetPwTooltip')} withArrow>
            <ActionIcon
              variant="subtle"
              onClick={handleResetPw}
              loading={resetPw.isPending}
              disabled={!user.is_active}
              aria-label={t('users.resetPw')}
            >
              <IconKey size={14} />
            </ActionIcon>
          </Tooltip>
          {canResetTOTP && !isSelf && (
            <Tooltip label={t('users.resetTOTPTooltip')} withArrow>
              <ActionIcon
                variant="subtle"
                color="yellow"
                onClick={handleResetTOTP}
                loading={resetTOTP.isPending}
                disabled={!user.is_active}
                aria-label={t('twoFactor.adminResetButton')}
              >
                <IconDeviceMobile size={14} />
              </ActionIcon>
            </Tooltip>
          )}
          {!isSelf && (
            <Tooltip label={t('users.deleteTooltip')} withArrow>
              <ActionIcon
                variant="subtle"
                color="red"
                onClick={handleDelete}
                loading={deletePerm.isPending}
                aria-label={t('common.delete')}
              >
                <IconTrash size={14} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}
