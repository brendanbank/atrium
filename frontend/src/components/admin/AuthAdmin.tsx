// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Group,
  MultiSelect,
  NumberInput,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';

import {
  useAdminAppConfig,
  useUpdateAppConfigNamespace,
  type AuthConfig,
  type CaptchaProvider,
} from '@/hooks/useAppConfig';
import { useRoles } from '@/hooks/useRolesAdmin';

const CAPTCHA_OPTIONS: { value: CaptchaProvider; label: string }[] = [
  { value: 'none', label: 'Off' },
  { value: 'turnstile', label: 'Cloudflare Turnstile' },
  { value: 'hcaptcha', label: 'hCaptcha' },
];

const EMPTY: AuthConfig = {
  allow_self_delete: true,
  delete_grace_days: 30,
  allow_signup: false,
  signup_default_role_code: 'user',
  require_email_verification: true,
  password_min_length: 8,
  password_require_mixed_case: false,
  password_require_digit: false,
  password_require_symbol: false,
  password_check_breach: false,
  require_2fa_for_roles: [],
  captcha_provider: 'none',
  captcha_site_key: null,
};

export function AuthAdmin() {
  const { t } = useTranslation();
  const { data, isLoading } = useAdminAppConfig();
  const { data: roles = [] } = useRoles();
  const update = useUpdateAppConfigNamespace<AuthConfig>('auth');

  const initial = (data?.auth as Partial<AuthConfig> | undefined) ?? {};
  const [draft, setDraft] = useState<AuthConfig>({ ...EMPTY, ...initial });

  useEffect(() => {
    if (!data?.auth) return;
    const a = data.auth as Partial<AuthConfig>;
    // Form state has to mirror the server-canonicalised values that
    // come back through the same query after a save. Same eslint
    // exception rationale as BrandingAdmin / SystemAdmin.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({ ...EMPTY, ...a });
  }, [data]);

  const roleOptions = useMemo(
    () =>
      roles.map((r) => ({
        value: r.code,
        label: `${r.name} (${r.code})`,
      })),
    [roles],
  );

  const submit = async () => {
    try {
      await update.mutateAsync(draft);
      notifications.show({ color: 'teal', message: t('authAdmin.saved') });
    } catch {
      notifications.show({ color: 'red', message: t('admin.saveFailed') });
    }
  };

  return (
    <Stack>
      <Title order={3}>{t('authAdmin.title')}</Title>
      <Text c="dimmed" size="sm">
        {t('authAdmin.intro')}
      </Text>

      <Paper withBorder p="md">
        <Stack>
          <Title order={4}>{t('authAdmin.signupTitle')}</Title>
          <Switch
            label={t('authAdmin.allowSignup')}
            description={t('authAdmin.allowSignupHelp')}
            checked={draft.allow_signup}
            onChange={(e) =>
              setDraft({ ...draft, allow_signup: e.currentTarget.checked })
            }
          />
          <Switch
            label={t('authAdmin.requireEmailVerification')}
            description={t('authAdmin.requireEmailVerificationHelp')}
            checked={draft.require_email_verification}
            onChange={(e) =>
              setDraft({
                ...draft,
                require_email_verification: e.currentTarget.checked,
              })
            }
          />
          <Select
            label={t('authAdmin.signupDefaultRole')}
            description={t('authAdmin.signupDefaultRoleHelp')}
            data={roleOptions}
            value={draft.signup_default_role_code}
            onChange={(v) =>
              v && setDraft({ ...draft, signup_default_role_code: v })
            }
            allowDeselect={false}
            searchable
            disabled={!draft.allow_signup}
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md">
        <Stack>
          <Title order={4}>{t('authAdmin.twoFactorTitle')}</Title>
          <Text c="dimmed" size="sm">
            {t('authAdmin.twoFactorIntro')}
          </Text>
          <MultiSelect
            label={t('authAdmin.require2faForRoles')}
            description={t('authAdmin.require2faForRolesHelp')}
            data={roleOptions}
            value={draft.require_2fa_for_roles}
            onChange={(v) =>
              setDraft({ ...draft, require_2fa_for_roles: v })
            }
            placeholder={t('authAdmin.require2faPlaceholder')}
            searchable
            clearable
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md">
        <Stack>
          <Title order={4}>{t('authAdmin.passwordTitle')}</Title>
          <NumberInput
            label={t('authAdmin.passwordMinLength')}
            description={t('authAdmin.passwordMinLengthHelp')}
            value={draft.password_min_length}
            onChange={(v) =>
              setDraft({
                ...draft,
                password_min_length:
                  typeof v === 'number' ? v : Number(v) || 8,
              })
            }
            min={6}
            max={128}
          />
          <Switch
            label={t('authAdmin.passwordMixedCase')}
            checked={draft.password_require_mixed_case}
            onChange={(e) =>
              setDraft({
                ...draft,
                password_require_mixed_case: e.currentTarget.checked,
              })
            }
          />
          <Switch
            label={t('authAdmin.passwordDigit')}
            checked={draft.password_require_digit}
            onChange={(e) =>
              setDraft({
                ...draft,
                password_require_digit: e.currentTarget.checked,
              })
            }
          />
          <Switch
            label={t('authAdmin.passwordSymbol')}
            checked={draft.password_require_symbol}
            onChange={(e) =>
              setDraft({
                ...draft,
                password_require_symbol: e.currentTarget.checked,
              })
            }
          />
          <Switch
            label={t('authAdmin.passwordBreach')}
            description={t('authAdmin.passwordBreachHelp')}
            checked={draft.password_check_breach}
            onChange={(e) =>
              setDraft({
                ...draft,
                password_check_breach: e.currentTarget.checked,
              })
            }
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md">
        <Stack>
          <Title order={4}>{t('authAdmin.deleteTitle')}</Title>
          <Switch
            label={t('authAdmin.allowSelfDelete')}
            description={t('authAdmin.allowSelfDeleteHelp')}
            checked={draft.allow_self_delete}
            onChange={(e) =>
              setDraft({
                ...draft,
                allow_self_delete: e.currentTarget.checked,
              })
            }
          />
          <NumberInput
            label={t('authAdmin.deleteGraceDays')}
            description={t('authAdmin.deleteGraceDaysHelp')}
            value={draft.delete_grace_days}
            onChange={(v) =>
              setDraft({
                ...draft,
                delete_grace_days:
                  typeof v === 'number' ? v : Number(v) || 0,
              })
            }
            min={0}
            max={365}
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md">
        <Stack>
          <Title order={4}>{t('captcha.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('captcha.intro')}
          </Text>
          <Select
            label={t('captcha.provider')}
            description={t('captcha.providerHelp')}
            data={CAPTCHA_OPTIONS}
            value={draft.captcha_provider}
            onChange={(v) =>
              v &&
              setDraft({
                ...draft,
                captcha_provider: v as CaptchaProvider,
              })
            }
            allowDeselect={false}
          />
          <TextInput
            label={t('captcha.siteKey')}
            description={t('captcha.siteKeyHelp')}
            value={draft.captcha_site_key ?? ''}
            onChange={(e) =>
              setDraft({
                ...draft,
                captcha_site_key:
                  e.currentTarget.value === '' ? null : e.currentTarget.value,
              })
            }
            disabled={draft.captcha_provider === 'none'}
            maxLength={200}
          />
          <Text c="dimmed" size="xs">
            {t('captcha.secretHint')}
          </Text>
        </Stack>
      </Paper>

      <Group justify="flex-end">
        <Button onClick={submit} loading={update.isPending} disabled={isLoading}>
          {t('common.save')}
        </Button>
      </Group>
    </Stack>
  );
}
