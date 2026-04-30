// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import type { ReactElement } from 'react';
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
import {
  getAdminTabs,
  getBuiltinAdminTabOverride,
  type AdminSection,
} from '@/host/registry';

/** A resolved admin/settings section row. Both the sidebar's expandable
 *  parent and the route page render from the same list, so visibility
 *  filtering and sort order are computed once here. */
export interface SectionItem {
  key: string;
  label: string;
  icon?: ReactElement;
  /** Returns a fresh element on each render — matches the registry's
   *  ``render()`` shape so host tabs and built-ins look the same. */
  render: () => ReactElement;
  order?: number;
}

interface BuiltinDef extends SectionItem {
  /** Default sidebar bucket atrium ships this tab in. A host bundle
   *  can override via ``setBuiltinAdminTabSection`` at boot. */
  defaultSection: AdminSection;
}

/** Built-in admin tabs use 100..900 in steps of 100 so a host tab can
 *  interleave with ``order: 250`` (between Auth and Users), ``650``
 *  (between Email templates and Email outbox), etc. */
const ADMIN_ORDER = {
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

function sortByOrder(items: SectionItem[]): SectionItem[] {
  return [...items].sort((a, b) => {
    const ao = a.order;
    const bo = b.order;
    if (ao === undefined && bo === undefined) return 0;
    if (ao === undefined) return 1;
    if (bo === undefined) return -1;
    return ao - bo;
  });
}

function hostItemsFor(
  section: AdminSection,
  userPerms: readonly string[],
): SectionItem[] {
  return getAdminTabs()
    .filter((tab) => (tab.section ?? 'admin') === section)
    .filter((tab) => !tab.perm || userPerms.includes(tab.perm))
    .map((tab) => ({
      key: tab.key,
      label: tab.label,
      icon: tab.icon,
      render: tab.render
        ? tab.render
        : tab.element
          ? () => tab.element as ReactElement
          : () => <></>,
      order: tab.order,
    }));
}

function builtinsFor(
  section: AdminSection,
  defs: readonly BuiltinDef[],
): SectionItem[] {
  const out: SectionItem[] = [];
  for (const def of defs) {
    const override = getBuiltinAdminTabOverride(def.key);
    const effectiveSection = override?.section ?? def.defaultSection;
    if (effectiveSection !== section) continue;
    const item: SectionItem = {
      key: def.key,
      label: def.label,
      render: def.render,
      order: override?.order ?? def.order,
    };
    if (def.icon) item.icon = def.icon;
    out.push(item);
  }
  return out;
}

/** Build the full set of permission-gated atrium built-in tabs. The
 *  list is a single source of truth — both ``useAdminSectionItems``
 *  and ``useSettingsSectionItems`` filter from it via the host
 *  override map, so a built-in only ever appears in one bucket. */
function useBuiltinDefs(): BuiltinDef[] {
  const { t } = useTranslation();
  const canManageRoles = usePerm('role.manage');
  const canViewAudit = usePerm('audit.read');
  const canManageAppConfig = usePerm('app_setting.manage');
  const canManageEmailTemplates = usePerm('email_template.manage');
  const canManageEmailOutbox = usePerm('email_outbox.manage');

  const defs: BuiltinDef[] = [];

  if (canManageAppConfig) {
    defs.push({
      key: 'system',
      label: t('system.tab'),
      icon: <IconServer size={14} />,
      render: () => <SystemAdmin />,
      order: ADMIN_ORDER.system,
      defaultSection: 'admin',
    });
    defs.push({
      key: 'auth',
      label: t('authAdmin.tab'),
      icon: <IconLock size={14} />,
      render: () => <AuthAdmin />,
      order: ADMIN_ORDER.auth,
      defaultSection: 'admin',
    });
  }
  defs.push({
    key: 'users',
    label: t('users.tab'),
    icon: <IconUserPlus size={14} />,
    render: () => <UsersAdmin />,
    order: ADMIN_ORDER.users,
    defaultSection: 'admin',
  });
  if (canManageAppConfig) {
    defs.push({
      key: 'branding',
      label: t('branding.tab'),
      icon: <IconBrush size={14} />,
      render: () => <BrandingAdmin />,
      order: ADMIN_ORDER.branding,
      defaultSection: 'admin',
    });
  }
  if (canManageRoles) {
    defs.push({
      key: 'roles',
      label: t('roles.tab'),
      icon: <IconKey size={14} />,
      render: () => <RolesAdmin />,
      order: ADMIN_ORDER.roles,
      defaultSection: 'admin',
    });
  }
  if (canManageAppConfig) {
    defs.push({
      key: 'translations',
      label: t('translations.tab'),
      icon: <IconLanguage size={14} />,
      render: () => <TranslationsAdmin />,
      order: ADMIN_ORDER.translations,
      defaultSection: 'admin',
    });
  }
  if (canManageEmailTemplates) {
    defs.push({
      key: 'emails',
      label: t('emailTemplates.tab'),
      icon: <IconMail size={14} />,
      render: () => <EmailTemplatesAdmin />,
      order: ADMIN_ORDER.emails,
      defaultSection: 'admin',
    });
  }
  if (canManageEmailOutbox) {
    defs.push({
      key: 'outbox',
      label: t('emailOutbox.tab'),
      icon: <IconMailForward size={14} />,
      render: () => <EmailOutboxAdmin />,
      order: ADMIN_ORDER.outbox,
      defaultSection: 'admin',
    });
  }
  defs.push({
    key: 'reminders',
    label: t('reminders.tab'),
    icon: <IconSend size={14} />,
    render: () => <RemindersAdmin />,
    order: ADMIN_ORDER.reminders,
    defaultSection: 'admin',
  });
  if (canViewAudit) {
    defs.push({
      key: 'audit',
      label: t('audit.tab'),
      icon: <IconHistory size={14} />,
      render: () => <AuditAdmin />,
      order: ADMIN_ORDER.audit,
      defaultSection: 'admin',
    });
  }
  return defs;
}

/** Items rendered under the Admin sidebar group + the matching route
 *  page. Built-in atrium tabs are filtered by perm and bucketed by
 *  ``setBuiltinAdminTabSection`` overrides; host tabs that declared
 *  ``section: 'admin'`` (or omitted ``section``) join them. */
export function useAdminSectionItems(): SectionItem[] {
  const { data: me } = useMe();
  const builtinDefs = useBuiltinDefs();
  return sortByOrder([
    ...builtinsFor('admin', builtinDefs),
    ...hostItemsFor('admin', me?.permissions ?? []),
  ]);
}

/** Items rendered under the Settings sidebar group + the matching
 *  route page. Empty by default — atrium ships zero built-ins here.
 *  Host bundles populate it either with ``registerAdminTab({ section:
 *  'settings' })`` for their own tabs, or by relocating built-ins via
 *  ``setBuiltinAdminTabSection``. */
export function useSettingsSectionItems(): SectionItem[] {
  const { data: me } = useMe();
  const builtinDefs = useBuiltinDefs();
  return sortByOrder([
    ...builtinsFor('settings', builtinDefs),
    ...hostItemsFor('settings', me?.permissions ?? []),
  ]);
}
