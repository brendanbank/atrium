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
  IconBell,
  IconHome,
  IconSettings,
  IconUser,
  IconLogout,
} from '@tabler/icons-react';
import { useEffect, useRef } from 'react';
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

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

  // Atrium has no built-in admin role; show the admin link to anyone
  // holding the conventional ``admin`` RBAC role. Host apps can swap
  // this for their own role code as needed.
  const isAdmin = me?.roles.includes('admin') ?? false;

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
          isAdmin,
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

/** Built-in nav slots use 100/200/300 so a host can interleave with
 *  ``order: 150`` (between Home and Notifications), ``250`` (between
 *  Notifications and Admin), or any value > 300 to land below them. A
 *  host item with no ``order`` keeps insertion order and lands after
 *  everything that does have one — including the built-ins. */
const NAV_ORDER = {
  home: 100,
  notifications: 200,
  admin: 300,
} as const;

function buildNavLinks(args: {
  me: CurrentUser | null;
  isAdmin: boolean;
  pathname: string;
  onNavigate: () => void;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const { me, isAdmin, pathname, onNavigate, t } = args;

  const builtins: (NavItem & { active: boolean })[] = [
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
  if (isAdmin) {
    builtins.push({
      key: '__atrium_admin',
      label: t('nav.admin'),
      to: '/admin',
      icon: <IconSettings size={16} />,
      order: NAV_ORDER.admin,
      active: pathname.startsWith('/admin'),
    });
  }

  const hostItems = getNavItems().filter((item) =>
    item.condition ? item.condition({ me }) : true,
  );

  // Merge then re-sort. ``getNavItems`` already sorts host items by
  // ``order``; re-sorting the merged list with the same comparator
  // splices the built-ins in at the right place.
  const merged: (NavItem & { active?: boolean })[] = [
    ...builtins,
    ...hostItems,
  ];
  merged.sort((a, b) => {
    const ao = a.order;
    const bo = b.order;
    if (ao === undefined && bo === undefined) return 0;
    if (ao === undefined) return 1;
    if (bo === undefined) return -1;
    return ao - bo;
  });

  return merged.map((item) => (
    <NavLink
      key={item.key}
      component={Link}
      to={item.to}
      label={item.label}
      leftSection={item.icon}
      active={
        item.active ??
        (pathname === item.to || pathname.startsWith(`${item.to}/`))
      }
      onClick={onNavigate}
    />
  ));
}
