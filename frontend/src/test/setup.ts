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

// jsdom doesn't ship ``ResizeObserver``; Mantine's ``Textarea autosize``
// (used by every form with a multiline note field) registers a
// listener on the autosize-measurement element's ``ResizeObserver``
// during ``useLayoutEffect`` and throws ``Cannot read properties of
// undefined (reading 'addEventListener')`` when it isn't there.
// A no-op shim is enough; the test never actually inspects the
// resize-driven measurements.
if (typeof globalThis !== 'undefined' && !('ResizeObserver' in globalThis)) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}

// jsdom also doesn't ship ``document.fonts`` (the FontFaceSet API).
// Mantine's Textarea autosize registers ``loadingdone`` on it so the
// height re-measures after a webfont loads. Without this shim every
// render-with-Textarea throws "Cannot read properties of undefined
// (reading 'addEventListener')".
if (
  typeof document !== 'undefined' &&
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (document as any).fonts === undefined
) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (document as any).fonts = {
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  };
}
