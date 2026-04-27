// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Group,
  MultiSelect,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';

import enBundle from '@/i18n/locales/en.json';
import {
  useAdminAppConfig,
  useUpdateAppConfigNamespace,
  type I18nConfig,
} from '@/hooks/useAppConfig';

const SUPPORTED_LOCALES: { value: string; label: string }[] = [
  { value: 'en', label: 'English (EN)' },
  { value: 'nl', label: 'Nederlands (NL)' },
  { value: 'de', label: 'Deutsch (DE)' },
  { value: 'fr', label: 'Français (FR)' },
];

const EMPTY_I18N: I18nConfig = {
  enabled_locales: ['en', 'nl'],
  overrides: {},
};

function flattenKeys(
  obj: Record<string, unknown>,
  prefix = '',
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.assign(out, flattenKeys(value as Record<string, unknown>, path));
    } else if (typeof value === 'string') {
      out[path] = value;
    }
  }
  return out;
}

const FLAT_EN = flattenKeys(enBundle as Record<string, unknown>);
const ALL_KEYS = Object.keys(FLAT_EN).sort();

export function TranslationsAdmin() {
  const { t } = useTranslation();
  const { data, isLoading } = useAdminAppConfig();
  const update = useUpdateAppConfigNamespace<I18nConfig>('i18n');

  const initial = (data?.i18n as Partial<I18nConfig> | undefined) ?? {};
  const [draft, setDraft] = useState<I18nConfig>({
    enabled_locales:
      initial.enabled_locales && initial.enabled_locales.length > 0
        ? initial.enabled_locales
        : EMPTY_I18N.enabled_locales,
    overrides: { ...(initial.overrides ?? {}) },
  });
  const [activeLocale, setActiveLocale] = useState<string>(
    initial.enabled_locales?.[0] ?? 'en',
  );
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (!data?.i18n) return;
    const cfg = data.i18n as Partial<I18nConfig>;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({
      enabled_locales:
        cfg.enabled_locales && cfg.enabled_locales.length > 0
          ? cfg.enabled_locales
          : EMPTY_I18N.enabled_locales,
      overrides: { ...(cfg.overrides ?? {}) },
    });
  }, [data]);

  useEffect(() => {
    if (!draft.enabled_locales.includes(activeLocale)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveLocale(draft.enabled_locales[0] ?? 'en');
    }
  }, [draft.enabled_locales, activeLocale]);

  const localeOverrides = useMemo(
    () => draft.overrides[activeLocale] ?? {},
    [draft.overrides, activeLocale],
  );

  const filteredKeys = useMemo(() => {
    if (!search.trim()) return ALL_KEYS;
    const needle = search.trim().toLowerCase();
    return ALL_KEYS.filter(
      (k) =>
        k.toLowerCase().includes(needle) ||
        FLAT_EN[k].toLowerCase().includes(needle),
    );
  }, [search]);

  const setOverride = (locale: string, key: string, value: string) => {
    setDraft((prev) => {
      const nextLocale = { ...(prev.overrides[locale] ?? {}) };
      if (value === '') {
        delete nextLocale[key];
      } else {
        nextLocale[key] = value;
      }
      const nextOverrides = { ...prev.overrides };
      if (Object.keys(nextLocale).length === 0) {
        delete nextOverrides[locale];
      } else {
        nextOverrides[locale] = nextLocale;
      }
      return { ...prev, overrides: nextOverrides };
    });
  };

  const submit = async () => {
    try {
      await update.mutateAsync(draft);
      notifications.show({
        color: 'teal',
        message: `${t('translations.saved')} — ${t('translations.reloadHint')}`,
      });
    } catch {
      notifications.show({ color: 'red', message: t('admin.saveFailed') });
    }
  };

  return (
    <Stack>
      <Title order={3}>{t('translations.title')}</Title>
      <Text c="dimmed" size="sm">
        {t('translations.intro')}
      </Text>

      <Paper withBorder p="md">
        <Stack>
          <MultiSelect
            label={t('translations.enabledLocales')}
            description={t('translations.enabledLocalesHelp')}
            data={SUPPORTED_LOCALES}
            value={draft.enabled_locales}
            onChange={(v) =>
              setDraft((prev) => ({
                ...prev,
                enabled_locales: v.length > 0 ? v : ['en'],
              }))
            }
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md">
        <Stack>
          <Group grow>
            <Select
              label={t('translations.locale')}
              data={draft.enabled_locales.map((code) => ({
                value: code,
                label:
                  SUPPORTED_LOCALES.find((s) => s.value === code)?.label ??
                  code.toUpperCase(),
              }))}
              value={activeLocale}
              onChange={(v) => v && setActiveLocale(v)}
              allowDeselect={false}
            />
            <TextInput
              label={t('translations.key')}
              placeholder={t('translations.searchPlaceholder')}
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
            />
          </Group>

          <Table.ScrollContainer minWidth={720}>
            <Table verticalSpacing="xs" striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th style={{ width: '28%' }}>
                    {t('translations.key')}
                  </Table.Th>
                  <Table.Th style={{ width: '36%' }}>
                    {t('translations.default')}
                  </Table.Th>
                  <Table.Th>{t('translations.override')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filteredKeys.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={3}>
                      <Text c="dimmed" size="sm">
                        {t('translations.noKeys')}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                )}
                {filteredKeys.map((key) => (
                  <Table.Tr key={key}>
                    <Table.Td>
                      <Text ff="monospace" size="xs">
                        {key}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c="dimmed">
                        {FLAT_EN[key]}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <TextInput
                        size="xs"
                        value={localeOverrides[key] ?? ''}
                        onChange={(e) =>
                          setOverride(activeLocale, key, e.currentTarget.value)
                        }
                        placeholder={FLAT_EN[key]}
                      />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>

          <Group justify="flex-end">
            <Button onClick={submit} loading={update.isPending} disabled={isLoading}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </Paper>
    </Stack>
  );
}
