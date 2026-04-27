// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Money formatting helpers.
 *
 * We default to Dutch locale (nl-NL) so amounts render as
 * "€ 1.234,56" — comma decimal, dot thousands — matching both
 * Dutch and Italian conventions. All other locales should go
 * through this module so the app stays consistent.
 */

const LOCALE = 'nl-NL';

export const DECIMAL_SEPARATOR = ',';
export const THOUSAND_SEPARATOR = '.';

export interface FormatMoneyOptions {
  /** Decimal places. Default 2. Pass 0 for whole-currency totals. */
  fractionDigits?: number;
}

export function formatMoney(
  cents: number | null,
  currency: string = 'EUR',
  { fractionDigits = 2 }: FormatMoneyOptions = {},
): string {
  if (cents == null) return '—';
  return new Intl.NumberFormat(LOCALE, {
    style: 'currency',
    currency,
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(cents / 100);
}
