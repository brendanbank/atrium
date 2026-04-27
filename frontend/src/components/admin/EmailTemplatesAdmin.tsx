// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo, useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconEdit } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { CKEditorField } from '@/components/CKEditorField';
import {
  useEmailTemplate,
  useEmailTemplates,
  useUpdateEmailTemplate,
  type EmailTemplate,
} from '@/hooks/useEmailTemplates';
import { useAppConfig } from '@/hooks/useAppConfig';

const FALLBACK_LOCALES = ['en'];

/** Inner editor — keyed on (templateKey, locale) so when the user
 * switches locales the parent remounts this child and useState picks
 * up the freshly-loaded subject/body synchronously, avoiding the
 * effect-to-setState race CKEditor's async init would lose against. */
function VariantEditor({
  initial,
  templateKey,
  locale,
  onSaved,
  onCancel,
}: {
  initial: EmailTemplate;
  templateKey: string;
  locale: string;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const update = useUpdateEmailTemplate(templateKey, locale);
  const [subject, setSubject] = useState(initial.subject);
  const [body, setBody] = useState(initial.body_html);

  const submit = async () => {
    try {
      await update.mutateAsync({ subject, body_html: body });
      notifications.show({ color: 'teal', message: t('emailTemplates.saved') });
      onSaved();
    } catch {
      notifications.show({ color: 'red', message: t('admin.saveFailed') });
    }
  };

  return (
    <>
      <TextInput
        label={t('emailTemplates.subject')}
        value={subject}
        onChange={(e) => setSubject(e.currentTarget.value)}
      />
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          {t('emailTemplates.body')}
        </Text>
        <CKEditorField value={body} onChange={setBody} />
        <Text size="xs" c="dimmed">
          {t('emailTemplates.jinjaHint')}
        </Text>
      </Stack>
      <Group justify="flex-end">
        <Button variant="subtle" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button onClick={submit} loading={update.isPending}>
          {t('common.save')}
        </Button>
      </Group>
    </>
  );
}

function EditTemplateModal({
  templateKey,
  description,
  enabledLocales,
  opened,
  onClose,
}: {
  templateKey: string | null;
  description: string | null;
  enabledLocales: string[];
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [locale, setLocale] = useState(enabledLocales[0] ?? 'en');
  const variant = useEmailTemplate(templateKey, locale);

  if (!templateKey) return null;

  const missing = !variant.isLoading && variant.isError;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={`${t('emailTemplates.edit')} - ${templateKey}`}
    >
      <Stack>
        {description && (
          <Text size="sm" c="dimmed">
            {description}
          </Text>
        )}
        {enabledLocales.length > 1 && (
          <Group gap="xs" align="center">
            <Text size="sm" fw={500}>
              {t('emailTemplates.locale')}
            </Text>
            <SegmentedControl
              size="xs"
              value={locale}
              onChange={setLocale}
              data={enabledLocales.map((l) => ({ value: l, label: l }))}
            />
          </Group>
        )}
        {variant.isLoading && (
          <Text c="dimmed" size="sm">
            {t('common.loading')}
          </Text>
        )}
        {missing && (
          <Text c="dimmed" size="sm">
            {t('emailTemplates.localeMissing')}
          </Text>
        )}
        {variant.data && (
          <VariantEditor
            // Key remounts the editor on locale change so useState's
            // initializer pulls the new variant body synchronously.
            key={locale}
            initial={variant.data}
            templateKey={templateKey}
            locale={locale}
            onSaved={onClose}
            onCancel={onClose}
          />
        )}
      </Stack>
    </Modal>
  );
}

interface GroupedTemplate {
  key: string;
  description: string | null;
  defaultSubject: string;
  locales: string[];
}

function groupByKey(rows: EmailTemplate[]): GroupedTemplate[] {
  const byKey = new Map<string, GroupedTemplate>();
  for (const row of rows) {
    let group = byKey.get(row.key);
    if (!group) {
      group = {
        key: row.key,
        description: row.description,
        defaultSubject: row.subject,
        locales: [],
      };
      byKey.set(row.key, group);
    }
    group.locales.push(row.locale);
    // Description and subject preview default to the EN row when one
    // exists; otherwise just take the first row in iteration order.
    if (row.locale === 'en') {
      group.description = row.description;
      group.defaultSubject = row.subject;
    }
  }
  return Array.from(byKey.values()).sort((a, b) =>
    a.key.localeCompare(b.key),
  );
}

export function EmailTemplatesAdmin() {
  const { t } = useTranslation();
  const { data: templates = [], isLoading } = useEmailTemplates();
  const { data: appConfig } = useAppConfig();
  const enabledLocales = appConfig?.i18n?.enabled_locales ?? FALLBACK_LOCALES;
  const [editing, setEditing] = useState<GroupedTemplate | null>(null);

  const grouped = useMemo(() => groupByKey(templates), [templates]);

  return (
    <Stack>
      <Title order={3}>{t('emailTemplates.title')}</Title>
      <Paper withBorder>
        <Table.ScrollContainer minWidth={720}>
          <Table verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('emailTemplates.key')}</Table.Th>
                <Table.Th>{t('emailTemplates.subject')}</Table.Th>
                <Table.Th>{t('emailTemplates.description')}</Table.Th>
                <Table.Th>{t('emailTemplates.locales')}</Table.Th>
                <Table.Th w={60}></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {isLoading && (
                <Table.Tr>
                  <Table.Td colSpan={5}>
                    <Text c="dimmed">{t('common.loading')}</Text>
                  </Table.Td>
                </Table.Tr>
              )}
              {grouped.map((tpl) => (
                <Table.Tr key={tpl.key}>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>
                    <Text ff="monospace" size="sm">
                      {tpl.key}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{tpl.defaultSubject}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {tpl.description ?? ''}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" ff="monospace" c="dimmed">
                      {tpl.locales.sort().join(', ')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      variant="subtle"
                      onClick={() => setEditing(tpl)}
                    >
                      <IconEdit size={14} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
      <EditTemplateModal
        // Force a full remount whenever a different template is
        // picked. The modal's locale state then resets to the first
        // enabled locale, and the variant query refetches under the
        // new (key, locale) pair without an effect-to-state shuffle.
        key={editing?.key ?? 'closed'}
        templateKey={editing?.key ?? null}
        description={editing?.description ?? null}
        enabledLocales={enabledLocales}
        opened={editing !== null}
        onClose={() => setEditing(null)}
      />
    </Stack>
  );
}
