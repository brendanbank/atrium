// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { createTheme, type MantineColorScheme, type MantineThemeOverride } from '@mantine/core';

import type { BrandConfig, ThemePreset } from '@/hooks/useAppConfig';

import { classicPreset } from './presets/classic';
import { darkGlassPreset } from './presets/dark-glass';
import { defaultPreset } from './presets/default';

const PRESETS: Record<ThemePreset, MantineThemeOverride> = {
  default: defaultPreset,
  'dark-glass': darkGlassPreset,
  classic: classicPreset,
};

export const PRESET_OPTIONS: { value: ThemePreset; label: string }[] = [
  { value: 'default', label: 'Default (teal)' },
  { value: 'dark-glass', label: 'Dark glass' },
  { value: 'classic', label: 'Classic (blue serif)' },
];

// Curated set of override keys the admin UI exposes. Anything outside
// this list is dropped silently when building the theme — the JSON
// blob in app_settings is intentionally permissive (admins editing
// the raw row shouldn't be able to inject arbitrary CSS), but only
// these five tokens roundtrip through the form.
const ALLOWED_OVERRIDE_KEYS = [
  'primaryColor',
  'primaryShade',
  'defaultRadius',
  'fontFamily',
  'headingsFontFamily',
] as const;

type AllowedOverrideKey = (typeof ALLOWED_OVERRIDE_KEYS)[number];

function applyOverrides(
  base: MantineThemeOverride,
  overrides: Record<string, string>,
): MantineThemeOverride {
  const out: MantineThemeOverride = { ...base };
  for (const key of ALLOWED_OVERRIDE_KEYS) {
    const raw = overrides[key];
    if (raw === undefined || raw === '') continue;
    if (key === 'primaryShade') {
      const shade = Number(raw);
      if (!Number.isInteger(shade) || shade < 0 || shade > 9) continue;
      out.primaryShade = shade as MantineThemeOverride['primaryShade'];
      continue;
    }
    if (key === 'headingsFontFamily') {
      out.headings = { ...(out.headings ?? {}), fontFamily: raw };
      continue;
    }
    (out as Record<AllowedOverrideKey, unknown>)[key] = raw;
  }
  return out;
}

export function buildTheme(brand: BrandConfig | undefined) {
  const preset = brand?.preset ?? 'default';
  const base = PRESETS[preset] ?? defaultPreset;
  const merged = applyOverrides(base, brand?.overrides ?? {});
  return createTheme(merged);
}

export function colorSchemeForPreset(preset: ThemePreset): MantineColorScheme {
  // ``dark-glass`` is designed against the dark scheme; force it so
  // operators don't have to also flip the OS-level setting to make
  // the brand match. Other presets respect user/OS preference.
  return preset === 'dark-glass' ? 'dark' : 'auto';
}
