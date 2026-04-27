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
import { getNavItems } from '@/host/registry';

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
        <NavLink
          component={Link}
          to="/"
          label={t('nav.home')}
          leftSection={<IconHome size={16} />}
          active={location.pathname === '/'}
          onClick={close}
        />
        <NavLink
          component={Link}
          to="/notifications"
          label={t('nav.notifications')}
          leftSection={<IconBell size={16} />}
          active={location.pathname.startsWith('/notifications')}
          onClick={close}
        />
        {isAdmin && (
          <NavLink
            component={Link}
            to="/admin"
            label={t('nav.admin')}
            leftSection={<IconSettings size={16} />}
            active={location.pathname.startsWith('/admin')}
            onClick={close}
          />
        )}
        {getNavItems()
          .filter((item) =>
            item.condition ? item.condition({ me: me ?? null }) : true,
          )
          .map((item) => (
            <NavLink
              key={item.key}
              component={Link}
              to={item.to}
              label={item.label}
              leftSection={item.icon}
              active={
                location.pathname === item.to ||
                location.pathname.startsWith(`${item.to}/`)
              }
              onClick={close}
            />
          ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <AnnouncementBanner />
        <ImpersonationBanner />
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
