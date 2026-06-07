// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Regression coverage for ``OtpInput``.
 *
 * The bug this guards against: 2FA code entry used Mantine's segmented
 * ``<PinInput>`` (one ``<input maxlength="1">`` per digit). Desktop
 * password-manager *extensions* fill those per-field, but mobile *native*
 * autofill (iOS Password AutoFill — which 1Password drives on iOS — and
 * Android Autofill) inserts the whole code into the single focused field,
 * where ``maxlength=1`` truncates it to one digit and the code never lands.
 *
 * The fix is a single ``<input autocomplete="one-time-code"
 * inputmode="numeric">``, the autofill target 1Password and Apple document.
 * These tests pin that contract: exactly one input, the right autofill
 * attributes, and PinInput-equivalent behaviour (digits only, clamped to
 * length) so a native autofill of the full code is accepted intact.
 */
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';

import { OtpInput } from '@/components/OtpInput';

afterEach(cleanup);

function Harness({ length }: { length?: number }) {
  const [code, setCode] = useState('');
  return (
    <MantineProvider>
      <OtpInput
        value={code}
        onChange={setCode}
        length={length}
        aria-label="One-time code"
      />
      <output data-testid="value">{code}</output>
    </MantineProvider>
  );
}

describe('OtpInput', () => {
  it('renders a single autofill-friendly input, not a segmented field', () => {
    render(<Harness />);
    const input = screen.getByLabelText('One-time code') as HTMLInputElement;
    // A segmented PinInput would render six inputs; a native autofill of
    // the whole code only lands when there is exactly one.
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
    expect(input.getAttribute('autocomplete')).toBe('one-time-code');
    expect(input.getAttribute('inputmode')).toBe('numeric');
  });

  it('accepts a full 6-digit code typed/pasted/autofilled in one shot', () => {
    render(<Harness />);
    const input = screen.getByLabelText('One-time code') as HTMLInputElement;
    // Native autofill sets the whole string at once — the maxlength=1
    // truncation that broke PinInput must not happen here.
    fireEvent.change(input, { target: { value: '123456' } });
    expect(screen.getByTestId('value')).toHaveTextContent('123456');
  });

  it('strips non-digits and clamps to length', () => {
    render(<Harness />);
    const input = screen.getByLabelText('One-time code') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '12-34 56789' } });
    expect(screen.getByTestId('value')).toHaveTextContent('123456');
  });

  it('honours a custom length', () => {
    render(<Harness length={4} />);
    const input = screen.getByLabelText('One-time code') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '987654' } });
    expect(screen.getByTestId('value')).toHaveTextContent('9876');
  });
});
