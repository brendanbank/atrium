// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Button, Container, Group, Stack, Text, Title } from '@mantine/core';
import { IconBell, IconSettings, IconUser } from '@tabler/icons-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { HostHomeWidgets } from '@/components/HostHomeWidgets';
import { useMe } from '@/hooks/useAuth';
import { getHomeWidgets } from '@/host/registry';

/** Minimal landing page. Host apps replace this with whatever
 *  dashboard makes sense for them; Atrium ships only the shell.
 *
 *  ``HostHomeWidgets`` is rendered outside the welcome Container so
 *  widgets that opt into ``width: 'wide'`` or ``'full'`` can break
 *  out of the 680px column. The atrium-shipped welcome content stays
 *  in the narrow column.
 *
 *  The ``home.intro`` line is integrator-facing copy: it tells someone
 *  who's just spun up a fresh starter where to hook their own pages.
 *  Once any host widget is registered the intro is noise, so we hide
 *  it. The greeting + the action buttons stay either way — they're
 *  useful chrome regardless of whether a host owns the page. */
export function HomePage() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const isAdmin = me?.roles.includes('admin') ?? false;
  const hasHostWidgets = getHomeWidgets().length > 0;

  return (
    <Stack gap="md">
      <HostHomeWidgets />
      <Container size={680}>
        <Stack gap="md">
          <Title order={2}>
            {me?.full_name
              ? t('home.welcomeNamed', { name: me.full_name })
              : t('home.welcome')}
          </Title>
          {!hasHostWidgets && <Text c="dimmed">{t('home.intro')}</Text>}
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
    </Stack>
  );
}
