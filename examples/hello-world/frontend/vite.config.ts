// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { hostBundleConfig } from '@brendanbank/atrium-host-bundle-utils/vite';

// One function call: lib-mode build emitting `dist/main.js`, CSS
// inlined via runtime <style> tags, defines for the externalised
// React + TanStack Query references. See `@brendanbank/atrium-host-bundle-utils`
// for the rationale on each default.
export default hostBundleConfig({ entry: 'src/main.tsx' });
