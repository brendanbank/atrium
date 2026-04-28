// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, describe, expect, test } from 'vitest';

import { __atrium_t__ } from '../src/i18n';

interface MinimalI18n {
  language?: string;
  t: (
    key: string,
    options?: Record<string, unknown> & { defaultValue?: string },
  ) => string;
}

function installFakeI18n(
  bundles: Record<string, Record<string, string>>,
  language: string,
): MinimalI18n {
  const fake: MinimalI18n = {
    language,
    t(key, options) {
      const langs = [language, 'en'];
      for (const l of langs) {
        const hit = bundles[l]?.[key];
        if (typeof hit === 'string') {
          return interpolate(hit, options);
        }
      }
      const def = options?.defaultValue;
      return typeof def === 'string' ? def : key;
    },
  };
  (window as unknown as { __atrium_i18n__?: MinimalI18n }).__atrium_i18n__ =
    fake;
  return fake;
}

function interpolate(
  s: string,
  vars?: Record<string, unknown> & { defaultValue?: string },
): string {
  if (!vars) return s;
  return s.replace(/\{\{(\w+)\}\}/g, (_, key) => {
    if (key === 'defaultValue') return _;
    const v = vars[key];
    return v == null ? _ : String(v);
  });
}

afterEach(() => {
  delete (window as unknown as { __atrium_i18n__?: unknown }).__atrium_i18n__;
});

describe('__atrium_t__', () => {
  test('resolves a key against the active locale', () => {
    installFakeI18n(
      {
        en: { 'common.save': 'Save' },
        nl: { 'common.save': 'Opslaan' },
      },
      'nl',
    );
    expect(__atrium_t__('common.save')).toBe('Opslaan');
  });

  test('falls back to English when the active locale lacks the key', () => {
    installFakeI18n(
      {
        en: { 'common.confirmDelete': 'Delete this item?' },
        nl: {},
      },
      'nl',
    );
    expect(__atrium_t__('common.confirmDelete')).toBe('Delete this item?');
  });

  test('returns the literal key when neither locale has it', () => {
    installFakeI18n({ en: {}, nl: {} }, 'nl');
    expect(__atrium_t__('common.unknownKey')).toBe('common.unknownKey');
  });

  test('returns the literal key when atrium did not expose i18next', () => {
    // The pre-0.14 fallback path — host bundle running against an older
    // atrium image that never installed window.__atrium_i18n__.
    expect(__atrium_t__('common.save')).toBe('common.save');
  });

  test('interpolates vars into the resolved string', () => {
    installFakeI18n(
      {
        en: { 'common.welcomeNamed': 'Welcome, {{name}}' },
      },
      'en',
    );
    expect(__atrium_t__('common.welcomeNamed', { name: 'Alice' })).toBe(
      'Welcome, Alice',
    );
  });

  test('coerces numeric vars to strings via the provider', () => {
    installFakeI18n(
      {
        en: { 'common.itemsLeft': '{{count}} items left' },
      },
      'en',
    );
    expect(__atrium_t__('common.itemsLeft', { count: 3 })).toBe(
      '3 items left',
    );
  });
});
