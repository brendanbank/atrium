// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Create-token form. Submits ``POST /auth/tokens`` and hands the
 * plaintext response off to the parent so it can show the reveal
 * modal. The parent owns the staged plaintext; this modal never
 * touches it.
 *
 * Scopes are picked from the user's current permissions (the only
 * scopes the server will accept). The expiry dropdown matches the
 * spec UX: 30 / 90 / 365 / Never; the "Never" option is hidden when
 * ``maxLifetimeDays`` is set so the user can't pick a value the
 * server will silently downcap.
 */
import { useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  MultiSelect,
  Select,
  Stack,
  Textarea,
  TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { useTranslation } from 'react-i18next';

import {
  useCreateToken,
  type CreateTokenPayload,
  type TokenCreated,
} from '@/hooks/useTokens';

interface TokenCreateModalProps {
  opened: boolean;
  onClose: () => void;
  /** Permissions the user currently holds. The scope picker only
   *  offers these — the server enforces the same intersection but a
   *  client-side filter prevents the user from picking an obviously
   *  out-of-reach scope and getting a 403. */
  availableScopes: string[];
  /** Cap for the expiry dropdown. ``null`` allows the "Never" option. */
  maxLifetimeDays: number | null;
  /** Called with the freshly-minted token once the API returns. The
   *  parent typically opens a reveal modal; the plaintext is never
   *  persisted in this modal. */
  onCreated: (created: TokenCreated) => void;
}

const DEFAULT_EXPIRIES = [30, 90, 365] as const;
type ExpiryChoice = '30' | '90' | '365' | 'never';

export function TokenCreateModal({
  opened,
  onClose,
  availableScopes,
  maxLifetimeDays,
  onCreated,
}: TokenCreateModalProps) {
  const { t } = useTranslation();
  const createToken = useCreateToken();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm<{
    name: string;
    description: string;
    scopes: string[];
    expiry: ExpiryChoice;
  }>({
    initialValues: {
      name: '',
      description: '',
      scopes: [],
      expiry: '90',
    },
    validate: {
      name: (v) =>
        v.trim().length === 0 ? t('tokens.create.nameRequired') : null,
      scopes: (v) =>
        v.length === 0 ? t('tokens.create.scopesRequired') : null,
    },
  });

  const handleClose = () => {
    form.reset();
    setSubmitError(null);
    onClose();
  };

  const expiryOptions = [
    ...DEFAULT_EXPIRIES.filter(
      (d) => maxLifetimeDays === null || d <= maxLifetimeDays,
    ).map((d) => ({
      value: String(d),
      label: t(`tokens.create.expiryDays_${d}` as const, {
        defaultValue: t('tokens.create.expiryDays', { days: d }),
      }),
    })),
    ...(maxLifetimeDays === null
      ? [{ value: 'never', label: t('tokens.create.expiryNever') }]
      : []),
  ];

  const submit = form.onSubmit(async (values) => {
    setSubmitError(null);
    const expires_in_days =
      values.expiry === 'never' ? null : Number(values.expiry);
    const payload: CreateTokenPayload = {
      name: values.name.trim(),
      description: values.description.trim() || null,
      scopes: values.scopes,
      expires_in_days,
    };
    try {
      const created = await createToken.mutateAsync(payload);
      onCreated(created);
      form.reset();
    } catch (err) {
      const r = err as {
        response?: { status?: number; data?: { detail?: unknown } };
      };
      const detail = r.response?.data?.detail;
      const code =
        typeof detail === 'object' && detail !== null && 'code' in detail
          ? String((detail as { code: unknown }).code)
          : null;
      if (code === 'scope_overreach') {
        setSubmitError(t('tokens.errors.scopeOverreach'));
      } else if (code === 'max_per_user_exceeded') {
        setSubmitError(t('tokens.errors.maxPerUser'));
      } else if (typeof detail === 'string') {
        setSubmitError(detail);
      } else {
        setSubmitError(t('tokens.errors.unknown'));
      }
    }
  });

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={t('tokens.create.title')}
      size="lg"
      centered
    >
      <form onSubmit={submit}>
        <Stack gap="sm">
          <TextInput
            required
            label={t('tokens.create.name')}
            description={t('tokens.create.nameHelp')}
            {...form.getInputProps('name')}
            data-testid="token-create-name"
          />
          <Textarea
            label={t('tokens.create.description')}
            description={t('tokens.create.descriptionHelp')}
            autosize
            minRows={2}
            maxRows={4}
            {...form.getInputProps('description')}
          />
          <MultiSelect
            required
            label={t('tokens.create.scopes')}
            description={t('tokens.create.scopesHelp')}
            placeholder={t('tokens.create.scopesPlaceholder')}
            data={availableScopes.map((p) => ({ value: p, label: p }))}
            searchable
            {...form.getInputProps('scopes')}
            data-testid="token-create-scopes"
          />
          <Select
            required
            label={t('tokens.create.expiry')}
            description={t('tokens.create.expiryHelp')}
            data={expiryOptions}
            allowDeselect={false}
            {...form.getInputProps('expiry')}
          />
          {submitError ? <Alert color="red">{submitError}</Alert> : null}
          <Group justify="flex-end" mt="xs">
            <Button variant="default" onClick={handleClose}>
              {t('common.cancel')}
            </Button>
            <Button
              type="submit"
              loading={createToken.isPending}
              data-testid="token-create-submit"
            >
              {t('tokens.create.submit')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
