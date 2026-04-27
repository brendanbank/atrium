// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';

import de from './locales/de.json';
import en from './locales/en.json';
import fr from './locales/fr.json';
import nl from './locales/nl.json';

const defaultLng = import.meta.env.VITE_DEFAULT_LANGUAGE ?? 'en';

const SUPPORTED = ['en', 'nl', 'de', 'fr'] as const;

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: 'en',
    lng: defaultLng,
    supportedLngs: SUPPORTED as unknown as string[],
    resources: {
      en: { translation: en },
      nl: { translation: nl },
      de: { translation: de },
      fr: { translation: fr },
    },
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
    },
  });

interface I18nOverrides {
  enabled_locales?: string[];
  overrides?: Record<string, Record<string, string>>;
}

interface AppConfigShape {
  i18n?: I18nOverrides;
}

function unflattenDotted(flat: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [path, value] of Object.entries(flat)) {
    const parts = path.split('.');
    let cursor = out;
    for (let i = 0; i < parts.length - 1; i++) {
      const key = parts[i];
      const next = cursor[key];
      if (typeof next !== 'object' || next === null) {
        cursor[key] = {};
      }
      cursor = cursor[key] as Record<string, unknown>;
    }
    cursor[parts[parts.length - 1]] = value;
  }
  return out;
}

void (async () => {
  try {
    // Resolve the API base the same way ``lib/api.ts`` does. Bare
    // ``/app-config`` would hit the Vite dev server (port 5173) which
    // serves index.html for unknown paths — the JSON parse would
    // silently fail and overrides would never apply.
    const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
    const res = await fetch(`${apiBase}/app-config`, {
      credentials: 'include',
    });
    if (!res.ok) return;
    const cfg = (await res.json()) as AppConfigShape;
    const overrides = cfg.i18n?.overrides ?? {};
    for (const [locale, flatBundle] of Object.entries(overrides)) {
      if (!flatBundle || Object.keys(flatBundle).length === 0) continue;
      const nested = unflattenDotted(flatBundle);
      i18n.addResourceBundle(locale, 'translation', nested, true, true);
    }
  } catch {
    // Network or parse failures fall through to the bundled defaults —
    // an admin-broken /app-config response shouldn't take down the UI.
  }
})();

export default i18n;
