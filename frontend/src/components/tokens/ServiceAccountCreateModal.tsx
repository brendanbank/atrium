// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Admin-only "create service account" form. Posts ``POST
 * /admin/service_accounts`` and hands the embedded plaintext token
 * back to the parent for the reveal modal.
 *
 * Spec §16 / migration 0009: service accounts are users with
 * ``is_service_account=True``. The form takes a name + email +
 * description + optional role assignments + the initial PAT scopes
 * + optional expiry. Scopes shown here are the operator's own
 * permissions (the server defends in depth: they can only grant the
 * SA scopes they themselves hold).
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
  useCreateServiceAccount,
  type CreateServiceAccountPayload,
  type ServiceAccountCreated,
} from '@/hooks/useTokens';

interface ServiceAccountCreateModalProps {
  opened: boolean;
  onClose: () => void;
  /** Permission slugs the operator currently holds — also the upper
   *  bound for what they can grant the SA's first PAT. */
  availableScopes: string[];
  /** All non-system role codes the operator can assign. */
  availableRoles: string[];
  maxLifetimeDays: number | null;
  onCreated: (created: ServiceAccountCreated) => void;
}

const DEFAULT_EXPIRIES = [30, 90, 365] as const;

export function ServiceAccountCreateModal({
  opened,
  onClose,
  availableScopes,
  availableRoles,
  maxLifetimeDays,
  onCreated,
}: ServiceAccountCreateModalProps) {
  const { t } = useTranslation();
  const createSA = useCreateServiceAccount();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm<{
    name: string;
    email: string;
    description: string;
    role_codes: string[];
    initial_scopes: string[];
    expiry: string;
  }>({
    initialValues: {
      name: '',
      email: '',
      description: '',
      role_codes: [],
      initial_scopes: [],
      expiry: '90',
    },
    validate: {
      name: (v) =>
        v.trim().length === 0 ? t('tokens.create.nameRequired') : null,
      email: (v) =>
        /^\S+@\S+\.\S+$/.test(v) ? null : t('login.invalidEmail'),
      initial_scopes: (v) =>
        v.length === 0 ? t('tokens.create.scopesRequired') : null,
    },
  });

  const expiryOptions = [
    ...DEFAULT_EXPIRIES.filter(
      (d) => maxLifetimeDays === null || d <= maxLifetimeDays,
    ).map((d) => ({
      value: String(d),
      label: t('tokens.create.expiryDays', { days: d }),
    })),
    ...(maxLifetimeDays === null
      ? [{ value: 'never', label: t('tokens.create.expiryNever') }]
      : []),
  ];

  const handleClose = () => {
    form.reset();
    setSubmitError(null);
    onClose();
  };

  const submit = form.onSubmit(async (values) => {
    setSubmitError(null);
    const expires_in_days =
      values.expiry === 'never' ? null : Number(values.expiry);
    const payload: CreateServiceAccountPayload = {
      name: values.name.trim(),
      email: values.email.trim(),
      description: values.description.trim() || null,
      role_codes: values.role_codes,
      initial_scopes: values.initial_scopes,
      expires_in_days,
    };
    try {
      const created = await createSA.mutateAsync(payload);
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
      if (r.response?.status === 409) {
        setSubmitError(t('tokens.errors.emailTaken'));
      } else if (code === 'scope_overreach_actor') {
        setSubmitError(t('tokens.errors.scopeOverreachActor'));
      } else if (code === 'scope_overreach_target') {
        setSubmitError(t('tokens.errors.scopeOverreachTarget'));
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
      title={t('tokens.serviceAccount.title')}
      size="lg"
      centered
    >
      <form onSubmit={submit}>
        <Stack gap="sm">
          <TextInput
            required
            label={t('tokens.serviceAccount.name')}
            description={t('tokens.serviceAccount.nameHelp')}
            {...form.getInputProps('name')}
            data-testid="sa-name"
          />
          <TextInput
            required
            type="email"
            label={t('tokens.serviceAccount.email')}
            description={t('tokens.serviceAccount.emailHelp')}
            {...form.getInputProps('email')}
            data-testid="sa-email"
          />
          <Textarea
            label={t('tokens.create.description')}
            autosize
            minRows={2}
            maxRows={4}
            {...form.getInputProps('description')}
          />
          <MultiSelect
            label={t('tokens.serviceAccount.roles')}
            description={t('tokens.serviceAccount.rolesHelp')}
            placeholder={t('tokens.serviceAccount.rolesPlaceholder')}
            data={availableRoles.map((r) => ({ value: r, label: r }))}
            searchable
            {...form.getInputProps('role_codes')}
          />
          <MultiSelect
            required
            label={t('tokens.create.scopes')}
            description={t('tokens.serviceAccount.scopesHelp')}
            placeholder={t('tokens.create.scopesPlaceholder')}
            data={availableScopes.map((p) => ({ value: p, label: p }))}
            searchable
            {...form.getInputProps('initial_scopes')}
          />
          <Select
            required
            label={t('tokens.create.expiry')}
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
              loading={createSA.isPending}
              data-testid="sa-submit"
            >
              {t('tokens.serviceAccount.submit')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
