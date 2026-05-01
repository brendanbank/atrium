// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * One-time plaintext display for a freshly-minted PAT.
 *
 * The plaintext arrives via the parent component's mutation handler
 * and is passed in through ``token``. It lives in the parent's React
 * state (no TanStack Query cache, no localStorage). Dismiss wipes
 * the prop reference; nothing in this component persists beyond the
 * modal lifetime.
 *
 * Spec §3 / issue #115: no auto-dismiss — the user must click "I've
 * copied it" so they don't lose the only visible copy by clicking
 * away accidentally.
 */
import { useState } from 'react';
import {
  Alert,
  Button,
  CopyButton,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Text,
} from '@mantine/core';
import { IconAlertTriangle, IconCheck, IconCopy } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

interface TokenRevealModalProps {
  opened: boolean;
  /** Plaintext token to display, or ``null`` when nothing is in flight.
   *  The parent owns the React state; this modal renders it but never
   *  echoes it elsewhere. */
  token: string | null;
  /** Display label so the user knows which token they're copying. */
  name: string | null;
  onClose: () => void;
}

export function TokenRevealModal({
  opened,
  token,
  name,
  onClose,
}: TokenRevealModalProps) {
  const { t } = useTranslation();
  const [revealed, setRevealed] = useState(false);

  const handleClose = () => {
    setRevealed(false);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      // No auto-dismiss + no close-on-outside-click. The user must
      // explicitly acknowledge they've copied the token.
      closeOnClickOutside={false}
      closeOnEscape={false}
      withCloseButton={false}
      title={t('tokens.reveal.title')}
      size="lg"
      centered
    >
      <Stack gap="sm">
        <Alert
          color="yellow"
          icon={<IconAlertTriangle size={16} />}
          title={t('tokens.reveal.warningTitle')}
        >
          {t('tokens.reveal.warningBody')}
        </Alert>

        {name ? (
          <Text size="sm">
            <strong>{t('tokens.reveal.nameLabel')}:</strong> {name}
          </Text>
        ) : null}

        <PasswordInput
          label={t('tokens.reveal.tokenLabel')}
          value={token ?? ''}
          readOnly
          visible={revealed}
          onVisibilityChange={setRevealed}
          // Selectable text — the user may copy-paste the prefix into a
          // support ticket later (see issue #115 note about token_prefix
          // being the only stable copyable handle).
          styles={{
            input: { fontFamily: 'var(--mantine-font-family-monospace)' },
          }}
          data-testid="token-reveal-input"
        />

        <Group justify="space-between">
          <CopyButton value={token ?? ''} timeout={2000}>
            {({ copied, copy }) => (
              <Button
                onClick={copy}
                variant="light"
                color={copied ? 'teal' : 'blue'}
                leftSection={
                  copied ? <IconCheck size={16} /> : <IconCopy size={16} />
                }
                disabled={!token}
                data-testid="token-reveal-copy"
              >
                {copied
                  ? t('tokens.reveal.copied')
                  : t('tokens.reveal.copy')}
              </Button>
            )}
          </CopyButton>
          <Button onClick={handleClose} data-testid="token-reveal-dismiss">
            {t('tokens.reveal.dismiss')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
