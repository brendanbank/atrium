// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest';

import { formatMoney } from './money';

// We assert on the digits + comma/dot pattern rather than exact string,
// because the browser's Intl output for nl-NL can render €/space with
// NBSPs that vary across ICU versions.

describe('formatMoney', () => {
  it('returns the em-dash for null', () => {
    expect(formatMoney(null)).toBe('—');
  });

  it('defaults to 2 decimals with comma separator (EU style)', () => {
    const s = formatMoney(34286); // €342,86
    expect(s).toMatch(/342,86/);
  });

  it('respects fractionDigits=0 for whole-euro totals', () => {
    const s = formatMoney(68572, 'EUR', { fractionDigits: 0 });
    // 685.72 → rounded for display → 686
    expect(s).toMatch(/\b686\b/);
    expect(s).not.toMatch(/,/);
  });

  it('uses dot as thousand separator', () => {
    const s = formatMoney(123456700); // €1.234.567,00
    expect(s).toMatch(/1\.234\.567,00/);
  });

  it('accepts non-EUR currencies', () => {
    const s = formatMoney(10000, 'USD');
    // nl-NL renders USD with a space or "US$"; just assert it's there
    expect(s).toMatch(/100,00/);
    expect(s.toUpperCase()).toContain('US');
  });
});
