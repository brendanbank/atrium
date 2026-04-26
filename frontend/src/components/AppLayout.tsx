import {
  AppShell,
  Avatar,
  Burger,
  Button,
  Group,
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
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { useMe, useLogout } from '@/hooks/useAuth';

import { ImpersonationBanner } from './ImpersonationBanner';
import { NotificationsBell } from './NotificationsBell';

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const { t, i18n } = useTranslation();
  const { data: me } = useMe();
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

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={4}>{t('app.title')}</Title>
          </Group>
          <Group gap="xs">
            {me && <NotificationsBell />}
            <Select
              size="xs"
              aria-label={t('common.language')}
              value={i18n.language.startsWith('nl') ? 'nl' : 'en'}
              onChange={(v) => v && i18n.changeLanguage(v)}
              data={[
                { value: 'en', label: 'EN' },
                { value: 'nl', label: 'NL' },
              ]}
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
      </AppShell.Navbar>

      <AppShell.Main>
        <ImpersonationBanner />
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
