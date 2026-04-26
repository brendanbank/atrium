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
import { useAppConfig } from '@/hooks/useAppConfig';
import { ME_QUERY_KEY } from '@/hooks/useAuth';
import { CaptchaWidget } from '@/components/CaptchaWidget';
import type { TOTPState } from '@/hooks/useTOTP';

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const { data: appConfig } = useAppConfig();
  const allowSignup = appConfig?.auth?.allow_signup === true;
  const captchaProvider = appConfig?.auth?.captcha_provider ?? 'none';
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);

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
    if (captchaProvider !== 'none' && !captchaToken) {
      setError(t('captcha.required'));
      return;
    }
    setSubmitting(true);
    try {
      await login(email, password, captchaToken);
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
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })
        .response;
      const status = resp?.status;
      const detail = resp?.data?.detail ?? '';
      if (status === 400 && detail.toLowerCase().includes('captcha')) {
        setError(t('captcha.failed'));
      } else if (status === 400 || status === 401) {
        setError(t('login.invalidCredentials'));
      } else {
        setError(t('login.unknownError'));
      }
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
              <CaptchaWidget onToken={setCaptchaToken} />
              {error && <Alert color="red">{error}</Alert>}
              <Button type="submit" fullWidth loading={submitting}>
                {t('login.submit')}
              </Button>
              <Anchor component={Link} to="/forgot-password" size="sm" ta="center">
                {t('login.forgotPassword')}
              </Anchor>
              {allowSignup && (
                <Anchor component={Link} to="/register" size="sm" ta="center">
                  {t('login.signupCta')}
                </Anchor>
              )}
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}
