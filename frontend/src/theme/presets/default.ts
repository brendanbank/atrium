// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import type { MantineThemeOverride } from '@mantine/core';

const SYSTEM_FONT_STACK =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

export const defaultPreset: MantineThemeOverride = {
  primaryColor: 'teal',
  defaultRadius: 'md',
  fontFamily: SYSTEM_FONT_STACK,
  headings: { fontFamily: SYSTEM_FONT_STACK },
};
