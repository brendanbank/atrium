// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Center,
  Code,
  Container,
  Group,
  Loader,
  Paper,
  PinInput,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import QRCode from 'qrcode';

import {
  useEmailOTPConfirm,
  useEmailOTPRequest,
  useEmailOTPSetup,
  useEmailOTPVerify,
  useTOTPConfirm,
  useTOTPSetup,
  useTOTPState,
  useTOTPVerify,
} from '@/hooks/useTOTP';
import {
  useWebAuthnAuthenticate,
  useWebAuthnRegister,
} from '@/hooks/useWebAuthn';

/**
 * /2fa page — hosts both enrollment and returning-user challenge.
 *
 * Challenge flow: if the user has a WebAuthn credential we fire the
 * browser ceremony on mount — no "Tap your security key" intermediate
 * screen. If WebAuthn fails or isn't enrolled we fall back to a picker
 * of the remaining methods (TOTP / email OTP).
 */
export function TwoFactorPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: state, isLoading, isFetching, refetch } = useTOTPState();

  const from = new URLSearchParams(location.search).get('from') ?? '/';

  useEffect(() => {
    // Wait for the background refetch before trusting `session_passed`:
    // after a logout+re-login the cache may still carry the previous
    // session's `true`, and bouncing to `from` with a partial session
    // would just redirect back here via the 403/totp_required path.
    if (isFetching) return;
    if (state?.session_passed) navigate(from, { replace: true });
  }, [state, isFetching, navigate, from]);

  if (isLoading || !state) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }

  const anyConfirmed =
    state.confirmed ||
    state.email_otp_confirmed ||
    state.webauthn_credential_count > 0;
  if (anyConfirmed) {
    return <TwoFactorChallenge state={state} onVerified={() => refetch()} />;
  }
  return <TwoFactorSetup state={state} onChange={() => refetch()} />;
}


// ---------- Setup (first enrollment) ----------

function TwoFactorSetup({
  state,
  onChange,
}: {
  state: {
    enrolled: boolean;
    confirmed: boolean;
    email_otp_enrolled: boolean;
    email_otp_confirmed: boolean;
  };
  onChange: () => void;
}) {
  const { t } = useTranslation();
  const [method, setMethod] = useState<'pick' | 'totp' | 'email' | 'webauthn'>(
    () => {
      // Resume a half-finished enrollment automatically.
      if (state.enrolled && !state.confirmed) return 'totp';
      if (state.email_otp_enrolled && !state.email_otp_confirmed) return 'email';
      return 'pick';
    },
  );

  if (method === 'pick') {
    return (
      <Center h="100vh">
        <Container size={480} w="100%">
          <Title ta="center" mb="lg" order={2}>
            {t('twoFactor.setupTitle')}
          </Title>
          <Paper withBorder shadow="md" p="xl" radius="md">
            <Stack>
              <Text size="sm" c="dimmed">
                {t('twoFactor.pickMethodIntro')}
              </Text>
              <Button onClick={() => setMethod('totp')}>
                {t('twoFactor.useAuthenticator')}
              </Button>
              <Button variant="light" onClick={() => setMethod('email')}>
                {t('twoFactor.useEmail')}
              </Button>
              <Button variant="light" onClick={() => setMethod('webauthn')}>
                {t('twoFactor.useSecurityKey')}
              </Button>
            </Stack>
          </Paper>
        </Container>
      </Center>
    );
  }
  if (method === 'totp') {
    return <TOTPSetupFlow onBack={() => setMethod('pick')} onConfirmed={onChange} />;
  }
  if (method === 'email') {
    return (
      <EmailOTPSetupFlow
        onBack={() => setMethod('pick')}
        onConfirmed={onChange}
      />
    );
  }
  return (
    <WebAuthnSetupFlow
      onBack={() => setMethod('pick')}
      onConfirmed={onChange}
    />
  );
}


function TOTPSetupFlow({
  onBack,
  onConfirmed,
}: {
  onBack: () => void;
  onConfirmed: () => void;
}) {
  const { t } = useTranslation();
  const setup = useTOTPSetup();
  const confirm = useTOTPConfirm();
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // ``/auth/totp/setup`` is server-side idempotent (reuses an
    // unconfirmed secret), so it's OK if StrictMode invokes this
    // effect twice. Every success writes the same QR, the overwrite
    // is a no-op. No ref gate.
    setup.mutate(undefined, {
      onSuccess: async (data) => {
        try {
          setSecret(data.secret);
          const dataUrl = await QRCode.toDataURL(data.provisioning_uri, {
            width: 240,
            margin: 1,
          });
          setQrDataUrl(dataUrl);
        } catch (err) {
          console.error('QR render failed', err);
          setError(t('twoFactor.invalidCode'));
        }
      },
      onError: (err) => {
        console.error('TOTP setup failed', err);
        setError(t('twoFactor.invalidCode'));
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await confirm.mutateAsync(code);
      notifications.show({ color: 'teal', message: t('twoFactor.setupSuccess') });
      onConfirmed();
    } catch {
      setError(t('twoFactor.invalidCode'));
    }
  };

  return (
    <Center h="100vh">
      <Container size={480} w="100%">
        <Title ta="center" mb="lg" order={2}>
          {t('twoFactor.setupTitle')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <Stack>
            <Text size="sm" c="dimmed">
              {t('twoFactor.setupIntro')}
            </Text>
            {qrDataUrl ? (
              <Center>
                <img
                  src={qrDataUrl}
                  alt="TOTP QR code"
                  style={{ maxWidth: 240, borderRadius: 8 }}
                />
              </Center>
            ) : (
              <Center>
                <Loader />
              </Center>
            )}
            {secret && (
              <Text size="xs" ta="center" c="dimmed">
                {t('twoFactor.manualSecret')}: <Code>{secret}</Code>
              </Text>
            )}
            <form onSubmit={handleSubmit}>
              <Stack>
                <Text size="sm" fw={500}>
                  {t('twoFactor.enterFirstCode')}
                </Text>
                <Center>
                  <PinInput
                    length={6}
                    type="number"
                    oneTimeCode
                    value={code}
                    onChange={setCode}
                    autoFocus
                  />
                </Center>
                {error && <Alert color="red">{error}</Alert>}
                <Group justify="space-between">
                  <Button variant="subtle" onClick={onBack}>
                    {t('twoFactor.back')}
                  </Button>
                  <Button type="submit" loading={confirm.isPending} disabled={code.length < 6}>
                    {t('twoFactor.confirmSubmit')}
                  </Button>
                </Group>
              </Stack>
            </form>
          </Stack>
        </Paper>
      </Container>
    </Center>
  );
}


function EmailOTPSetupFlow({
  onBack,
  onConfirmed,
}: {
  onBack: () => void;
  onConfirmed: () => void;
}) {
  const { t } = useTranslation();
  const setup = useEmailOTPSetup();
  const confirm = useEmailOTPConfirm();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  // React StrictMode invokes effects twice in dev. The mail-send
  // isn't idempotent (each call queues another email + a fresh code)
  // so dedupe with a ref.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setup.mutate(undefined, {
      onSuccess: () => setSent(true),
      onError: () => setError(t('twoFactor.emailSendFailed')),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await confirm.mutateAsync(code);
      notifications.show({ color: 'teal', message: t('twoFactor.setupSuccess') });
      onConfirmed();
    } catch {
      setError(t('twoFactor.invalidCode'));
    }
  };

  return (
    <Center h="100vh">
      <Container size={480} w="100%">
        <Title ta="center" mb="lg" order={2}>
          {t('twoFactor.emailSetupTitle')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <form onSubmit={handleSubmit}>
            <Stack>
              <Text size="sm" c="dimmed" ta="center">
                {sent ? t('twoFactor.emailSentIntro') : t('twoFactor.emailSending')}
              </Text>
              <Center>
                <PinInput
                  length={6}
                  type="number"
                  oneTimeCode
                  value={code}
                  onChange={setCode}
                  autoFocus
                />
              </Center>
              {error && <Alert color="red">{error}</Alert>}
              <Group justify="space-between">
                <Button variant="subtle" onClick={onBack}>
                  {t('twoFactor.back')}
                </Button>
                <Button type="submit" loading={confirm.isPending} disabled={code.length < 6}>
                  {t('twoFactor.confirmSubmit')}
                </Button>
              </Group>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}


// ---------- Challenge (returning user with a partial session) ----------

type ChallengePhase = 'webauthn' | 'picker' | 'totp' | 'email';

function TwoFactorChallenge({
  state,
  onVerified,
}: {
  state: {
    confirmed: boolean;
    email_otp_confirmed: boolean;
    webauthn_credential_count: number;
  };
  onVerified: () => void;
}) {
  const { t } = useTranslation();
  const authenticate = useWebAuthnAuthenticate();

  const hasWebAuthn = state.webauthn_credential_count > 0;
  const fallbackMethods: Array<'totp' | 'email'> = [];
  if (state.confirmed) fallbackMethods.push('totp');
  if (state.email_otp_confirmed) fallbackMethods.push('email');

  // Initial phase: WebAuthn first if registered (auto-triggered on mount),
  // otherwise pick fallback. Single fallback → land directly on its form.
  const initialPhase: ChallengePhase = hasWebAuthn
    ? 'webauthn'
    : fallbackMethods.length > 1
      ? 'picker'
      : (fallbackMethods[0] ?? 'picker');

  const [phase, setPhase] = useState<ChallengePhase>(initialPhase);
  const [webAuthnError, setWebAuthnError] = useState<string | null>(null);
  // StrictMode double-invokes effects; a single WebAuthn ceremony per
  // entry into the 'webauthn' phase is what we want.
  const webAuthnStarted = useRef(false);

  useEffect(() => {
    if (phase !== 'webauthn') return;
    if (webAuthnStarted.current) return;
    webAuthnStarted.current = true;
    authenticate
      .mutateAsync()
      .then(() => {
        onVerified();
      })
      .catch((err) => {
        const msg = (err as Error)?.message ?? t('twoFactor.webauthnFailed');
        setWebAuthnError(msg);
        // If fallback methods exist, move the user to the picker so they
        // can choose one; otherwise keep them here and offer retry.
        if (fallbackMethods.length > 0) setPhase('picker');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const retryWebAuthn = () => {
    webAuthnStarted.current = false;
    setWebAuthnError(null);
    setPhase('webauthn');
  };

  if (phase === 'webauthn') {
    return (
      <Center h="100vh">
        <Container size={420} w="100%">
          <Title ta="center" mb="lg" order={2}>
            {t('twoFactor.challengeTitle')}
          </Title>
          <Paper withBorder shadow="md" p="xl" radius="md">
            <Stack align="center">
              {webAuthnError ? (
                <>
                  <Alert color="red" style={{ width: '100%' }}>
                    {webAuthnError}
                  </Alert>
                  <Button onClick={retryWebAuthn} loading={authenticate.isPending}>
                    {t('twoFactor.webauthnRetry')}
                  </Button>
                </>
              ) : (
                <>
                  <Loader />
                  <Text size="sm" c="dimmed" ta="center">
                    {t('twoFactor.webauthnWaiting')}
                  </Text>
                </>
              )}
            </Stack>
          </Paper>
        </Container>
      </Center>
    );
  }

  if (phase === 'picker') {
    return (
      <Center h="100vh">
        <Container size={420} w="100%">
          <Title ta="center" mb="lg" order={2}>
            {t('twoFactor.challengeTitle')}
          </Title>
          <Paper withBorder shadow="md" p="xl" radius="md">
            <Stack>
              {webAuthnError && <Alert color="red">{webAuthnError}</Alert>}
              <Text size="sm" c="dimmed" ta="center">
                {t('twoFactor.pickChallengeMethod')}
              </Text>
              {fallbackMethods.includes('totp') && (
                <Button onClick={() => setPhase('totp')}>
                  {t('twoFactor.useAuthenticator')}
                </Button>
              )}
              {fallbackMethods.includes('email') && (
                <Button variant="light" onClick={() => setPhase('email')}>
                  {t('twoFactor.useEmail')}
                </Button>
              )}
              {hasWebAuthn && (
                <Button variant="subtle" onClick={retryWebAuthn}>
                  {t('twoFactor.webauthnRetry')}
                </Button>
              )}
            </Stack>
          </Paper>
        </Container>
      </Center>
    );
  }

  const canGoBack = hasWebAuthn || fallbackMethods.length > 1;
  const backHandler = canGoBack ? () => setPhase('picker') : undefined;
  if (phase === 'totp') {
    return <TOTPChallengeForm onVerified={onVerified} onBack={backHandler} />;
  }
  return <EmailOTPChallengeForm onVerified={onVerified} onBack={backHandler} />;
}


function TOTPChallengeForm({
  onVerified,
  onBack,
}: {
  onVerified: () => void;
  onBack?: () => void;
}) {
  const { t } = useTranslation();
  const verify = useTOTPVerify();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await verify.mutateAsync(code);
      onVerified();
    } catch {
      setError(t('twoFactor.invalidCode'));
      setCode('');
    }
  };

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Title ta="center" mb="lg" order={2}>
          {t('twoFactor.challengeTitle')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <form onSubmit={handleSubmit}>
            <Stack>
              <Text size="sm" c="dimmed" ta="center">
                {t('twoFactor.challengeIntro')}
              </Text>
              <Center>
                <PinInput
                  length={6}
                  type="number"
                  oneTimeCode
                  value={code}
                  onChange={setCode}
                  autoFocus
                />
              </Center>
              {error && <Alert color="red">{error}</Alert>}
              <Group justify="space-between">
                {onBack ? (
                  <Button variant="subtle" onClick={onBack}>
                    {t('twoFactor.back')}
                  </Button>
                ) : (
                  <div />
                )}
                <Button type="submit" loading={verify.isPending} disabled={code.length < 6}>
                  {t('twoFactor.verifySubmit')}
                </Button>
              </Group>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}


function EmailOTPChallengeForm({
  onVerified,
  onBack,
}: {
  onVerified: () => void;
  onBack?: () => void;
}) {
  const { t } = useTranslation();
  const requestCode = useEmailOTPRequest();
  const verify = useEmailOTPVerify();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    requestCode.mutate(undefined, {
      onSuccess: () => setSent(true),
      onError: () => setError(t('twoFactor.emailSendFailed')),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await verify.mutateAsync(code);
      onVerified();
    } catch {
      setError(t('twoFactor.invalidCode'));
      setCode('');
    }
  };

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Title ta="center" mb="lg" order={2}>
          {t('twoFactor.emailChallengeTitle')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <form onSubmit={handleSubmit}>
            <Stack>
              <Text size="sm" c="dimmed" ta="center">
                {sent ? t('twoFactor.emailSentIntro') : t('twoFactor.emailSending')}
              </Text>
              <Center>
                <PinInput
                  length={6}
                  type="number"
                  oneTimeCode
                  value={code}
                  onChange={setCode}
                  autoFocus
                />
              </Center>
              {error && <Alert color="red">{error}</Alert>}
              <Group justify="space-between">
                {onBack ? (
                  <Button variant="subtle" onClick={onBack}>
                    {t('twoFactor.back')}
                  </Button>
                ) : (
                  <Button
                    variant="subtle"
                    onClick={() => {
                      setCode('');
                      requestCode.mutate();
                    }}
                    loading={requestCode.isPending}
                  >
                    {t('twoFactor.resendCode')}
                  </Button>
                )}
                <Button type="submit" loading={verify.isPending} disabled={code.length < 6}>
                  {t('twoFactor.verifySubmit')}
                </Button>
              </Group>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}


// ---------- WebAuthn flows ----------

function WebAuthnSetupFlow({
  onBack,
  onConfirmed,
}: {
  onBack: () => void;
  onConfirmed: () => void;
}) {
  const { t } = useTranslation();
  const register = useWebAuthnRegister();
  const [label, setLabel] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await register.mutateAsync(label.trim());
      notifications.show({
        color: 'teal',
        message: t('twoFactor.webauthnRegistered'),
      });
      onConfirmed();
    } catch (err) {
      const msg = (err as Error)?.message ?? t('twoFactor.webauthnFailed');
      setError(msg);
    }
  };

  return (
    <Center h="100vh">
      <Container size={480} w="100%">
        <Title ta="center" mb="lg" order={2}>
          {t('twoFactor.webauthnSetupTitle')}
        </Title>
        <Paper withBorder shadow="md" p="xl" radius="md">
          <form onSubmit={submit}>
            <Stack>
              <Text size="sm" c="dimmed">
                {t('twoFactor.webauthnSetupIntro')}
              </Text>
              <Text size="sm" fw={500}>
                {t('twoFactor.webauthnLabel')}
              </Text>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('twoFactor.webauthnLabelPlaceholder')}
                autoFocus
                style={{
                  padding: '8px 12px',
                  border: '1px solid var(--mantine-color-gray-4)',
                  borderRadius: 4,
                  fontSize: 14,
                }}
              />
              {error && <Alert color="red">{error}</Alert>}
              <Group justify="space-between">
                <Button variant="subtle" onClick={onBack}>
                  {t('twoFactor.back')}
                </Button>
                <Button
                  type="submit"
                  loading={register.isPending}
                  disabled={label.trim().length === 0}
                >
                  {t('twoFactor.webauthnRegisterSubmit')}
                </Button>
              </Group>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  );
}

