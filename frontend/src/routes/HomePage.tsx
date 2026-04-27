// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Button, Container, Group, Stack, Text, Title } from '@mantine/core';
import { IconBell, IconSettings, IconUser } from '@tabler/icons-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { HostHomeWidgets } from '@/components/HostHomeWidgets';
import { useMe } from '@/hooks/useAuth';

/** Minimal landing page. Host apps replace this with whatever
 *  dashboard makes sense for them; Atrium ships only the shell. */
export function HomePage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const isAdmin = me?.roles.includes('admin') ?? false;

  return (
    <Container size={680}>
      <Stack gap="md">
        <HostHomeWidgets />
        <Title order={2}>
          {me?.full_name
            ? t('home.welcomeNamed', { name: me.full_name })
            : t('home.welcome')}
        </Title>
        <Text c="dimmed">{t('home.intro')}</Text>
        <Group>
          <Button
            component={Link}
            to="/profile"
            variant="light"
            leftSection={<IconUser size={16} />}
          >
            {t('nav.profile')}
          </Button>
          <Button
            component={Link}
            to="/notifications"
            variant="light"
            leftSection={<IconBell size={16} />}
          >
            {t('nav.notifications')}
          </Button>
          {isAdmin && (
            <Button
              component={Link}
              to="/admin"
              variant="light"
              leftSection={<IconSettings size={16} />}
            >
              {t('nav.admin')}
            </Button>
          )}
        </Group>
      </Stack>
    </Container>
  );
}
