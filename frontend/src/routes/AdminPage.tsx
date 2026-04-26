import { Stack, Tabs, Title } from '@mantine/core';
import {
  IconBrush,
  IconHistory,
  IconKey,
  IconLanguage,
  IconMail,
  IconSend,
  IconServer,
  IconUserPlus,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { AuditAdmin } from '@/components/admin/AuditAdmin';
import { BrandingAdmin } from '@/components/admin/BrandingAdmin';
import { EmailTemplatesAdmin } from '@/components/admin/EmailTemplatesAdmin';
import { RemindersAdmin } from '@/components/admin/RemindersAdmin';
import { RolesAdmin } from '@/components/admin/RolesAdmin';
import { SystemAdmin } from '@/components/admin/SystemAdmin';
import { TranslationsAdmin } from '@/components/admin/TranslationsAdmin';
import { UsersAdmin } from '@/components/admin/UsersAdmin';
import { usePerm } from '@/hooks/useAuth';

const TABS = [
  'users',
  'roles',
  'branding',
  'system',
  'translations',
  'emails',
  'reminders',
  'audit',
] as const;
type TabValue = (typeof TABS)[number];

export function AdminPage() {
  const { t } = useTranslation();
  const canManageRoles = usePerm('role.manage');
  const canViewAudit = usePerm('audit.read');
  const canManageAppConfig = usePerm('app_setting.manage');
  const canManageEmailTemplates = usePerm('email_template.manage');

  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('tab') as TabValue | null;
  const isValid =
    requested !== null &&
    TABS.includes(requested) &&
    (requested !== 'audit' || canViewAudit) &&
    (requested !== 'roles' || canManageRoles) &&
    (requested !== 'branding' || canManageAppConfig) &&
    (requested !== 'system' || canManageAppConfig) &&
    (requested !== 'translations' || canManageAppConfig) &&
    (requested !== 'emails' || canManageEmailTemplates);
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
          {canManageAppConfig && (
            <Tabs.Tab value="branding" leftSection={<IconBrush size={14} />}>
              {t('branding.tab')}
            </Tabs.Tab>
          )}
          {canManageAppConfig && (
            <Tabs.Tab value="system" leftSection={<IconServer size={14} />}>
              {t('system.tab')}
            </Tabs.Tab>
          )}
          {canManageAppConfig && (
            <Tabs.Tab
              value="translations"
              leftSection={<IconLanguage size={14} />}
            >
              {t('translations.tab')}
            </Tabs.Tab>
          )}
          {canManageEmailTemplates && (
            <Tabs.Tab value="emails" leftSection={<IconMail size={14} />}>
              {t('emailTemplates.tab')}
            </Tabs.Tab>
          )}
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
        {canManageAppConfig && (
          <Tabs.Panel value="branding" pt="md"><BrandingAdmin /></Tabs.Panel>
        )}
        {canManageAppConfig && (
          <Tabs.Panel value="system" pt="md"><SystemAdmin /></Tabs.Panel>
        )}
        {canManageAppConfig && (
          <Tabs.Panel value="translations" pt="md">
            <TranslationsAdmin />
          </Tabs.Panel>
        )}
        {canManageEmailTemplates && (
          <Tabs.Panel value="emails" pt="md"><EmailTemplatesAdmin /></Tabs.Panel>
        )}
        <Tabs.Panel value="reminders" pt="md"><RemindersAdmin /></Tabs.Panel>
        {canViewAudit && (
          <Tabs.Panel value="audit" pt="md"><AuditAdmin /></Tabs.Panel>
        )}
      </Tabs>
    </Stack>
  );
}
