// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import '@testing-library/jest-dom/vitest';

// jsdom doesn't ship ``window.matchMedia``; Mantine's MantineProvider
// reads it during color-scheme resolution and throws "matchMedia is
// not a function" on first render. The browser default would resolve
// every query to ``no-match``, which matches Mantine's "auto" preset
// behaviour on a system without an explicit dark-mode preference.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
