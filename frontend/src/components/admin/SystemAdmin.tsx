import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertOctagon } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import {
  useAdminAppConfig,
  useUpdateAppConfigNamespace,
  type AnnouncementLevel,
  type CaptchaProvider,
  type SystemConfig,
} from '@/hooks/useAppConfig';

const LEVEL_OPTIONS: { value: AnnouncementLevel; label: string }[] = [
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'critical', label: 'Critical' },
];

const CAPTCHA_OPTIONS: { value: CaptchaProvider; label: string }[] = [
  { value: 'none', label: 'Off' },
  { value: 'turnstile', label: 'Cloudflare Turnstile' },
  { value: 'hcaptcha', label: 'hCaptcha' },
];

// Captcha lives in the ``auth`` namespace, but operationally it
// belongs alongside the maintenance toggles. Keeping a separate
// "Auth" tab for two fields would be overkill; revisit if a
// dedicated Security tab lands.
interface AuthCaptchaPatch {
  captcha_provider: CaptchaProvider;
  captcha_site_key: string | null;
}

const EMPTY: SystemConfig = {
  maintenance_mode: false,
  maintenance_message:
    'Atrium is undergoing maintenance. Please check back in a few minutes.',
  announcement: null,
  announcement_level: 'info',
};

export function SystemAdmin() {
  const { t } = useTranslation();
  const { data, isLoading } = useAdminAppConfig();
  const update = useUpdateAppConfigNamespace<SystemConfig>('system');
  // Auth namespace mutation is keyed separately so saving captcha
  // doesn't roll the whole AuthConfig back to defaults — the PUT
  // accepts a partial since the backend re-applies model defaults.
  const updateAuth = useUpdateAppConfigNamespace<Record<string, unknown>>(
    'auth',
  );
  const initial = (data?.system as Partial<SystemConfig> | undefined) ?? {};
  const [draft, setDraft] = useState<SystemConfig>({ ...EMPTY, ...initial });

  const authInitial =
    (data?.auth as Partial<AuthCaptchaPatch> | undefined) ?? {};
  const [captcha, setCaptcha] = useState<AuthCaptchaPatch>({
    captcha_provider: authInitial.captcha_provider ?? 'none',
    captcha_site_key: authInitial.captcha_site_key ?? null,
  });

  useEffect(() => {
    if (!data?.system) return;
    const s = data.system as Partial<SystemConfig>;
    // See BrandingAdmin for the same eslint exception rationale.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({ ...EMPTY, ...s });
  }, [data]);

  useEffect(() => {
    if (!data?.auth) return;
    const a = data.auth as Partial<AuthCaptchaPatch>;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCaptcha({
      captcha_provider: a.captcha_provider ?? 'none',
      captcha_site_key: a.captcha_site_key ?? null,
    });
  }, [data]);

  const submit = async () => {
    try {
      await update.mutateAsync(draft);
      notifications.show({ color: 'teal', message: t('system.saved') });
    } catch {
      notifications.show({ color: 'red', message: t('admin.saveFailed') });
    }
  };

  const submitCaptcha = async () => {
    // Merge captcha onto the existing auth namespace so unrelated
    // fields (signup toggles, password policy) survive the PUT —
    // sending only the captcha keys would reset everything else to
    // the model default.
    const existingAuth = (data?.auth as Record<string, unknown> | undefined) ?? {};
    try {
      await updateAuth.mutateAsync({
        ...existingAuth,
        captcha_provider: captcha.captcha_provider,
        captcha_site_key: captcha.captcha_site_key,
      });
      notifications.show({ color: 'teal', message: t('captcha.saved') });
    } catch {
      notifications.show({ color: 'red', message: t('admin.saveFailed') });
    }
  };

  return (
    <Stack>
      <Title order={3}>{t('system.title')}</Title>
      <Text c="dimmed" size="sm">
        {t('system.intro')}
      </Text>
      <Paper withBorder p="md">
        <Stack>
          <Switch
            label={t('system.maintenanceMode')}
            description={t('system.maintenanceModeHelp')}
            checked={draft.maintenance_mode}
            onChange={(e) =>
              setDraft({ ...draft, maintenance_mode: e.currentTarget.checked })
            }
          />
          {draft.maintenance_mode && (
            <Alert
              color="red"
              icon={<IconAlertOctagon size={18} />}
              title={t('system.maintenanceWarningTitle')}
            >
              {t('system.maintenanceWarning')}
            </Alert>
          )}
          <Textarea
            label={t('system.maintenanceMessage')}
            value={draft.maintenance_message}
            onChange={(e) =>
              setDraft({ ...draft, maintenance_message: e.currentTarget.value })
            }
            minRows={2}
            autosize
            maxLength={500}
          />
        </Stack>
      </Paper>
      <Paper withBorder p="md">
        <Stack>
          <TextInput
            label={t('system.announcement')}
            description={t('system.announcementHelp')}
            placeholder={t('system.announcementPlaceholder')}
            value={draft.announcement ?? ''}
            onChange={(e) =>
              setDraft({
                ...draft,
                announcement:
                  e.currentTarget.value === '' ? null : e.currentTarget.value,
              })
            }
            maxLength={2000}
          />
          <Select
            label={t('system.announcementLevel')}
            data={LEVEL_OPTIONS}
            value={draft.announcement_level}
            onChange={(v) =>
              v &&
              setDraft({ ...draft, announcement_level: v as AnnouncementLevel })
            }
            allowDeselect={false}
          />
        </Stack>
      </Paper>
      <Group justify="flex-end">
        <Button onClick={submit} loading={update.isPending} disabled={isLoading}>
          {t('common.save')}
        </Button>
      </Group>
      <Title order={4} mt="md">
        {t('captcha.title')}
      </Title>
      <Text c="dimmed" size="sm">
        {t('captcha.intro')}
      </Text>
      <Paper withBorder p="md">
        <Stack>
          <Select
            label={t('captcha.provider')}
            description={t('captcha.providerHelp')}
            data={CAPTCHA_OPTIONS}
            value={captcha.captcha_provider}
            onChange={(v) =>
              v &&
              setCaptcha({
                ...captcha,
                captcha_provider: v as CaptchaProvider,
              })
            }
            allowDeselect={false}
          />
          <TextInput
            label={t('captcha.siteKey')}
            description={t('captcha.siteKeyHelp')}
            value={captcha.captcha_site_key ?? ''}
            onChange={(e) =>
              setCaptcha({
                ...captcha,
                captcha_site_key:
                  e.currentTarget.value === '' ? null : e.currentTarget.value,
              })
            }
            disabled={captcha.captcha_provider === 'none'}
            maxLength={200}
          />
          <Text c="dimmed" size="xs">
            {t('captcha.secretHint')}
          </Text>
        </Stack>
      </Paper>
      <Group justify="flex-end">
        <Button
          onClick={submitCaptcha}
          loading={updateAuth.isPending}
          disabled={isLoading}
        >
          {t('common.save')}
        </Button>
      </Group>
    </Stack>
  );
}
