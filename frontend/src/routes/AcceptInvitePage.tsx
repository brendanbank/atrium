// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react';
import {
  Alert,
  Button,
  Center,
  Container,
  Paper,
  PasswordInput,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { acceptInvite } from '@/lib/auth';

export function AcceptInvitePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const form = useForm({
    initialValues: { password: '', confirm: '' },
    validate: {
      password: (v) =>
        v.length >= 8 ? null : t('acceptInvite.passwordTooShort'),
      confirm: (v, values) =>
        v === values.password ? null : t('acceptInvite.passwordMismatch'),
    },
  });

  if (!token) {
    return (
      <Center h="100vh">
        <Container size={420}>
          <Alert color="red" title={t('acceptInvite.missingTokenTitle')}>
            {t('acceptInvite.missingTokenBody')}
          </Alert>
        </Container>
      </Center>
    );
  }

  const handleSubmit = form.onSubmit(async ({ password }) => {
    setError(null);
    setSubmitting(true);
    try {
      await acceptInvite(token, password);
      setSuccess(true);
      setTimeout(() => navigate('/login', { replace: true }), 1500);
    } catch (err) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })
        .response;
      if (resp?.status === 410) {
        setError(t('acceptInvite.expiredOrRevoked'));
      } else if (resp?.status === 409) {
        setError(t('acceptInvite.alreadyAccepted'));
      } else if (resp?.status === 404) {
        setError(t('acceptInvite.notFound'));
      } else {
        setError(resp?.data?.detail ?? t('acceptInvite.unknownError'));
      }
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Title ta="center" mb="lg">
          {t('acceptInvite.title')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <form onSubmit={handleSubmit}>
            <Stack>
              <Text c="dimmed" size="sm">
                {t('acceptInvite.description')}
              </Text>
              <PasswordInput
                label={t('acceptInvite.password')}
                required
                autoFocus
                autoComplete="new-password"
                {...form.getInputProps('password')}
              />
              <PasswordInput
                label={t('acceptInvite.confirmPassword')}
                required
                autoComplete="new-password"
                {...form.getInputProps('confirm')}
              />
              {error && <Alert color="red">{error}</Alert>}
              {success && (
                <Alert color="teal">{t('acceptInvite.success')}</Alert>
              )}
              <Button type="submit" fullWidth loading={submitting} disabled={success}>
                {t('acceptInvite.submit')}
              </Button>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}
