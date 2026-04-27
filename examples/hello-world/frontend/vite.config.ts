// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { resolve } from 'node:path';
import { defineConfig } from 'vite';

// Library build that emits a single ES module loaded by atrium via
// dynamic import (`system.host_bundle_url` → `await import(url)`).
//
// **Strategy**: bundle everything (React, ReactDOM, Mantine, TanStack
// Query) inside the host bundle. The exported elements are atrium-React
// elements that own a single ``<div>`` wrapper; that div's ref callback
// uses *our* bundled ReactDOM to mount *our* React tree inside it.
// Two React trees, side by side in the DOM:
//   - atrium's React owns the page shell, the wrapper div, routing
//   - our React owns the subtree (Mantine widgets, hook state)
// This isolates the React boundary cleanly and avoids the
// "Invalid hook call" trap of mixing two React copies in one tree.
//
// Bundle is ~250 KB gzipped. Production hosts that need a smaller
// bundle can share atrium's React via import maps — a follow-up
// branch. The example uses the simpler self-contained pattern.
export default defineConfig({
  // Lib-mode builds don't auto-replace ``process.env.NODE_ENV`` the
  // way Vite's app-mode builds do, and several deps (React internals,
  // TanStack Query) reference it. Without these defines the bundle
  // throws ``ReferenceError: process is not defined`` the moment the
  // SPA dynamic-imports it.
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
    'process.env': '{}',
  },
  build: {
    target: 'es2022',
    lib: {
      entry: resolve(__dirname, 'src/main.tsx'),
      formats: ['es'],
      fileName: () => 'main.js',
    },
    emptyOutDir: true,
    sourcemap: true,
  },
});
