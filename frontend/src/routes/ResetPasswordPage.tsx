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
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { resetPassword } from '@/lib/auth';

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [error, setError] = useState<string | null>(null);
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
          <Alert color="red">{t('resetPassword.missingToken')}</Alert>
        </Container>
      </Center>
    );
  }

  const handleSubmit = form.onSubmit(async ({ password }) => {
    setError(null);
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      navigate('/login', { replace: true });
    } catch (err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      setError(resp?.data?.detail ?? t('resetPassword.unknownError'));
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Title ta="center" mb="lg">
          {t('resetPassword.title')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <form onSubmit={handleSubmit}>
            <Stack>
              <PasswordInput
                label={t('resetPassword.newPassword')}
                required
                autoFocus
                {...form.getInputProps('password')}
              />
              <PasswordInput
                label={t('acceptInvite.confirmPassword')}
                required
                {...form.getInputProps('confirm')}
              />
              {error && <Alert color="red">{error}</Alert>}
              <Button type="submit" fullWidth loading={submitting}>
                {t('resetPassword.submit')}
              </Button>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}
