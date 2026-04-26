import { useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Modal,
  Paper,
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
  useEmailTemplates,
  useUpdateEmailTemplate,
  type EmailTemplate,
} from '@/hooks/useEmailTemplates';

function EditTemplateModal({
  template,
  opened,
  onClose,
}: {
  template: EmailTemplate | null;
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const update = useUpdateEmailTemplate(template?.key ?? '');
  // Initialize state directly from props on mount. The parent forces
  // this component to remount whenever `template` changes (via a key
  // prop on its render site), so useState picks up the correct
  // initial values synchronously — no useEffect-to-setState race
  // for CKEditor's async init to lose against.
  const [subject, setSubject] = useState(template?.subject ?? '');
  const [body, setBody] = useState(template?.body_html ?? '');

  if (!template) return null;

  const submit = async () => {
    try {
      await update.mutateAsync({ subject, body_html: body });
      notifications.show({ color: 'teal', message: t('emailTemplates.saved') });
      onClose();
    } catch {
      notifications.show({ color: 'red', message: t('admin.saveFailed') });
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={`${t('emailTemplates.edit')} — ${template.key}`}
    >
      <Stack>
        {template.description && (
          <Text size="sm" c="dimmed">
            {template.description}
          </Text>
        )}
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
          <Button variant="subtle" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} loading={update.isPending}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function EmailTemplatesAdmin() {
  const { t } = useTranslation();
  const { data: templates = [], isLoading } = useEmailTemplates();
  const [editing, setEditing] = useState<EmailTemplate | null>(null);

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
              <Table.Th w={60}></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isLoading && (
              <Table.Tr>
                <Table.Td colSpan={4}>
                  <Text c="dimmed">{t('common.loading')}</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {templates.map((tpl) => (
              <Table.Tr key={tpl.key}>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                  <Text ff="monospace" size="sm">
                    {tpl.key}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{tpl.subject}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {tpl.description ?? ''}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <ActionIcon variant="subtle" onClick={() => setEditing(tpl)}>
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
        // Force a full remount whenever a different template is picked.
        // That's what lets the modal's useState pull the new template's
        // subject/body synchronously on mount — no effect-to-setState
        // round-trip for CKEditor's async init to race against.
        key={editing?.key ?? 'closed'}
        template={editing}
        opened={editing !== null}
        onClose={() => setEditing(null)}
      />
    </Stack>
  );
}
