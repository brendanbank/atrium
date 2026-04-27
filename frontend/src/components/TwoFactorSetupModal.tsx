// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Center,
  Code,
  Group,
  Loader,
  Modal,
  PinInput,
  Stack,
  Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import QRCode from 'qrcode';

import {
  useEmailOTPConfirm,
  useEmailOTPSetup,
  useTOTPConfirm,
  useTOTPSetup,
} from '@/hooks/useTOTP';

type Method = 'totp' | 'email';

interface Props {
  opened: boolean;
  method: Method;
  onClose: () => void;
  /** Called when the user successfully enrolls the chosen method. */
  onEnrolled: () => void;
}

/**
 * Setup flow for either TOTP or email OTP, rendered in a modal so
 * the user can add a second method from the profile page without
 * being bounced through ``/2fa`` (which is for the pre-session
 * challenge flow and redirects away if the session is already full).
 */
export function TwoFactorSetupModal({ opened, method, onClose, onEnrolled }: Props) {
  const { t } = useTranslation();

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        method === 'totp'
          ? t('twoFactor.setupTitle')
          : t('twoFactor.emailSetupTitle')
      }
      centered
      size="md"
    >
      {method === 'totp' ? (
        <TOTPSetupInner onEnrolled={onEnrolled} onClose={onClose} />
      ) : (
        <EmailOTPSetupInner onEnrolled={onEnrolled} onClose={onClose} />
      )}
    </Modal>
  );
}


function TOTPSetupInner({
  onEnrolled,
  onClose,
}: {
  onEnrolled: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const setup = useTOTPSetup();
  const confirm = useTOTPConfirm();
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await confirm.mutateAsync(code);
      notifications.show({ color: 'teal', message: t('twoFactor.setupSuccess') });
      onEnrolled();
      onClose();
    } catch {
      setError(t('twoFactor.invalidCode'));
    }
  };

  return (
    <form onSubmit={submit}>
      <Stack>
        <Text size="sm" c="dimmed">
          {t('twoFactor.setupIntro')}
        </Text>
        {qrDataUrl ? (
          <Center>
            <img src={qrDataUrl} alt="TOTP QR code" style={{ maxWidth: 220, borderRadius: 8 }} />
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
        <Text size="sm" fw={500}>
          {t('twoFactor.enterFirstCode')}
        </Text>
        <Center>
          <PinInput length={6} type="number" oneTimeCode value={code} onChange={setCode} autoFocus />
        </Center>
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" loading={confirm.isPending} disabled={code.length < 6}>
            {t('twoFactor.confirmSubmit')}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}


function EmailOTPSetupInner({
  onEnrolled,
  onClose,
}: {
  onEnrolled: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const setup = useEmailOTPSetup();
  const confirm = useEmailOTPConfirm();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  // Mail send is not idempotent — each call queues another email and
  // a fresh code. StrictMode invokes this effect twice in dev, so
  // dedupe with a ref.
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

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await confirm.mutateAsync(code);
      notifications.show({ color: 'teal', message: t('twoFactor.setupSuccess') });
      onEnrolled();
      onClose();
    } catch {
      setError(t('twoFactor.invalidCode'));
    }
  };

  return (
    <form onSubmit={submit}>
      <Stack>
        <Text size="sm" c="dimmed">
          {sent ? t('twoFactor.emailSentIntro') : t('twoFactor.emailSending')}
        </Text>
        <Center>
          <PinInput length={6} type="number" oneTimeCode value={code} onChange={setCode} autoFocus />
        </Center>
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" loading={confirm.isPending} disabled={code.length < 6}>
            {t('twoFactor.confirmSubmit')}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
