// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import {
  AppShell,
  Avatar,
  Burger,
  Button,
  Group,
  Image,
  Menu,
  NavLink,
  Select,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconAdjustments,
  IconBell,
  IconHome,
  IconSettings,
  IconUser,
  IconLogout,
} from '@tabler/icons-react';
import type { ReactElement } from 'react';
import { useEffect, useRef } from 'react';
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
  useAdminSectionItems,
  useSettingsSectionItems,
  type SectionItem,
} from '@/admin/sections';
import { useAppConfig } from '@/hooks/useAppConfig';
import { useMe, useLogout } from '@/hooks/useAuth';
import { getNavItems, type NavItem } from '@/host/registry';
import type { CurrentUser } from '@/lib/auth';

import { AnnouncementBanner } from './AnnouncementBanner';
import { ImpersonationBanner } from './ImpersonationBanner';
import { NotificationsBell } from './NotificationsBell';

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const { t, i18n } = useTranslation();
  const { data: me } = useMe();
  const { data: appConfig } = useAppConfig();
  const brand = appConfig?.brand;
  const logout = useLogout();
  const navigate = useNavigate();
  const location = useLocation();
  const adminItems = useAdminSectionItems();
  const settingsItems = useSettingsSectionItems();

  const initials = me?.full_name
    ? me.full_name
        .split(/\s+/)
        .slice(0, 2)
        .map((w) => w[0])
        .join('')
        .toUpperCase()
    : '?';

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const configured = appConfig?.i18n?.enabled_locales;
  const enabledLocales =
    configured && configured.length > 0 ? configured : ['en', 'nl'];

  const currentLocale = i18n.language.split('-')[0];
  const activeLocale = enabledLocales.includes(currentLocale)
    ? currentLocale
    : enabledLocales[0];

  // If the admin disables the locale the user currently has selected,
  // fall back to the first enabled one without forcing them to pick.
  useEffect(() => {
    if (currentLocale !== activeLocale) {
      void i18n.changeLanguage(activeLocale);
    }
  }, [activeLocale, currentLocale, i18n]);

  // Sync the UI language to ``users.preferred_language`` ONCE per
  // mounted session. Without this, a user who picked NL on the
  // profile page and then logs out/back in would see EN until they
  // manually switched again. Re-running the sync on every me-update
  // would override the user's manual header switch — so the ref
  // gate ensures we only push preferred_language → i18n on the
  // first non-null ``me`` (and let later changes flow the other
  // way through the profile page's onSuccess).
  const preferredLocale = me?.preferred_language;
  const initialLocaleSynced = useRef(false);
  useEffect(() => {
    if (initialLocaleSynced.current) return;
    if (!preferredLocale) return;
    initialLocaleSynced.current = true;
    if (
      enabledLocales.includes(preferredLocale) &&
      preferredLocale !== currentLocale
    ) {
      void i18n.changeLanguage(preferredLocale);
    }
  }, [preferredLocale, currentLocale, enabledLocales, i18n]);

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            {brand?.logo_url && (
              <Link to="/" style={{ display: 'inline-flex' }} aria-label={t('app.title')}>
                <Image
                  src={brand.logo_url}
                  h={32}
                  w="auto"
                  fit="contain"
                  alt=""
                />
              </Link>
            )}
            <Title order={4}>{brand?.name ?? t('app.title')}</Title>
          </Group>
          <Group gap="xs">
            {me && <NotificationsBell />}
            <Select
              size="xs"
              aria-label={t('common.language')}
              value={activeLocale}
              onChange={(v) => v && i18n.changeLanguage(v)}
              data={enabledLocales.map((code) => ({
                value: code,
                label: code.toUpperCase(),
              }))}
              w={80}
            />
            {me && (
              <Menu position="bottom-end" shadow="md">
                <Menu.Target>
                  <Avatar radius="xl" size="sm" style={{ cursor: 'pointer' }}>
                    {initials}
                  </Avatar>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label>{me.email}</Menu.Label>
                  <Menu.Item
                    leftSection={<IconUser size={14} />}
                    component={Link}
                    to="/profile"
                  >
                    {t('nav.profile')}
                  </Menu.Item>
                  <Menu.Divider />
                  <Menu.Item
                    leftSection={<IconLogout size={14} />}
                    onClick={handleLogout}
                    color="red"
                  >
                    {t('nav.logout')}
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
            {!me && (
              <Button component={Link} to="/login" size="xs" variant="light">
                {t('login.submit')}
              </Button>
            )}
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        {buildNavLinks({
          me: me ?? null,
          adminItems,
          settingsItems,
          pathname: location.pathname,
          onNavigate: close,
          t,
        })}
      </AppShell.Navbar>

      <AppShell.Main>
        <AnnouncementBanner />
        <ImpersonationBanner />
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}

/** Built-in nav slots use 100/200/250/300 so a host can interleave
 *  with ``order: 150`` (between Home and Notifications) or any value
 *  > 300 to land below Admin. The Settings parent slots in at 250 —
 *  above Admin and below Notifications — so host preference pages get
 *  a natural home that won't shove Admin off the bottom. A host item
 *  with no ``order`` keeps insertion order and lands after everything
 *  that does have one — including the built-ins. */
const NAV_ORDER = {
  home: 100,
  notifications: 200,
  settings: 250,
  admin: 300,
} as const;

interface SectionNavGroup {
  key: string;
  label: string;
  to: string;
  icon: ReactElement;
  order: number;
  items: SectionItem[];
}

function buildNavLinks(args: {
  me: CurrentUser | null;
  adminItems: SectionItem[];
  settingsItems: SectionItem[];
  pathname: string;
  onNavigate: () => void;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const { me, adminItems, settingsItems, pathname, onNavigate, t } = args;

  type FlatItem = NavItem & { active: boolean };
  type GroupItem = SectionNavGroup & { active: boolean };
  type Entry = FlatItem | GroupItem;

  const isGroup = (entry: Entry): entry is GroupItem =>
    (entry as GroupItem).items !== undefined;

  const entries: Entry[] = [
    {
      key: '__atrium_home',
      label: t('nav.home'),
      to: '/',
      icon: <IconHome size={16} />,
      order: NAV_ORDER.home,
      active: pathname === '/',
    },
    {
      key: '__atrium_notifications',
      label: t('nav.notifications'),
      to: '/notifications',
      icon: <IconBell size={16} />,
      order: NAV_ORDER.notifications,
      active: pathname.startsWith('/notifications'),
    },
  ];

  // Settings hides entirely when no host has registered into it —
  // there's no atrium-shipped content for this group. Admin hides
  // when the viewer holds zero qualifying perms (matches the previous
  // ``isAdmin`` gate but is now derived from the resolved item list).
  if (settingsItems.length > 0) {
    entries.push({
      key: '__atrium_settings',
      label: t('nav.settings'),
      to: '/settings',
      icon: <IconAdjustments size={16} />,
      order: NAV_ORDER.settings,
      items: settingsItems,
      active: pathname.startsWith('/settings'),
    });
  }
  if (adminItems.length > 0) {
    entries.push({
      key: '__atrium_admin',
      label: t('nav.admin'),
      to: '/admin',
      icon: <IconSettings size={16} />,
      order: NAV_ORDER.admin,
      items: adminItems,
      active: pathname.startsWith('/admin'),
    });
  }

  const hostItems = getNavItems()
    .filter((item) => (item.condition ? item.condition({ me }) : true))
    .map(
      (item): FlatItem => ({
        ...item,
        active: pathname === item.to || pathname.startsWith(`${item.to}/`),
      }),
    );
  entries.push(...hostItems);

  // Stable sort: items with order come first; same-key falls back to
  // insertion order (Array.prototype.sort is stable in ES2019+).
  entries.sort((a, b) => {
    const ao = a.order;
    const bo = b.order;
    if (ao === undefined && bo === undefined) return 0;
    if (ao === undefined) return 1;
    if (bo === undefined) return -1;
    return ao - bo;
  });

  return entries.map((entry) => {
    if (isGroup(entry)) {
      const opened = entry.active;
      return (
        <NavLink
          key={entry.key}
          label={entry.label}
          leftSection={entry.icon}
          // Default-open when we're already inside the group so the
          // active child is visible without an extra click; users can
          // still toggle it closed.
          defaultOpened={opened}
          // The parent itself isn't directly clickable — child links
          // own navigation. Marking it active when one of its children
          // is matches the highlight users expect from a sidebar.
          active={entry.active}
          childrenOffset={28}
        >
          {entry.items.map((item) => {
            const to = `${entry.to}/${item.key}`;
            return (
              <NavLink
                key={item.key}
                component={Link}
                to={to}
                label={item.label}
                leftSection={item.icon}
                active={
                  pathname === to || pathname.startsWith(`${to}/`)
                }
                onClick={onNavigate}
              />
            );
          })}
        </NavLink>
      );
    }
    return (
      <NavLink
        key={entry.key}
        component={Link}
        to={entry.to}
        label={entry.label}
        leftSection={entry.icon}
        active={entry.active}
        onClick={onNavigate}
      />
    );
  });
}
