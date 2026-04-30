// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';

import {
  getLocaleOverlays,
  subscribeLocaleOverlay,
  type LocaleOverlay,
} from '@/host/registry';
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

// Expose the i18next instance on window so host bundles can resolve
// shared keys (e.g. ``__atrium_t__('common.save')`` from
// ``@brendanbank/atrium-host-bundle-utils``) against atrium's bundled
// resources + admin overrides + host overlays. The host bundle reads
// the active locale dynamically — a user's language switch reaches the
// next ``t()`` call without re-registering. Available since atrium
// 0.14.0; older images leave the global undefined and the helper falls
// back to returning the key.
declare global {
  interface Window {
    __atrium_i18n__?: typeof i18n;
  }
}
if (typeof window !== 'undefined') {
  window.__atrium_i18n__ = i18n;
}

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

function applyHostLocaleOverlay(overlay: LocaleOverlay): void {
  // Accept either a flat dotted bundle (``{"home.welcome": "Hi"}``)
  // or an already-nested tree. The flat form is detected by every
  // value being a primitive — if any value is itself an object, the
  // caller passed the nested shape directly.
  const looksFlat = Object.values(overlay.strings).every(
    (v) => v === null || typeof v !== 'object',
  );
  const bundle = looksFlat
    ? unflattenDotted(overlay.strings as Record<string, string>)
    : overlay.strings;
  // ``deep=true`` merges nested objects so a host overlaying a single
  // sub-key under ``home`` doesn't wipe atrium's other ``home.*``
  // strings. ``overwrite=true`` is the per-key last-write-wins.
  i18n.addResourceBundle(overlay.locale, 'translation', bundle, true, true);
}

// Drain any overlays the host bundle registered before this module
// finished initialising (defensive — host bundle loads after this
// module imports), then subscribe so future ``registerLocale`` calls
// land immediately.
for (const overlay of getLocaleOverlays()) {
  applyHostLocaleOverlay(overlay);
}
subscribeLocaleOverlay(applyHostLocaleOverlay);

void (async () => {
  try {
    // Resolve the API base the same way ``lib/api.ts`` does. Bare
    // ``/app-config`` would hit the Vite dev server (port 5173) which
    // serves index.html for unknown paths — the JSON parse would
    // silently fail and overrides would never apply.
    const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api';
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
  } finally {
    // Re-apply host overlays last so the precedence is deterministic
    // (shipped < admin override < host overlay) regardless of which
    // async path resolved first. Subsequent host registrations land
    // via the subscription above.
    for (const overlay of getLocaleOverlays()) {
      applyHostLocaleOverlay(overlay);
    }
  }
})();

export default i18n;
