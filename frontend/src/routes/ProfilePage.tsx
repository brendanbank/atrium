// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { TwoFactorSetupModal } from '@/components/TwoFactorSetupModal';
import { useSelfDelete } from '@/hooks/useAccountDeletion';
import { ME_QUERY_KEY, useMe } from '@/hooks/useAuth';
import { useLogoutAll, useSessions } from '@/hooks/useSessions';
import {
  useEmailOTPDisable,
  useTOTPDisable,
  useTOTPState,
} from '@/hooks/useTOTP';
import {
  useWebAuthnCredentials,
  useWebAuthnDeleteCredential,
  useWebAuthnRegister,
} from '@/hooks/useWebAuthn';
import { updateMe, type CurrentUser, type Language } from '@/lib/auth';

export function ProfilePage() {
  const { t, i18n } = useTranslation();
  const { data: me, isLoading } = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: sessions = [] } = useSessions();
  const logoutAll = useLogoutAll();
  const { data: totpState, refetch: refetchTotpState } = useTOTPState();
  const totpDisable = useTOTPDisable();
  const emailOtpDisable = useEmailOTPDisable();
  const webauthnRegister = useWebAuthnRegister();
  const webauthnDelete = useWebAuthnDeleteCredential();
  const { data: webauthnCreds = [], refetch: refetchWebauthnCreds } =
    useWebAuthnCredentials();
  const [twoFactorModal, setTwoFactorModal] = useState<null | 'totp' | 'email'>(
    null,
  );
  const [webauthnLabel, setWebauthnLabel] = useState('');
  const [webauthnError, setWebauthnError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const selfDelete = useSelfDelete();

  const profileForm = useForm({
    initialValues: {
      full_name: '',
      phone: '',
      email: '',
      preferred_language: 'en' as Language,
    },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : t('login.invalidEmail')),
      full_name: (v) => (v.trim().length > 0 ? null : t('profile.nameRequired')),
    },
  });

  useEffect(() => {
    if (me) {
      profileForm.setValues({
        full_name: me.full_name ?? '',
        phone: me.phone ?? '',
        email: me.email,
        preferred_language: me.preferred_language,
      });
      profileForm.resetDirty({
        full_name: me.full_name ?? '',
        phone: me.phone ?? '',
        email: me.email,
        preferred_language: me.preferred_language,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.id]);

  const updateProfile = useMutation<
    CurrentUser,
    Error,
    Partial<CurrentUser>
  >({
    mutationFn: (payload) => updateMe(payload),
    onSuccess: (updated) => {
      // PATCH /users/me returns the base user shape WITHOUT roles /
      // permissions / impersonating_from (those come from
      // /users/me/context, fetched separately by fetchMe). Merge
      // onto the existing cache so consumers like AppLayout that
      // read ``me.roles`` don't see undefined after a save.
      const previous = qc.getQueryData<CurrentUser>(ME_QUERY_KEY);
      qc.setQueryData(ME_QUERY_KEY, { ...(previous ?? {}), ...updated });
      if (updated.preferred_language !== i18n.language) {
        i18n.changeLanguage(updated.preferred_language);
      }
      notifications.show({
        color: 'teal',
        message: t('profile.savedProfile'),
      });
    },
    onError: () => {
      notifications.show({
        color: 'red',
        message: t('profile.saveFailed'),
      });
    },
  });

  const passwordForm = useForm({
    initialValues: { password: '', confirm: '' },
    validate: {
      password: (v) =>
        v.length >= 8 ? null : t('acceptInvite.passwordTooShort'),
      confirm: (v, values) =>
        v === values.password ? null : t('acceptInvite.passwordMismatch'),
    },
  });

  const [changingPassword, setChangingPassword] = useState(false);
  const changePassword = passwordForm.onSubmit(async ({ password }) => {
    setChangingPassword(true);
    try {
      await updateMe({ password });
      passwordForm.reset();
      notifications.show({
        color: 'teal',
        message: t('profile.savedPassword'),
      });
    } catch {
      notifications.show({
        color: 'red',
        message: t('profile.saveFailed'),
      });
    } finally {
      setChangingPassword(false);
    }
  });

  if (isLoading) return <Loader />;
  if (!me) return <Alert color="red">{t('profile.notLoggedIn')}</Alert>;

  return (
    <Stack maw={820} gap={6}>
      <Title order={2}>{t('profile.title')}</Title>

      <Paper withBorder p="sm" radius="md">
        <form onSubmit={profileForm.onSubmit((values) => updateProfile.mutate(values))}>
          <Stack gap={6}>
            <InlineField label={t('profile.fullName')} required>
              <TextInput
                required
                {...profileForm.getInputProps('full_name')}
              />
            </InlineField>
            <InlineField label={t('profile.phone')}>
              <TextInput {...profileForm.getInputProps('phone')} />
            </InlineField>
            <InlineField label={t('login.email')} required>
              <TextInput
                required
                type="email"
                {...profileForm.getInputProps('email')}
              />
            </InlineField>
            <InlineField label={t('common.language')}>
              <Select
                data={[
                  { value: 'en', label: 'English' },
                  { value: 'nl', label: 'Nederlands (coming soon)' },
                ]}
                {...profileForm.getInputProps('preferred_language')}
              />
            </InlineField>
            <Group justify="flex-end" mt={4}>
              <Button
                type="submit"
                size="xs"
                disabled={!profileForm.isDirty()}
                loading={updateProfile.isPending}
              >
                {t('common.save')}
              </Button>
            </Group>
          </Stack>
        </form>
      </Paper>

      <Paper withBorder p="sm" radius="md">
        <Title order={5} mb={4}>
          {t('profile.changePassword')}
        </Title>
        <form onSubmit={changePassword}>
          <Stack gap={6}>
            <InlineField label={t('resetPassword.newPassword')} required>
              <PasswordInput
                required
                autoComplete="new-password"
                {...passwordForm.getInputProps('password')}
              />
            </InlineField>
            <InlineField label={t('acceptInvite.confirmPassword')} required>
              <PasswordInput
                required
                autoComplete="new-password"
                {...passwordForm.getInputProps('confirm')}
              />
            </InlineField>
            <Group justify="flex-end" mt={4}>
              <Button type="submit" size="xs" loading={changingPassword}>
                {t('profile.updatePassword')}
              </Button>
            </Group>
          </Stack>
        </form>
      </Paper>

      <Paper withBorder p="sm" radius="md">
        <Title order={5} mb={4}>
          {t('profile.twoFactorTitle')}
        </Title>
        <Stack gap="sm">
          <TwoFactorMethodRow
            label={t('profile.twoFactorTotp')}
            active={!!totpState?.confirmed}
            disableBlockedReason={
              totpState?.confirmed && !totpState?.email_otp_confirmed
                ? t('profile.twoFactorNeedsOther')
                : null
            }
            onAdd={() => setTwoFactorModal('totp')}
            onDisable={async () => {
              if (!window.confirm(t('profile.twoFactorConfirmDisable'))) return;
              try {
                await totpDisable.mutateAsync();
                notifications.show({
                  color: 'teal',
                  message: t('profile.twoFactorDisabled'),
                });
                refetchTotpState();
              } catch (err) {
                const resp = (err as { response?: { data?: { detail?: string } } })
                  .response;
                notifications.show({
                  color: 'red',
                  message: resp?.data?.detail ?? t('profile.saveFailed'),
                });
              }
            }}
            disabling={totpDisable.isPending}
          />
          <TwoFactorMethodRow
            label={t('profile.twoFactorEmail')}
            active={!!totpState?.email_otp_confirmed}
            disableBlockedReason={
              totpState?.email_otp_confirmed && !totpState?.confirmed
                ? t('profile.twoFactorNeedsOther')
                : null
            }
            onAdd={() => setTwoFactorModal('email')}
            onDisable={async () => {
              if (!window.confirm(t('profile.twoFactorConfirmDisable'))) return;
              try {
                await emailOtpDisable.mutateAsync();
                notifications.show({
                  color: 'teal',
                  message: t('profile.twoFactorDisabled'),
                });
                refetchTotpState();
              } catch (err) {
                const resp = (err as { response?: { data?: { detail?: string } } })
                  .response;
                notifications.show({
                  color: 'red',
                  message: resp?.data?.detail ?? t('profile.saveFailed'),
                });
              }
            }}
            disabling={emailOtpDisable.isPending}
          />
        </Stack>

        <Text size="sm" fw={500} mt="md" mb={4}>
          {t('profile.webauthnTitle')}
        </Text>
        <Stack gap={4}>
          {webauthnCreds.length === 0 ? (
            <Text size="xs" c="dimmed">
              {t('profile.webauthnNone')}
            </Text>
          ) : (
            webauthnCreds.map((c) => (
              <Group key={c.id} justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap">
                  <Text size="sm">{c.label}</Text>
                  {c.last_used_at ? (
                    <Text size="xs" c="dimmed">
                      {t('profile.webauthnLastUsed', {
                        when: new Date(c.last_used_at).toLocaleDateString(),
                      })}
                    </Text>
                  ) : (
                    <Text size="xs" c="dimmed">
                      {t('profile.webauthnNeverUsed')}
                    </Text>
                  )}
                </Group>
                <Button
                  variant="subtle"
                  color="red"
                  size="xs"
                  loading={
                    webauthnDelete.isPending &&
                    webauthnDelete.variables === c.id
                  }
                  onClick={async () => {
                    if (
                      !window.confirm(
                        t('profile.webauthnConfirmDelete', { label: c.label }),
                      )
                    )
                      return;
                    try {
                      await webauthnDelete.mutateAsync(c.id);
                      notifications.show({
                        color: 'teal',
                        message: t('profile.webauthnDeleted'),
                      });
                      refetchWebauthnCreds();
                      refetchTotpState();
                    } catch (err) {
                      const resp = (err as {
                        response?: { data?: { detail?: string } };
                      }).response;
                      notifications.show({
                        color: 'red',
                        message: resp?.data?.detail ?? t('profile.saveFailed'),
                      });
                    }
                  }}
                >
                  {t('profile.twoFactorDisable')}
                </Button>
              </Group>
            ))
          )}
          <Group gap="xs" mt={4} align="center">
            <TextInput
              size="xs"
              placeholder={t('twoFactor.webauthnLabelPlaceholder')}
              value={webauthnLabel}
              onChange={(e) => setWebauthnLabel(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <Button
              size="xs"
              variant="light"
              loading={webauthnRegister.isPending}
              disabled={webauthnLabel.trim().length === 0}
              onClick={async () => {
                setWebauthnError(null);
                try {
                  await webauthnRegister.mutateAsync(webauthnLabel.trim());
                  notifications.show({
                    color: 'teal',
                    message: t('twoFactor.webauthnRegistered'),
                  });
                  setWebauthnLabel('');
                  refetchWebauthnCreds();
                  refetchTotpState();
                } catch (err) {
                  setWebauthnError(
                    (err as Error)?.message ?? t('twoFactor.webauthnFailed'),
                  );
                }
              }}
            >
              {t('profile.webauthnAdd')}
            </Button>
          </Group>
          {webauthnError && (
            <Alert color="red" mt={4}>
              {webauthnError}
            </Alert>
          )}
        </Stack>
      </Paper>

      <TwoFactorSetupModal
        opened={twoFactorModal !== null}
        method={twoFactorModal ?? 'totp'}
        onClose={() => setTwoFactorModal(null)}
        onEnrolled={() => refetchTotpState()}
      />

      <RolesSummary roles={me.roles} />

      <Paper withBorder p="sm" radius="md">
        <Title order={5} mb={4}>
          {t('profile.sessionsTitle')}
        </Title>
        {sessions.length === 0 ? (
          <Text c="dimmed" size="sm">
            {t('profile.noOtherSessions')}
          </Text>
        ) : (
          <Table striped withTableBorder verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('profile.sessionDevice')}</Table.Th>
                <Table.Th>{t('profile.sessionIssued')}</Table.Th>
                <Table.Th>{t('profile.sessionExpires')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sessions.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td>
                    <Text size="sm" lineClamp={1}>
                      {s.user_agent ?? '—'}
                    </Text>
                    {s.ip ? (
                      <Text size="xs" c="dimmed">
                        {s.ip}
                      </Text>
                    ) : null}
                  </Table.Td>
                  <Table.Td>{new Date(s.issued_at).toLocaleString()}</Table.Td>
                  <Table.Td>{new Date(s.expires_at).toLocaleString()}</Table.Td>
                  <Table.Td>
                    {s.is_current ? (
                      <Badge color="teal" variant="light">
                        {t('profile.sessionCurrent')}
                      </Badge>
                    ) : null}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        <Group justify="flex-end" mt="md">
          <Button
            color="red"
            variant="light"
            loading={logoutAll.isPending}
            onClick={() => {
              if (!window.confirm(t('profile.confirmLogoutAll'))) return;
              logoutAll.mutate(undefined, {
                onSuccess: () => {
                  notifications.show({
                    color: 'teal',
                    message: t('profile.loggedOutAll'),
                  });
                  navigate('/login', { replace: true });
                },
                onError: () => {
                  notifications.show({
                    color: 'red',
                    message: t('profile.saveFailed'),
                  });
                },
              });
            }}
          >
            {t('profile.logoutAll')}
          </Button>
        </Group>
      </Paper>

      <Paper withBorder p="sm" radius="md">
        <Title order={5} mb={4}>
          {t('profile.deleteAccountTitle')}
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          {t('profile.deleteAccountIntro')}
        </Text>
        <Group justify="flex-end">
          <Button
            color="red"
            variant="light"
            onClick={() => {
              setDeleteError(null);
              setDeletePassword('');
              setDeleteOpen(true);
            }}
          >
            {t('profile.deleteAccountButton')}
          </Button>
        </Group>
      </Paper>

      <Modal
        opened={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        title={t('profile.deleteAccountModalTitle')}
        centered
      >
        <Stack gap="sm">
          <Text size="sm">{t('profile.deleteAccountModalIntro')}</Text>
          <PasswordInput
            label={t('login.password')}
            value={deletePassword}
            onChange={(e) => setDeletePassword(e.currentTarget.value)}
            autoComplete="current-password"
          />
          {deleteError ? <Alert color="red">{deleteError}</Alert> : null}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleteOpen(false)}>
              {t('profile.deleteAccountCancel')}
            </Button>
            <Button
              color="red"
              loading={selfDelete.isPending}
              disabled={deletePassword.length === 0}
              onClick={async () => {
                setDeleteError(null);
                try {
                  await selfDelete.mutateAsync({ password: deletePassword });
                  setDeleteOpen(false);
                  navigate('/login?deleted=1', { replace: true });
                } catch (err) {
                  const status = (err as { response?: { status?: number } })
                    .response?.status;
                  setDeleteError(
                    status === 401
                      ? t('profile.deleteAccountWrongPassword')
                      : t('profile.deleteAccountFailed'),
                  );
                }
              }}
            >
              {t('profile.deleteAccountConfirm')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}


/** Wraps any input in a two-column row: label on the left, input on
 * the right. Keeps the profile dense without stacking every label. */
function InlineField({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  // ``display: flex`` with ``align-items: center`` keeps the label
  // baseline-aligned with the input across TextInput / PasswordInput
  // / Select variants. ``min-width: 0`` on the child wrapper is what
  // actually makes the input shrink to its flex share in a tight
  // viewport — without it, long placeholders push the whole row out.
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--mantine-spacing-sm)',
      }}
    >
      <div
        style={{
          width: 140,
          flexShrink: 0,
          fontSize: 'var(--mantine-font-size-sm)',
          fontWeight: 500,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
        {required ? (
          <span style={{ color: 'var(--mantine-color-red-6)' }}> *</span>
        ) : null}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  );
}


/** Read-only summary of the RBAC roles the current user holds.
 *  Roles are managed by an admin via the Users admin tab. */
function RolesSummary({ roles }: { roles: string[] }) {
  const { t } = useTranslation();
  return (
    <Paper withBorder p="sm" radius="md">
      <Title order={5} mb={4}>
        {t('profile.rolesTitle')}
      </Title>
      {roles.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t('profile.rolesEmpty')}
        </Text>
      ) : (
        <Group gap={6}>
          {roles.map((r) => (
            <Badge key={r} variant="light" color="blue">
              {r}
            </Badge>
          ))}
        </Group>
      )}
    </Paper>
  );
}


function TwoFactorMethodRow({
  label,
  active,
  disableBlockedReason,
  onAdd,
  onDisable,
  disabling,
}: {
  label: string;
  active: boolean;
  /** If set, the "Disable" button is shown but disabled with this
   * tooltip — disabling would leave the user with zero 2FA methods.
   * If null, disabling is OK. */
  disableBlockedReason: string | null;
  onAdd: () => void;
  onDisable: () => void;
  disabling: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Group justify="space-between" wrap="nowrap">
      <Group gap="sm">
        <Text fw={500}>{label}</Text>
        <Badge color={active ? 'teal' : 'gray'} variant="light">
          {active ? t('profile.twoFactorActive') : t('profile.twoFactorNotSet')}
        </Badge>
      </Group>
      {active ? (
        <Button
          variant="subtle"
          color="red"
          size="xs"
          loading={disabling}
          disabled={disableBlockedReason !== null}
          title={disableBlockedReason ?? undefined}
          onClick={onDisable}
        >
          {t('profile.twoFactorDisable')}
        </Button>
      ) : (
        <Button variant="light" size="xs" onClick={onAdd}>
          {t('profile.twoFactorAdd')}
        </Button>
      )}
    </Group>
  );
}
