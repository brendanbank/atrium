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

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const form = useForm({
    initialValues: { email: '' },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : t('login.invalidEmail')),
    },
  });

  const handleSubmit = form.onSubmit(async ({ email }) => {
    setSubmitting(true);
    try {
      await forgotPassword(email);
    } finally {
      setSubmitting(false);
      // Always show success to avoid email enumeration.
      setDone(true);
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
