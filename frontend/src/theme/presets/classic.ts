// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import type { MantineThemeOverride } from '@mantine/core';

const SERIF_DISPLAY_STACK =
  '"Source Serif 4", "Source Serif Pro", Georgia, "Times New Roman", serif';
const SANS_BODY_STACK =
  '"Source Sans 3", "Source Sans Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

export const classicPreset: MantineThemeOverride = {
  primaryColor: 'blue',
  primaryShade: 7,
  defaultRadius: 'sm',
  fontFamily: SANS_BODY_STACK,
  headings: { fontFamily: SERIF_DISPLAY_STACK, fontWeight: '600' },
};
