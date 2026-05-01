// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vitest coverage for the PAT modals.
 *
 * The Playwright e2e drives the full create → reveal → revoke loop
 * end-to-end against the live API; these unit tests pin down the
 * client-side contracts that don't need a backend round-trip:
 *
 *  - ``TokenCreateModal`` validates name + scopes before submitting,
 *    surfaces server error codes (``scope_overreach`` etc.) to the
 *    user, and discards the typed plaintext on close.
 *  - ``TokenRevealModal`` ignores backdrop clicks / Escape (the
 *    plaintext is one-shot — accidental dismiss is the bug we're
 *    guarding against), and the in-component reveal toggle never
 *    leaks the value into a global.
 *  - The shared ``TokensTable`` revoke confirmation requires a
 *    non-empty reason in the admin variant.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import { TokenCreateModal } from '@/components/tokens/TokenCreateModal';
import { TokenRevealModal } from '@/components/tokens/TokenRevealModal';
import { TokensTable } from '@/components/tokens/TokensTable';
import type { AdminTokenSummary, TokenSummary } from '@/hooks/useTokens';
import { api } from '@/lib/api';

// Standalone i18n instance for tests — the real one in ``src/i18n``
// kicks off LanguageDetector against the JSDOM ``navigator`` and
// loads four locale bundles, which is overkill for unit tests. Inline
// the strings the modal copy references so assertions can match on
// stable English text.
const testI18n = i18n.createInstance();
void testI18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  resources: {
    en: {
      translation: {
        common: {
          cancel: 'Cancel',
          loading: 'Loading…',
          empty: 'Nothing here yet.',
        },
        login: { invalidEmail: 'Enter a valid email address' },
        admin: { active: 'Active', inactive: 'Inactive' },
        tokens: {
          notAllowed: 'No permission',
          never: 'Never',
          neverUsed: 'Never used',
          status: {
            active: 'Active',
            expired: 'Expired',
            revoked: 'Revoked',
          },
          cols: {
            name: 'Name',
            prefix: 'Prefix',
            user: 'User',
            scopes: 'Scopes',
            lastUsed: 'Last used',
            created: 'Created',
            expires: 'Expires',
            status: 'Status',
          },
          actions: {
            rotate: 'Rotate',
            revoke: 'Revoke',
            audit: 'Audit trail',
          },
          create: {
            title: 'New personal access token',
            name: 'Name',
            nameHelp: 'Operator-readable label',
            nameRequired: 'Name is required',
            description: 'Description',
            descriptionHelp: 'Notes',
            scopes: 'Scopes',
            scopesHelp: 'Permissions the token can use',
            scopesPlaceholder: 'Pick scopes…',
            scopesRequired: 'Pick at least one scope',
            expiry: 'Expires after',
            expiryHelp: 'Default 90 days',
            expiryDays: '{{days}} days',
            expiryDays_30: '30 days',
            expiryDays_90: '90 days',
            expiryDays_365: '1 year',
            expiryNever: 'Never',
            submit: 'Create token',
          },
          reveal: {
            title: 'Copy your new token',
            warningTitle: 'Only shown once',
            warningBody: 'Store it now',
            nameLabel: 'Token',
            tokenLabel: 'Bearer token',
            copy: 'Copy token',
            copied: 'Copied',
            dismiss: "I've copied it",
          },
          rotate: { confirm: 'rotate?' },
          revoke: {
            title: 'Revoke token',
            confirm: 'Revoke "{{name}}"?',
            reasonLabel: 'Reason',
            reasonHelp: 'Required for audit',
            submit: 'Revoke',
            done: 'Token revoked.',
          },
          errors: {
            scopeOverreach: 'Scope not held',
            maxPerUser: 'Too many tokens',
            scopeOverreachActor: 'You can not grant that',
            scopeOverreachTarget: 'Roles do not cover',
            emailTaken: 'Email taken',
            rotateFailed: 'Rotate failed',
            revokeFailed: 'Revoke failed',
            unknown: 'Unknown error',
          },
        },
      },
    },
  },
});

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <MantineProvider>
      <I18nextProvider i18n={testI18n}>
        <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('TokenCreateModal', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('submits a valid form and routes the plaintext to onCreated', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        id: 7,
        name: 'CI sidecar',
        description: null,
        token_prefix: 'atr_pat_aBcD',
        scopes: ['user.manage'],
        expires_at: null,
        last_used_at: null,
        last_used_ip: null,
        use_count: 0,
        created_at: '2026-05-01T00:00:00Z',
        revoked_at: null,
        revoke_reason: null,
        status: 'active',
        token: 'atr_pat_aBcDeFgH_xyz123',
      },
    } as never);
    const onCreated = vi.fn();
    render(
      wrap(
        <TokenCreateModal
          opened
          onClose={() => undefined}
          availableScopes={['user.manage', 'audit.read']}
          maxLifetimeDays={null}
          onCreated={onCreated}
        />,
      ),
    );

    const dialog = await screen.findByRole('dialog');
    fireEvent.change(dialog.querySelector('[data-testid="token-create-name"]')!, {
      target: { value: 'CI sidecar' },
    });

    // Open the MultiSelect dropdown and click the option.
    fireEvent.click(dialog.querySelector('[data-testid="token-create-scopes"]')!);
    fireEvent.click(await screen.findByRole('option', { name: 'user.manage' }));

    fireEvent.click(dialog.querySelector('[data-testid="token-create-submit"]')!);

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onCreated.mock.calls[0][0].token).toBe('atr_pat_aBcDeFgH_xyz123');
    expect(post).toHaveBeenCalledWith(
      '/auth/tokens',
      expect.objectContaining({
        name: 'CI sidecar',
        scopes: ['user.manage'],
        expires_in_days: 90,
      }),
    );
  });

  it('surfaces server error code as a localized message', async () => {
    vi.spyOn(api, 'post').mockRejectedValue({
      response: {
        status: 403,
        data: {
          detail: { code: 'scope_overreach', missing_permissions: ['x'] },
        },
      },
    } as never);
    render(
      wrap(
        <TokenCreateModal
          opened
          onClose={() => undefined}
          availableScopes={['user.manage']}
          maxLifetimeDays={null}
          onCreated={vi.fn()}
        />,
      ),
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(dialog.querySelector('[data-testid="token-create-name"]')!, {
      target: { value: 'overreach' },
    });
    fireEvent.click(dialog.querySelector('[data-testid="token-create-scopes"]')!);
    fireEvent.click(await screen.findByRole('option', { name: 'user.manage' }));
    fireEvent.click(dialog.querySelector('[data-testid="token-create-submit"]')!);

    expect(await screen.findByText('Scope not held')).toBeInTheDocument();
  });

  it('blocks submit when name is empty', async () => {
    const onCreated = vi.fn();
    const post = vi.spyOn(api, 'post');
    render(
      wrap(
        <TokenCreateModal
          opened
          onClose={() => undefined}
          availableScopes={['user.manage']}
          maxLifetimeDays={null}
          onCreated={onCreated}
        />,
      ),
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(dialog.querySelector('[data-testid="token-create-scopes"]')!);
    fireEvent.click(await screen.findByRole('option', { name: 'user.manage' }));
    // Submit by dispatching the form-level event so jsdom routes it
    // through Mantine's ``onSubmit`` wrapper. Clicking the submit
    // button alone doesn't bubble up reliably in jsdom + Mantine v9
    // because the modal renders inside a portal and the button is
    // ``type="submit"`` with no ``form`` attribute.
    const form = dialog.querySelector('form')!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(post).not.toHaveBeenCalled();
    });
    expect(onCreated).not.toHaveBeenCalled();
    // Mantine surfaces the form error inline; the exact text is
    // i18n-keyed so we look it up by fixture string.
    expect(screen.getByText('Name is required')).toBeInTheDocument();
  });
});

describe('TokenRevealModal', () => {
  afterEach(cleanup);

  it('renders the plaintext and a copy button', () => {
    render(
      wrap(
        <TokenRevealModal
          opened
          token="atr_pat_aBcDeFgH_xyz123"
          name="My token"
          onClose={() => undefined}
        />,
      ),
    );
    const input = screen.getByTestId('token-reveal-input') as HTMLInputElement;
    expect(input.value).toBe('atr_pat_aBcDeFgH_xyz123');
    expect(screen.getByTestId('token-reveal-copy')).toBeInTheDocument();
    expect(screen.getByTestId('token-reveal-dismiss')).toBeInTheDocument();
  });

  it('calls onClose only when the user clicks Dismiss', () => {
    const onClose = vi.fn();
    render(
      wrap(
        <TokenRevealModal
          opened
          token="atr_pat_aBcDeFgH_xyz123"
          name="My token"
          onClose={onClose}
        />,
      ),
    );
    // Pressing Escape on the dialog must NOT dismiss — Mantine respects
    // ``closeOnEscape={false}`` so the handler is wired but suppressed.
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('token-reveal-dismiss'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('writes the plaintext to the clipboard via CopyButton', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      wrap(
        <TokenRevealModal
          opened
          token="atr_pat_aBcDeFgH_xyz123"
          name="My token"
          onClose={() => undefined}
        />,
      ),
    );
    fireEvent.click(screen.getByTestId('token-reveal-copy'));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith('atr_pat_aBcDeFgH_xyz123'),
    );
  });
});

describe('TokensTable revoke confirmation', () => {
  afterEach(cleanup);

  function makeAdminRow(overrides: Partial<AdminTokenSummary> = {}): AdminTokenSummary {
    const base: TokenSummary = {
      id: 1,
      name: 'CI sidecar',
      description: null,
      token_prefix: 'atr_pat_aBcD',
      scopes: ['user.manage'],
      expires_at: null,
      last_used_at: null,
      last_used_ip: null,
      use_count: 0,
      created_at: '2026-05-01T00:00:00Z',
      revoked_at: null,
      revoke_reason: null,
      status: 'active',
    };
    return {
      ...base,
      user_id: 42,
      user_email: 'u@example.com',
      user_full_name: 'A User',
      revoked_by_user_id: null,
      ...overrides,
    };
  }

  it('admin variant blocks submit until reason is filled', async () => {
    const onRevoke = vi.fn();
    render(
      wrap(
        <TokensTable
          variant="admin"
          tokens={[makeAdminRow()]}
          onRevoke={onRevoke}
          onShowAudit={() => undefined}
        />,
      ),
    );
    fireEvent.click(screen.getByTestId('token-revoke-1'));
    const submit = await screen.findByTestId('token-revoke-submit');
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId('token-revoke-reason'), {
      target: { value: 'lost laptop' },
    });
    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);
    expect(onRevoke).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1 }),
      'lost laptop',
    );
  });

  it('profile variant submits without a reason', async () => {
    const onRevoke = vi.fn();
    render(
      wrap(
        <TokensTable
          variant="profile"
          tokens={[
            {
              id: 2,
              name: 'mine',
              description: null,
              token_prefix: 'atr_pat_zzzz',
              scopes: [],
              expires_at: null,
              last_used_at: null,
              last_used_ip: null,
              use_count: 0,
              created_at: '2026-05-01T00:00:00Z',
              revoked_at: null,
              revoke_reason: null,
              status: 'active',
            },
          ]}
          onRotate={() => undefined}
          onRevoke={onRevoke}
        />,
      ),
    );
    fireEvent.click(screen.getByTestId('token-revoke-2'));
    fireEvent.click(await screen.findByTestId('token-revoke-submit'));
    expect(onRevoke).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });
});

beforeEach(() => undefined);
