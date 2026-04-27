// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import type { MantineThemeOverride } from '@mantine/core';

const DISPLAY_FONT_STACK =
  '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

// Tuned for ``defaultColorScheme="dark"`` — the wrapper at
// MantineProvider level flips the scheme when this preset is active.
// Larger radius + slightly lighter primary plays better against the
// dark backdrop than the default teal.
export const darkGlassPreset: MantineThemeOverride = {
  primaryColor: 'cyan',
  primaryShade: { light: 6, dark: 4 },
  defaultRadius: 'lg',
  fontFamily: DISPLAY_FONT_STACK,
  headings: { fontFamily: DISPLAY_FONT_STACK, fontWeight: '600' },
};
