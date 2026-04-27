// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { describe, it, expect } from 'vitest';

import i18n from '@/i18n';

describe('test harness', () => {
  it('runs', () => {
    expect(1 + 1).toBe(2);
  });
});

describe('i18n bundle', () => {
  it('resolves a few EN keys after init', () => {
    expect(i18n.t('login.submit', { lng: 'en' })).toBe('Log in');
    expect(i18n.t('common.save', { lng: 'en' })).toBe('Save');
    expect(i18n.t('translations.tab', { lng: 'en' })).toBe('Translations');
  });

  it('exposes all four supported locales', () => {
    const langs = i18n.options.supportedLngs as string[];
    expect(langs).toContain('en');
    expect(langs).toContain('nl');
    expect(langs).toContain('de');
    expect(langs).toContain('fr');
  });

  it('translates the same key in NL and DE', () => {
    expect(i18n.t('common.save', { lng: 'nl' })).toBe('Opslaan');
    expect(i18n.t('common.save', { lng: 'de' })).toBe('Speichern');
    expect(i18n.t('common.save', { lng: 'fr' })).toBe('Enregistrer');
  });
});
