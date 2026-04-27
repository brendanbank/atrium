// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

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
  type SystemConfig,
} from '@/hooks/useAppConfig';

const LEVEL_OPTIONS: { value: AnnouncementLevel; label: string }[] = [
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'critical', label: 'Critical' },
];

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
  const initial = (data?.system as Partial<SystemConfig> | undefined) ?? {};
  const [draft, setDraft] = useState<SystemConfig>({ ...EMPTY, ...initial });

  useEffect(() => {
    if (!data?.system) return;
    const s = data.system as Partial<SystemConfig>;
    // See BrandingAdmin for the same eslint exception rationale.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({ ...EMPTY, ...s });
  }, [data]);

  const submit = async () => {
    try {
      await update.mutateAsync(draft);
      notifications.show({ color: 'teal', message: t('system.saved') });
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
          <Switch
            label={t('system.announcementEnabled')}
            description={t('system.announcementEnabledHelp')}
            checked={draft.announcement !== null}
            onChange={(e) =>
              setDraft({
                ...draft,
                announcement: e.currentTarget.checked ? '' : null,
              })
            }
          />
          {draft.announcement !== null && (
            <>
              <TextInput
                label={t('system.announcement')}
                placeholder={t('system.announcementPlaceholder')}
                value={draft.announcement}
                onChange={(e) =>
                  setDraft({ ...draft, announcement: e.currentTarget.value })
                }
                maxLength={2000}
              />
              <Select
                label={t('system.announcementLevel')}
                data={LEVEL_OPTIONS}
                value={draft.announcement_level}
                onChange={(v) =>
                  v &&
                  setDraft({
                    ...draft,
                    announcement_level: v as AnnouncementLevel,
                  })
                }
                allowDeselect={false}
              />
            </>
          )}
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
