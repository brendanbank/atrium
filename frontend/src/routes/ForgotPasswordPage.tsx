import { useState } from 'react';
import {
  Alert,
  Anchor,
  Button,
  Center,
  Container,
  Paper,
  Stack,
  TextInput,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { forgotPassword } from '@/lib/auth';
import { CaptchaWidget } from '@/components/CaptchaWidget';
import { useAppConfig } from '@/hooks/useAppConfig';

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const { data: appConfig } = useAppConfig();
  const captchaProvider = appConfig?.auth?.captcha_provider ?? 'none';
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);

  const form = useForm({
    initialValues: { email: '' },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : t('login.invalidEmail')),
    },
  });

  const handleSubmit = form.onSubmit(async ({ email }) => {
    setError(null);
    if (captchaProvider !== 'none' && !captchaToken) {
      setError(t('captcha.required'));
      return;
    }
    setSubmitting(true);
    try {
      await forgotPassword(email, captchaToken);
      setDone(true);
    } catch (err) {
      // Avoid email enumeration on the happy path, but a captcha
      // failure is a client-side problem the user can fix; surface
      // it instead of swallowing.
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })
        .response;
      const detail = resp?.data?.detail ?? '';
      if (resp?.status === 400 && detail.toLowerCase().includes('captcha')) {
        setError(t('captcha.failed'));
      } else {
        setDone(true);
      }
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Title ta="center" mb="lg">
          {t('forgotPassword.title')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          {done ? (
            <Stack>
              <Alert color="teal">{t('forgotPassword.emailSent')}</Alert>
              <Anchor component={Link} to="/login" ta="center">
                {t('forgotPassword.backToLogin')}
              </Anchor>
            </Stack>
          ) : (
            <form onSubmit={handleSubmit}>
              <Stack>
                <TextInput
                  label={t('login.email')}
                  required
                  autoFocus
                  {...form.getInputProps('email')}
                />
                <CaptchaWidget onToken={setCaptchaToken} />
                {error && <Alert color="red">{error}</Alert>}
                <Button type="submit" fullWidth loading={submitting}>
                  {t('forgotPassword.submit')}
                </Button>
                <Anchor component={Link} to="/login" size="sm" ta="center">
                  {t('forgotPassword.backToLogin')}
                </Anchor>
              </Stack>
            </form>
          )}
        </Paper>
      </Container>
    </Center>
  );
}
