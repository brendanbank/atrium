// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  NumberInput,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useEmailTemplates } from '@/hooks/useEmailTemplates';
import {
  useCreateReminderRule,
  useDeleteReminderRule,
  useReminderRules,
  useUpdateReminderRule,
  type ReminderRule,
  type ReminderRulePayload,
} from '@/hooks/useReminderRules';

function RuleFormModal({
  rule,
  opened,
  onClose,
}: {
  rule: ReminderRule | null;
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { data: templates = [] } = useEmailTemplates();
  const create = useCreateReminderRule();
  const update = useUpdateReminderRule(rule?.id ?? 0);

  const form = useForm<ReminderRulePayload>({
    initialValues: {
      name: '',
      template_key: '',
      kind: '',
      anchor: '',
      days_offset: 0,
      active: true,
    },
    validate: {
      name: (v) => (v.trim() ? null : t('common.required')),
      template_key: (v) => (v ? null : t('common.required')),
      anchor: (v) => (v.trim() ? null : t('common.required')),
    },
  });

  useEffect(() => {
    if (opened) {
      if (rule) {
        form.setValues({
          name: rule.name,
          template_key: rule.template_key,
          kind: rule.kind,
          anchor: rule.anchor,
          days_offset: rule.days_offset,
          active: rule.active,
        });
      } else {
        form.reset();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, rule?.id]);

  const submit = form.onSubmit(async (values) => {
    try {
      if (rule) await update.mutateAsync(values);
      else await create.mutateAsync(values);
      notifications.show({ color: 'teal', message: t('reminders.saved') });
      onClose();
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  });

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={rule ? t('reminders.editTitle') : t('reminders.newTitle')}
      centered
    >
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label={t('reminders.name')}
            required
            {...form.getInputProps('name')}
          />
          <Select
            label={t('reminders.template')}
            required
            data={templates.map((t_) => ({ value: t_.key, label: t_.key }))}
            searchable
            {...form.getInputProps('template_key')}
          />
          <TextInput
            label={t('reminders.kind')}
            description={t('reminders.kindHelp')}
            {...form.getInputProps('kind')}
          />
          <TextInput
            label={t('reminders.anchor')}
            required
            description={t('reminders.anchorHelp')}
            {...form.getInputProps('anchor')}
          />
          <NumberInput
            label={t('reminders.daysOffset')}
            description={t('reminders.daysOffsetHelp')}
            min={-365}
            max={365}
            {...form.getInputProps('days_offset')}
          />
          <Switch
            label={t('reminders.active')}
            {...form.getInputProps('active', { type: 'checkbox' })}
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={create.isPending || update.isPending}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

export function RemindersAdmin() {
  const { t } = useTranslation();
  const { data: rules = [], isLoading } = useReminderRules();
  const delRule = useDeleteReminderRule();
  const [editing, setEditing] = useState<ReminderRule | null>(null);
  const [newOpen, setNewOpen] = useState(false);

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('reminders.title')}</Title>
        <Button
          leftSection={<IconPlus size={14} />}
          onClick={() => setNewOpen(true)}
        >
          {t('reminders.newTitle')}
        </Button>
      </Group>

      <Paper withBorder>
        <Table.ScrollContainer minWidth={760}>
        <Table verticalSpacing="sm" style={{ whiteSpace: 'nowrap' }}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('reminders.name')}</Table.Th>
              <Table.Th>{t('reminders.template')}</Table.Th>
              <Table.Th>{t('reminders.anchor')}</Table.Th>
              <Table.Th>{t('reminders.daysOffset')}</Table.Th>
              <Table.Th>{t('reminders.active')}</Table.Th>
              <Table.Th w={80}></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isLoading && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed">{t('common.loading')}</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {rules.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>{r.name}</Table.Td>
                <Table.Td>
                  <Text ff="monospace" size="sm">
                    {r.template_key}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text ff="monospace" size="sm">{r.anchor}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {r.days_offset > 0 ? '+' : ''}
                    {r.days_offset}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge color={r.active ? 'teal' : 'gray'} variant="light">
                    {r.active ? t('admin.active') : t('admin.inactive')}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <ActionIcon variant="subtle" onClick={() => setEditing(r)}>
                      <IconEdit size={14} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      onClick={() => {
                        if (window.confirm(t('reminders.confirmDelete', { name: r.name }))) {
                          delRule.mutate(r.id);
                        }
                      }}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        </Table.ScrollContainer>
      </Paper>

      <RuleFormModal
        rule={editing}
        opened={editing !== null}
        onClose={() => setEditing(null)}
      />
      <RuleFormModal
        rule={null}
        opened={newOpen}
        onClose={() => setNewOpen(false)}
      />
    </Stack>
  );
}
