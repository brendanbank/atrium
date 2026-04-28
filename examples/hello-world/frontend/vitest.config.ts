// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { defineConfig } from 'vitest/config';

// Vite's built-in esbuild loader handles tsx via the project's
// tsconfig (`jsx: react-jsx`). No `@vitejs/plugin-react` needed for
// unit tests — the package isn't listed as a peer dep so we'd be
// adding one for tests alone, which the host-bundle pattern keeps
// out by design.
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
