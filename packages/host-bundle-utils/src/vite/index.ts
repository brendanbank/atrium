// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Vite preset for atrium host bundles.
 *
 * Imported only by `vite.config.ts`, never by runtime code, so Vite
 * stays out of the host's production bundle. Vite + the css-injection
 * plugin are declared as optional peer deps; install them only when
 * building (typical: as devDependencies in the host's
 * `frontend/package.json`).
 *
 * The preset returns a complete Vite config that:
 *
 *  - Builds in library mode (`build.lib`) emitting a single ES module
 *    at `dist/main.js`. Atrium's loader does
 *    `import(system.host_bundle_url)` with that URL — no IIFE / UMD
 *    needed.
 *  - Inlines every imported `.css` via a runtime `<style>` tag
 *    (`vite-plugin-css-injected-by-js`). Without this Vite extracts
 *    CSS to a sibling `main.css` that atrium's dynamic-import never
 *    fetches, and Mantine / FullCalendar / any rich-text editor ships
 *    silently unstyled.
 *  - Defines `process.env.NODE_ENV` so the externalised React +
 *    TanStack Query references resolve in lib-mode builds (Vite's
 *    app-mode auto-replaces this; lib-mode does not).
 *
 *  Hosts can override anything by passing `extraConfig` (merged into
 *  the returned object) — typical use: a host needing a SVG plugin or
 *  a dev-only proxy. The defaults match the canonical
 *  self-contained-bundle pattern documented in
 *  `docs/published-images.md`.
 */
import { resolve } from 'node:path';

// `vite` and `vite-plugin-css-injected-by-js` are optional peer deps;
// import via `await import` so a host that imports the runtime entry
// at production time isn't forced to install them. Tooling-only entry
// uses dynamic imports lazily inside the factory.

export interface HostBundleConfigOptions {
  /** Path to the host bundle's entry. Resolved against the directory
   *  containing the `vite.config.ts` that calls this factory. */
  entry: string;
  /** Output filename for the built bundle. Default `'main.js'` —
   *  matches atrium's documented `system.host_bundle_url` of
   *  `/host/main.js`. */
  fileName?: string;
  /** Output directory inside the host's frontend project. Default
   *  `'dist'` — matches Vite's default and the `COPY --from=frontend-builder
   *  /app/dist /opt/atrium/static/host` Dockerfile pattern. */
  outDir?: string;
  /** Include sourcemaps in the build. Default `true` — they are tiny
   *  next to the bundle and make production debugging tractable. */
  sourcemap?: boolean;
  /** Override the JS target. Default `'es2022'`. */
  target?: string;
  /** Extra Vite config to merge on top of the defaults. Plugins are
   *  appended; everything else uses Vite's standard merge semantics. */
  extraConfig?: Record<string, unknown>;
}

/** Build a Vite config for an atrium host bundle.
 *
 *  Usage in the host's `vite.config.ts`:
 *
 *  ```ts
 *  import { hostBundleConfig } from '@brendanbank/atrium-host-bundle-utils/vite';
 *
 *  export default hostBundleConfig({ entry: 'src/main.tsx' });
 *  ```
 *
 *  The factory is async because it lazy-imports `vite` and the css
 *  injection plugin so they can stay optional peer deps.
 */
export async function hostBundleConfig(
  options: HostBundleConfigOptions,
): Promise<Record<string, unknown>> {
  const {
    entry,
    fileName = 'main.js',
    outDir = 'dist',
    sourcemap = true,
    target = 'es2022',
    extraConfig = {},
  } = options;

  const [vite, cssInjectedByJs] = await Promise.all([
    import('vite'),
    import('vite-plugin-css-injected-by-js'),
  ]);

  const mergeConfig = (vite as { mergeConfig: (a: unknown, b: unknown) => unknown }).mergeConfig;
  const cssPluginFactory =
    ((cssInjectedByJs as unknown as { default?: () => unknown }).default ??
      (cssInjectedByJs as unknown as () => unknown)) as () => unknown;

  // Build the config as a plain object — `defineConfig` is only a
  // typing helper, and its strict `Plugin` typing fights the
  // dynamically-imported CSS plugin. The merged config is what Vite
  // actually consumes at build time.
  const base: Record<string, unknown> = {
    // Lib-mode builds don't auto-replace `process.env.NODE_ENV` the
    // way Vite's app-mode builds do, and several deps (React internals,
    // TanStack Query) reference it. Without these defines the bundle
    // throws `ReferenceError: process is not defined` the moment the
    // SPA dynamic-imports it.
    define: {
      'process.env.NODE_ENV': JSON.stringify('production'),
      'process.env': '{}',
    },
    plugins: [cssPluginFactory()],
    build: {
      target,
      lib: {
        entry: resolve(process.cwd(), entry),
        formats: ['es'],
        fileName: () => fileName,
      },
      outDir,
      emptyOutDir: true,
      sourcemap,
    },
  };

  return mergeConfig(base, extraConfig) as Record<string, unknown>;
}
