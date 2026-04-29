// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import type { ReactElement, ReactNode } from 'react';

import { Stack, Tabs, Title } from '@mantine/core';
import {
  IconBrush,
  IconHistory,
  IconKey,
  IconLanguage,
  IconLock,
  IconMail,
  IconMailForward,
  IconSend,
  IconServer,
  IconUserPlus,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { AuditAdmin } from '@/components/admin/AuditAdmin';
import { AuthAdmin } from '@/components/admin/AuthAdmin';
import { BrandingAdmin } from '@/components/admin/BrandingAdmin';
import { EmailOutboxAdmin } from '@/components/admin/EmailOutboxAdmin';
import { EmailTemplatesAdmin } from '@/components/admin/EmailTemplatesAdmin';
import { RemindersAdmin } from '@/components/admin/RemindersAdmin';
import { RolesAdmin } from '@/components/admin/RolesAdmin';
import { SystemAdmin } from '@/components/admin/SystemAdmin';
import { TranslationsAdmin } from '@/components/admin/TranslationsAdmin';
import { UsersAdmin } from '@/components/admin/UsersAdmin';
import { useMe, usePerm } from '@/hooks/useAuth';
import { getAdminTabs } from '@/host/registry';

/** Built-in admin tabs use 100..900 in steps of 100 so a host tab can
 *  interleave with ``order: 250`` (between Auth and Users), ``650``
 *  (between Email templates and Email outbox), etc. Host tabs without
 *  ``order`` keep registration order and land **after** every built-in.
 */
const TAB_ORDER = {
  system: 100,
  auth: 200,
  users: 300,
  branding: 400,
  roles: 500,
  translations: 600,
  emails: 700,
  outbox: 750,
  reminders: 800,
  audit: 900,
} as const;

type AdminTabRow = {
  key: string;
  label: ReactNode;
  icon?: ReactElement;
  panel: ReactNode;
  order?: number;
};

export function AdminPage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canManageRoles = usePerm('role.manage');
  const canViewAudit = usePerm('audit.read');
  const canManageAppConfig = usePerm('app_setting.manage');
  const canManageEmailTemplates = usePerm('email_template.manage');
  const canManageEmailOutbox = usePerm('email_outbox.manage');

  // Host-registered admin tabs; filtered by the perm code each tab
  // declares (omitted ``perm`` means visible to every viewer of the
  // admin page).
  const userPerms = me?.permissions ?? [];
  const visibleHostTabs = getAdminTabs().filter(
    (tab) => !tab.perm || userPerms.includes(tab.perm),
  );

  const tabs: AdminTabRow[] = [];
  if (canManageAppConfig) {
    tabs.push({
      key: 'system',
      label: t('system.tab'),
      icon: <IconServer size={14} />,
      panel: <SystemAdmin />,
      order: TAB_ORDER.system,
    });
    tabs.push({
      key: 'auth',
      label: t('authAdmin.tab'),
      icon: <IconLock size={14} />,
      panel: <AuthAdmin />,
      order: TAB_ORDER.auth,
    });
  }
  tabs.push({
    key: 'users',
    label: t('users.tab'),
    icon: <IconUserPlus size={14} />,
    panel: <UsersAdmin />,
    order: TAB_ORDER.users,
  });
  if (canManageAppConfig) {
    tabs.push({
      key: 'branding',
      label: t('branding.tab'),
      icon: <IconBrush size={14} />,
      panel: <BrandingAdmin />,
      order: TAB_ORDER.branding,
    });
  }
  if (canManageRoles) {
    tabs.push({
      key: 'roles',
      label: t('roles.tab'),
      icon: <IconKey size={14} />,
      panel: <RolesAdmin />,
      order: TAB_ORDER.roles,
    });
  }
  if (canManageAppConfig) {
    tabs.push({
      key: 'translations',
      label: t('translations.tab'),
      icon: <IconLanguage size={14} />,
      panel: <TranslationsAdmin />,
      order: TAB_ORDER.translations,
    });
  }
  if (canManageEmailTemplates) {
    tabs.push({
      key: 'emails',
      label: t('emailTemplates.tab'),
      icon: <IconMail size={14} />,
      panel: <EmailTemplatesAdmin />,
      order: TAB_ORDER.emails,
    });
  }
  if (canManageEmailOutbox) {
    tabs.push({
      key: 'outbox',
      label: t('emailOutbox.tab'),
      icon: <IconMailForward size={14} />,
      panel: <EmailOutboxAdmin />,
      order: TAB_ORDER.outbox,
    });
  }
  tabs.push({
    key: 'reminders',
    label: t('reminders.tab'),
    icon: <IconSend size={14} />,
    panel: <RemindersAdmin />,
    order: TAB_ORDER.reminders,
  });
  if (canViewAudit) {
    tabs.push({
      key: 'audit',
      label: t('audit.tab'),
      icon: <IconHistory size={14} />,
      panel: <AuditAdmin />,
      order: TAB_ORDER.audit,
    });
  }
  for (const hostTab of visibleHostTabs) {
    tabs.push({
      key: hostTab.key,
      label: hostTab.label,
      icon: hostTab.icon,
      panel: hostTab.render ? hostTab.render() : hostTab.element,
      order: hostTab.order,
    });
  }

  // Stable sort by ``order``; items without ``order`` keep insertion
  // order and land after every item that has one.
  tabs.sort((a, b) => {
    const ao = a.order;
    const bo = b.order;
    if (ao === undefined && bo === undefined) return 0;
    if (ao === undefined) return 1;
    if (bo === undefined) return -1;
    return ao - bo;
  });

  const visibleKeys = new Set(tabs.map((tab) => tab.key));

  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('tab');
  const fallback: string =
    canManageAppConfig && visibleKeys.has('system') ? 'system' : 'users';
  const active: string =
    requested !== null && visibleKeys.has(requested) ? requested : fallback;

  const onTabChange = (v: string | null) => {
    if (!v) return;
    setSearchParams({ tab: v }, { replace: true });
  };

  return (
    <Stack>
      <Title order={2}>{t('nav.admin')}</Title>
      <Tabs value={active} onChange={onTabChange} keepMounted={false}>
        <Tabs.List>
          {tabs.map((tab) => (
            <Tabs.Tab key={tab.key} value={tab.key} leftSection={tab.icon}>
              {tab.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        {tabs.map((tab) => (
          <Tabs.Panel key={tab.key} value={tab.key} pt="md">
            {tab.panel}
          </Tabs.Panel>
        ))}
      </Tabs>
    </Stack>
  );
}
