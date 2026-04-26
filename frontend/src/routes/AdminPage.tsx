import { Stack, Tabs, Title } from '@mantine/core';
import {
  IconHistory,
  IconKey,
  IconMail,
  IconSend,
  IconUserPlus,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { AuditAdmin } from '@/components/admin/AuditAdmin';
import { EmailTemplatesAdmin } from '@/components/admin/EmailTemplatesAdmin';
import { RemindersAdmin } from '@/components/admin/RemindersAdmin';
import { RolesAdmin } from '@/components/admin/RolesAdmin';
import { UsersAdmin } from '@/components/admin/UsersAdmin';
import { usePerm } from '@/hooks/useAuth';

const TABS = ['users', 'roles', 'emails', 'reminders', 'audit'] as const;
type TabValue = (typeof TABS)[number];

export function AdminPage() {
  const { t } = useTranslation();
  // Audit + role administration are guarded server-side; on the client
  // we just hide the tabs unless the user holds the matching
  // permissions. Host apps can swap these codes for their own.
  const canManageRoles = usePerm('role.manage');
  const canViewAudit = usePerm('audit.read');

  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('tab') as TabValue | null;
  const isValid =
    requested !== null &&
    TABS.includes(requested) &&
    (requested !== 'audit' || canViewAudit) &&
    (requested !== 'roles' || canManageRoles);
  const active: TabValue = isValid ? requested : 'users';

  const onTabChange = (v: string | null) => {
    if (!v) return;
    setSearchParams({ tab: v }, { replace: true });
  };

  return (
    <Stack>
      <Title order={2}>{t('nav.admin')}</Title>
      <Tabs value={active} onChange={onTabChange} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="users" leftSection={<IconUserPlus size={14} />}>
            {t('users.tab')}
          </Tabs.Tab>
          {canManageRoles && (
            <Tabs.Tab value="roles" leftSection={<IconKey size={14} />}>
              {t('roles.tab')}
            </Tabs.Tab>
          )}
          <Tabs.Tab value="emails" leftSection={<IconMail size={14} />}>
            {t('emailTemplates.tab')}
          </Tabs.Tab>
          <Tabs.Tab value="reminders" leftSection={<IconSend size={14} />}>
            {t('reminders.tab')}
          </Tabs.Tab>
          {canViewAudit && (
            <Tabs.Tab value="audit" leftSection={<IconHistory size={14} />}>
              {t('audit.tab')}
            </Tabs.Tab>
          )}
        </Tabs.List>
        <Tabs.Panel value="users" pt="md"><UsersAdmin /></Tabs.Panel>
        {canManageRoles && (
          <Tabs.Panel value="roles" pt="md"><RolesAdmin /></Tabs.Panel>
        )}
        <Tabs.Panel value="emails" pt="md"><EmailTemplatesAdmin /></Tabs.Panel>
        <Tabs.Panel value="reminders" pt="md"><RemindersAdmin /></Tabs.Panel>
        {canViewAudit && (
          <Tabs.Panel value="audit" pt="md"><AuditAdmin /></Tabs.Panel>
        )}
      </Tabs>
    </Stack>
  );
}
