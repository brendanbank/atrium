// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Regression coverage for ``AutofillUsernameField``.
 *
 * The /2fa challenge page has only a one-time-code field. Password managers
 * (1Password on iOS) scope autofill to an account via the page's username
 * field; with none present they match the domain but not the account, so on
 * the OTP page they open the whole vault instead of jumping to the matching
 * login and filling the code inline. This field supplies that context.
 *
 * Pins the contract: an ``autocomplete="username"`` input carrying the email
 * when known, and nothing at all when the email is absent (a hard reload of
 * /2fa) so the page never ships an empty, unfillable decoy field.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';

import { AutofillUsernameField } from '@/components/AutofillUsernameField';

afterEach(cleanup);

describe('AutofillUsernameField', () => {
  it('renders an autocomplete="username" field carrying the email', () => {
    const { container } = render(
      <AutofillUsernameField email="info@brendanbank.com" />,
    );
    const input = container.querySelector('input');
    expect(input).not.toBeNull();
    expect(input?.getAttribute('autocomplete')).toBe('username');
    expect((input as HTMLInputElement).value).toBe('info@brendanbank.com');
    // Read-only and out of the tab order — it's a decoy for the password
    // manager, never something the user edits or tabs into.
    expect(input?.hasAttribute('readonly')).toBe(true);
    expect(input?.getAttribute('tabindex')).toBe('-1');
  });

  it('renders nothing when the email is unknown', () => {
    const { container } = render(<AutofillUsernameField />);
    expect(container.querySelector('input')).toBeNull();
  });
});
