// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Stack, Tabs, Title } from '@mantine/core';
import {
  IconBrush,
  IconHistory,
  IconKey,
  IconLanguage,
  IconLock,
  IconMail,
  IconSend,
  IconServer,
  IconUserPlus,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { AuditAdmin } from '@/components/admin/AuditAdmin';
import { AuthAdmin } from '@/components/admin/AuthAdmin';
import { BrandingAdmin } from '@/components/admin/BrandingAdmin';
import { EmailTemplatesAdmin } from '@/components/admin/EmailTemplatesAdmin';
import { RemindersAdmin } from '@/components/admin/RemindersAdmin';
import { RolesAdmin } from '@/components/admin/RolesAdmin';
import { SystemAdmin } from '@/components/admin/SystemAdmin';
import { TranslationsAdmin } from '@/components/admin/TranslationsAdmin';
import { UsersAdmin } from '@/components/admin/UsersAdmin';
import { useMe, usePerm } from '@/hooks/useAuth';
import { getAdminTabs } from '@/host/registry';

const TABS = [
  'system',
  'auth',
  'users',
  'branding',
  'roles',
  'translations',
  'emails',
  'reminders',
  'audit',
] as const;

export function AdminPage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canManageRoles = usePerm('role.manage');
  const canViewAudit = usePerm('audit.read');
  const canManageAppConfig = usePerm('app_setting.manage');
  const canManageEmailTemplates = usePerm('email_template.manage');

  // Host-registered admin tabs; filtered by the perm code each tab
  // declares (omitted ``perm`` means visible to every viewer of the
  // admin page).
  const userPerms = me?.permissions ?? [];
  const visibleHostTabs = getAdminTabs().filter(
    (tab) => !tab.perm || userPerms.includes(tab.perm),
  );

  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('tab');
  const isBuiltinValid =
    requested !== null &&
    (TABS as readonly string[]).includes(requested) &&
    (requested !== 'audit' || canViewAudit) &&
    (requested !== 'roles' || canManageRoles) &&
    (requested !== 'branding' || canManageAppConfig) &&
    (requested !== 'system' || canManageAppConfig) &&
    (requested !== 'auth' || canManageAppConfig) &&
    (requested !== 'translations' || canManageAppConfig) &&
    (requested !== 'emails' || canManageEmailTemplates);
  const isHostValid =
    requested !== null && visibleHostTabs.some((t) => t.key === requested);
  const fallback: string = canManageAppConfig ? 'system' : 'users';
  const active: string = isBuiltinValid || isHostValid ? requested! : fallback;

  const onTabChange = (v: string | null) => {
    if (!v) return;
    setSearchParams({ tab: v }, { replace: true });
  };

  return (
    <Stack>
      <Title order={2}>{t('nav.admin')}</Title>
      <Tabs value={active} onChange={onTabChange} keepMounted={false}>
        <Tabs.List>
          {canManageAppConfig && (
            <Tabs.Tab value="system" leftSection={<IconServer size={14} />}>
              {t('system.tab')}
            </Tabs.Tab>
          )}
          {canManageAppConfig && (
            <Tabs.Tab value="auth" leftSection={<IconLock size={14} />}>
              {t('authAdmin.tab')}
            </Tabs.Tab>
          )}
          <Tabs.Tab value="users" leftSection={<IconUserPlus size={14} />}>
            {t('users.tab')}
          </Tabs.Tab>
          {canManageAppConfig && (
            <Tabs.Tab value="branding" leftSection={<IconBrush size={14} />}>
              {t('branding.tab')}
            </Tabs.Tab>
          )}
          {canManageRoles && (
            <Tabs.Tab value="roles" leftSection={<IconKey size={14} />}>
              {t('roles.tab')}
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
          {visibleHostTabs.map((tab) => (
            <Tabs.Tab
              key={tab.key}
              value={tab.key}
              leftSection={tab.icon}
            >
              {tab.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        {canManageAppConfig && (
          <Tabs.Panel value="system" pt="md"><SystemAdmin /></Tabs.Panel>
        )}
        {canManageAppConfig && (
          <Tabs.Panel value="auth" pt="md"><AuthAdmin /></Tabs.Panel>
        )}
        <Tabs.Panel value="users" pt="md"><UsersAdmin /></Tabs.Panel>
        {canManageAppConfig && (
          <Tabs.Panel value="branding" pt="md"><BrandingAdmin /></Tabs.Panel>
        )}
        {canManageRoles && (
          <Tabs.Panel value="roles" pt="md"><RolesAdmin /></Tabs.Panel>
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
        {visibleHostTabs.map((tab) => (
          <Tabs.Panel key={tab.key} value={tab.key} pt="md">
            {tab.render ? tab.render() : tab.element}
          </Tabs.Panel>
        ))}
      </Tabs>
    </Stack>
  );
}
