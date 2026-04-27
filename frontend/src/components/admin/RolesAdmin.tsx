// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import {
  useCreateRole,
  useDeleteRole,
  usePermissions,
  useRoles,
  useUpdateRole,
  type Permission,
  type Role,
} from '@/hooks/useRolesAdmin';

function groupByPrefix(
  permissions: Permission[],
): Array<{ group: string; items: Permission[] }> {
  const map = new Map<string, Permission[]>();
  for (const p of permissions) {
    const group = p.code.split('.')[0];
    const arr = map.get(group) ?? [];
    arr.push(p);
    map.set(group, arr);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([group, items]) => ({
      group,
      items: items.slice().sort((a, b) => a.code.localeCompare(b.code)),
    }));
}

function RoleEditModal({
  opened,
  onClose,
  role,
  permissions,
}: {
  opened: boolean;
  onClose: () => void;
  role: Role;
  permissions: Permission[];
}) {
  const { t } = useTranslation();
  const update = useUpdateRole(role.id);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(role.permissions),
  );
  const [name, setName] = useState(role.name);

  useEffect(() => {
    if (opened) {
      // Re-sync from props when the modal reopens. Cascading-render
      // warning is expected — the alternative (key-based remount) would
      // lose modal-internal state on every prop change.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelected(new Set(role.permissions));
      setName(role.name);
    }
  }, [opened, role]);

  const groups = useMemo(() => groupByPrefix(permissions), [permissions]);

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const handleSave = async () => {
    try {
      await update.mutateAsync({
        name: role.is_system ? undefined : name.trim(),
        permissions: Array.from(selected),
      });
      notifications.show({ color: 'teal', message: t('admin.saved') });
      onClose();
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('roles.editTitle', { code: role.code })}
      size="lg"
      centered
    >
      <Stack>
        <TextInput
          label={t('roles.name')}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          disabled={role.is_system}
          description={
            role.is_system ? t('roles.systemRoleNoRename') : undefined
          }
        />
        <TextInput label={t('roles.code')} value={role.code} readOnly />

        <Text fw={500}>{t('roles.permissions')}</Text>
        {groups.map(({ group, items }) => (
          <Paper key={group} withBorder p="xs">
            <Text fw={500} size="sm" mb={4} tt="capitalize">
              {group.replace(/_/g, ' ')}
            </Text>
            <Stack gap={4}>
              {items.map((p) => (
                <Checkbox
                  key={p.code}
                  checked={selected.has(p.code)}
                  onChange={() => toggle(p.code)}
                  label={
                    <Stack gap={0}>
                      <Text size="sm" ff="monospace">
                        {p.code}
                      </Text>
                      {p.description && (
                        <Text size="xs" c="dimmed">
                          {p.description}
                        </Text>
                      )}
                    </Stack>
                  }
                />
              ))}
            </Stack>
          </Paper>
        ))}

        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSave} loading={update.isPending}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function NewRoleModal({
  opened,
  onClose,
  permissions,
}: {
  opened: boolean;
  onClose: () => void;
  permissions: Permission[];
}) {
  const { t } = useTranslation();
  const create = useCreateRole();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const form = useForm({
    initialValues: { code: '', name: '' },
    validate: {
      code: (v) =>
        /^[a-z0-9_]+$/.test(v)
          ? null
          : t('roles.codeInvalid'),
      name: (v) => (v.trim() ? null : t('common.required')),
    },
  });

  useEffect(() => {
    if (opened) {
      form.reset();
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelected(new Set());
    }
    // form ref is stable; not including it to avoid reset loop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  const groups = useMemo(() => groupByPrefix(permissions), [permissions]);

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const submit = form.onSubmit(async (values) => {
    try {
      await create.mutateAsync({
        code: values.code.trim(),
        name: values.name.trim(),
        permissions: Array.from(selected),
      });
      notifications.show({ color: 'teal', message: t('roles.created') });
      onClose();
    } catch (err) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message:
          resp?.status === 409
            ? resp?.data?.detail ?? t('roles.codeConflict')
            : resp?.data?.detail ?? t('admin.saveFailed'),
      });
    }
  });

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('roles.newTitle')}
      size="lg"
      centered
    >
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label={t('roles.code')}
            description={t('roles.codeHelp')}
            required
            {...form.getInputProps('code')}
          />
          <TextInput
            label={t('roles.name')}
            required
            {...form.getInputProps('name')}
          />

          <Text fw={500}>{t('roles.permissions')}</Text>
          {groups.map(({ group, items }) => (
            <Paper key={group} withBorder p="xs">
              <Text fw={500} size="sm" mb={4} tt="capitalize">
                {group.replace(/_/g, ' ')}
              </Text>
              <Stack gap={4}>
                {items.map((p) => (
                  <Checkbox
                    key={p.code}
                    checked={selected.has(p.code)}
                    onChange={() => toggle(p.code)}
                    label={
                      <Stack gap={0}>
                        <Text size="sm" ff="monospace">
                          {p.code}
                        </Text>
                        {p.description && (
                          <Text size="xs" c="dimmed">
                            {p.description}
                          </Text>
                        )}
                      </Stack>
                    }
                  />
                ))}
              </Stack>
            </Paper>
          ))}

          <Group justify="flex-end">
            <Button variant="subtle" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={create.isPending}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function RoleRow({ role, permissions }: { role: Role; permissions: Permission[] }) {
  const { t } = useTranslation();
  const del = useDeleteRole();
  const [open, setOpen] = useState(false);

  const handleDelete = async () => {
    if (!window.confirm(t('roles.confirmDelete', { name: role.name }))) return;
    try {
      await del.mutateAsync(role.id);
      notifications.show({ color: 'teal', message: t('roles.deleted') });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      notifications.show({
        color: 'red',
        message: resp?.data?.detail ?? t('admin.deleteFailed'),
      });
    }
  };

  return (
    <Table.Tr>
      <Table.Td>
        <Button variant="subtle" size="compact-sm" onClick={() => setOpen(true)}>
          {role.name}
        </Button>
        {role.is_system && (
          <Badge ml="xs" color="gray" variant="light" size="xs">
            {t('roles.system')}
          </Badge>
        )}
        <RoleEditModal
          opened={open}
          onClose={() => setOpen(false)}
          role={role}
          permissions={permissions}
        />
      </Table.Td>
      <Table.Td>
        <Text ff="monospace" size="sm">
          {role.code}
        </Text>
      </Table.Td>
      <Table.Td>{role.permissions.length}</Table.Td>
      <Table.Td>
        {!role.is_system && (
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={handleDelete}
            loading={del.isPending}
            aria-label={t('common.delete')}
          >
            <IconTrash size={14} />
          </ActionIcon>
        )}
      </Table.Td>
    </Table.Tr>
  );
}

export function RolesAdmin() {
  const { t } = useTranslation();
  const { data: roles = [], isLoading } = useRoles();
  const { data: permissions = [] } = usePermissions();
  const [newOpen, setNewOpen] = useState(false);

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('roles.title')}</Title>
        <Button
          leftSection={<IconPlus size={14} />}
          onClick={() => setNewOpen(true)}
        >
          {t('roles.new')}
        </Button>
      </Group>

      <Paper withBorder>
        <Table.ScrollContainer minWidth={560}>
        <Table verticalSpacing="sm" style={{ whiteSpace: 'nowrap' }}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('roles.name')}</Table.Th>
              <Table.Th>{t('roles.code')}</Table.Th>
              <Table.Th>{t('roles.permCount')}</Table.Th>
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
            {!isLoading && roles.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={4}>
                  <Text c="dimmed">{t('roles.empty')}</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {roles.map((r) => (
              <RoleRow key={r.id} role={r} permissions={permissions} />
            ))}
          </Table.Tbody>
        </Table>
        </Table.ScrollContainer>
      </Paper>

      <NewRoleModal
        opened={newOpen}
        onClose={() => setNewOpen(false)}
        permissions={permissions}
      />
    </Stack>
  );
}
