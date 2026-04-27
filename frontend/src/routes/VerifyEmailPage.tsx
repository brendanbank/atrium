// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Anchor,
  Center,
  Container,
  Loader,
  Paper,
  Stack,
  Title,
} from '@mantine/core';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { verifyEmail } from '@/lib/auth';

type Status = 'pending' | 'success' | 'invalid' | 'missing';

export function VerifyEmailPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [status, setStatus] = useState<Status>(token ? 'pending' : 'missing');
  // React 18 StrictMode double-mounts in dev; without this guard the
  // verify endpoint runs twice and the second call sees a "consumed"
  // token and returns 400.
  const fired = useRef(false);

  useEffect(() => {
    if (!token || fired.current) return;
    fired.current = true;
    verifyEmail(token)
      .then(() => setStatus('success'))
      .catch(() => setStatus('invalid'));
  }, [token]);

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Title ta="center" mb="lg">
          {t('verifyEmail.title')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <Stack>
            {status === 'pending' && (
              <Center>
                <Loader />
              </Center>
            )}
            {status === 'success' && (
              <Alert color="teal">{t('verifyEmail.success')}</Alert>
            )}
            {status === 'invalid' && (
              <Alert color="red">{t('verifyEmail.invalid')}</Alert>
            )}
            {status === 'missing' && (
              <Alert color="red">{t('verifyEmail.missing')}</Alert>
            )}
            <Anchor component={Link} to="/login" size="sm" ta="center">
              {t('forgotPassword.backToLogin')}
            </Anchor>
          </Stack>
        </Paper>
      </Container>
    </Center>
  );
}
