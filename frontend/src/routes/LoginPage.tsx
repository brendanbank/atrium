import { useState } from 'react';
import {
  Alert,
  Anchor,
  Button,
  Center,
  Container,
  Paper,
  PasswordInput,
  Stack,
  TextInput,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';

import { login } from '@/lib/auth';
import { api } from '@/lib/api';
import { ME_QUERY_KEY } from '@/hooks/useAuth';
import type { TOTPState } from '@/hooks/useTOTP';

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const form = useForm({
    initialValues: { email: '', password: '' },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : t('login.invalidEmail')),
      password: (v) => (v.length >= 1 ? null : t('login.passwordRequired')),
    },
  });

  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? '/';

  const handleSubmit = form.onSubmit(async ({ email, password }) => {
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      // Every fresh login starts with a partial session. /2fa picks
      // between the setup picker (no confirmed method yet) and the
      // challenge screen (one or more methods enrolled).
      const { data: state } = await api.get<TOTPState>('/auth/totp/state');
      if (!state.session_passed) {
        navigate(`/2fa?from=${encodeURIComponent(redirectTo)}`, {
          replace: true,
        });
        return;
      }
      // refetch (not just invalidate) so RequireAuth sees the fresh user
      // before we navigate — otherwise the cached `null` from the pre-login
      // probe bounces us back to /login.
      await qc.refetchQueries({ queryKey: ME_QUERY_KEY });
      navigate(redirectTo, { replace: true });
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 400 || status === 401
          ? t('login.invalidCredentials')
          : t('login.unknownError'),
      );
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Title ta="center" mb="lg">
          {t('app.title')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <form onSubmit={handleSubmit}>
            <Stack>
              <TextInput
                label={t('login.email')}
                placeholder="you@example.com"
                required
                autoFocus
                type="email"
                inputMode="email"
                autoComplete="email"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                {...form.getInputProps('email')}
              />
              <PasswordInput
                label={t('login.password')}
                required
                autoComplete="current-password"
                {...form.getInputProps('password')}
              />
              {error && <Alert color="red">{error}</Alert>}
              <Button type="submit" fullWidth loading={submitting}>
                {t('login.submit')}
              </Button>
              <Anchor component={Link} to="/forgot-password" size="sm" ta="center">
                {t('login.forgotPassword')}
              </Anchor>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}
