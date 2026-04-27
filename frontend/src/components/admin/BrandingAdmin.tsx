// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  ColorSwatch,
  Divider,
  Grid,
  Group,
  MantineProvider,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';

import {
  useAdminAppConfig,
  useUpdateAppConfigNamespace,
  type BrandConfig,
  type ThemePreset,
} from '@/hooks/useAppConfig';
import { PRESET_OPTIONS, buildTheme, colorSchemeForPreset } from '@/theme';

const MANTINE_COLOR_OPTIONS = [
  'dark', 'gray', 'red', 'pink', 'grape', 'violet', 'indigo', 'blue',
  'cyan', 'teal', 'green', 'lime', 'yellow', 'orange',
].map((c) => ({ value: c, label: c }));

const RADIUS_OPTIONS = ['xs', 'sm', 'md', 'lg', 'xl'].map((r) => ({
  value: r,
  label: r,
}));

const SHADE_OPTIONS = Array.from({ length: 10 }, (_, i) => ({
  value: String(i),
  label: String(i),
}));

const EMPTY_BRAND: BrandConfig = {
  name: 'Atrium',
  logo_url: null,
  support_email: null,
  preset: 'default',
  overrides: {},
};

function BrandingPreview({ brand }: { brand: BrandConfig }) {
  const theme = useMemo(() => buildTheme(brand), [brand]);
  const scheme = colorSchemeForPreset(brand.preset);
  return (
    <MantineProvider theme={theme} forceColorScheme={scheme === 'dark' ? 'dark' : 'light'}>
      <Card withBorder padding="lg" radius={theme.defaultRadius}>
        <Stack gap="sm">
          <Title order={3}>{brand.name || 'Atrium'}</Title>
          <Text c="dimmed" size="sm">
            Preview of the chosen preset and overrides. Buttons, headings, and
            links use the theme below.
          </Text>
          <Group>
            <Button>Primary</Button>
            <Button variant="light">Light</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="subtle">Subtle</Button>
          </Group>
          <Group>
            {[3, 5, 7, 9].map((s) => (
              <ColorSwatch
                key={s}
                color={`var(--mantine-color-${theme.primaryColor ?? 'teal'}-${s})`}
                size={28}
              />
            ))}
          </Group>
        </Stack>
      </Card>
    </MantineProvider>
  );
}

export function BrandingAdmin() {
  const { t } = useTranslation();
  const { data, isLoading } = useAdminAppConfig();
  const update = useUpdateAppConfigNamespace<BrandConfig>('brand');

  const initial = (data?.brand as Partial<BrandConfig> | undefined) ?? {};
  const [draft, setDraft] = useState<BrandConfig>({
    ...EMPTY_BRAND,
    ...initial,
    overrides: { ...(initial.overrides ?? {}) },
  });

  // Populate the form once the GET resolves. Re-runs on data change so
  // the canonicalised values returned from a save (Pydantic
  // model_dump) propagate back into the controls without forcing a
  // remount.
  useEffect(() => {
    if (!data?.brand) return;
    const b = data.brand as Partial<BrandConfig>;
    // Form state has to mirror the server-canonicalised values that
    // come back through the same query after a save. Alternative
    // would be a key-remount per fetch, which loses focus mid-edit.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({
      ...EMPTY_BRAND,
      ...b,
      overrides: { ...(b.overrides ?? {}) },
    });
  }, [data]);

  const setOverride = (key: string, value: string) =>
    setDraft((prev) => ({
      ...prev,
      overrides: value === '' ? omit(prev.overrides, key) : { ...prev.overrides, [key]: value },
    }));

  const submit = async () => {
    try {
      await update.mutateAsync(draft);
      notifications.show({ color: 'teal', message: t('branding.saved') });
    } catch {
      notifications.show({ color: 'red', message: t('admin.saveFailed') });
    }
  };

  return (
    <Stack>
      <Title order={3}>{t('branding.title')}</Title>
      <Text c="dimmed" size="sm">
        {t('branding.intro')}
      </Text>
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Paper withBorder p="md">
            <Stack>
              <TextInput
                label={t('branding.name')}
                description={t('branding.nameHelp')}
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })}
              />
              <TextInput
                label={t('branding.logoUrl')}
                description={t('branding.logoUrlHelp')}
                placeholder="/brand/logo.svg"
                value={draft.logo_url ?? ''}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    logo_url: e.currentTarget.value === '' ? null : e.currentTarget.value,
                  })
                }
              />
              <TextInput
                label={t('branding.supportEmail')}
                placeholder="help@example.com"
                value={draft.support_email ?? ''}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    support_email: e.currentTarget.value === '' ? null : e.currentTarget.value,
                  })
                }
              />
              <Divider label={t('branding.theme')} labelPosition="left" />
              <Select
                label={t('branding.preset')}
                description={t('branding.presetHelp')}
                data={PRESET_OPTIONS}
                value={draft.preset}
                onChange={(v) => v && setDraft({ ...draft, preset: v as ThemePreset })}
                allowDeselect={false}
              />
              <Group grow>
                <Select
                  label={t('branding.primaryColor')}
                  data={MANTINE_COLOR_OPTIONS}
                  value={draft.overrides.primaryColor ?? ''}
                  onChange={(v) => setOverride('primaryColor', v ?? '')}
                  clearable
                  placeholder={t('branding.useDefault')}
                />
                <Select
                  label={t('branding.primaryShade')}
                  data={SHADE_OPTIONS}
                  value={draft.overrides.primaryShade ?? ''}
                  onChange={(v) => setOverride('primaryShade', v ?? '')}
                  clearable
                  placeholder={t('branding.useDefault')}
                />
              </Group>
              <Select
                label={t('branding.defaultRadius')}
                data={RADIUS_OPTIONS}
                value={draft.overrides.defaultRadius ?? ''}
                onChange={(v) => setOverride('defaultRadius', v ?? '')}
                clearable
                placeholder={t('branding.useDefault')}
              />
              <TextInput
                label={t('branding.fontFamily')}
                placeholder='"Inter", system-ui, sans-serif'
                value={draft.overrides.fontFamily ?? ''}
                onChange={(e) => setOverride('fontFamily', e.currentTarget.value)}
              />
              <TextInput
                label={t('branding.headingsFontFamily')}
                placeholder='"Source Serif 4", Georgia, serif'
                value={draft.overrides.headingsFontFamily ?? ''}
                onChange={(e) => setOverride('headingsFontFamily', e.currentTarget.value)}
              />
              <Group justify="flex-end" mt="sm">
                <Button onClick={submit} loading={update.isPending} disabled={isLoading}>
                  {t('common.save')}
                </Button>
              </Group>
            </Stack>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack>
            <Text size="sm" fw={500}>
              {t('branding.preview')}
            </Text>
            <BrandingPreview brand={draft} />
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}

function omit<T extends Record<string, unknown>>(obj: T, key: string): T {
  // Tiny inline helper — pulling `lodash/omit` for a four-line function
  // would inflate the bundle for no real benefit.
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(obj)) {
    if (k !== key) out[k] = obj[k];
  }
  return out as T;
}
