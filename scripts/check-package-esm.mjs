#!/usr/bin/env node
// Load every `exports` entry of the published host SDK packages with
// Node's own ESM loader, against the built `dist/`.
//
// Vite and the in-workspace vitest runs transform the packages, so
// they tolerate things Node's loader rejects -- an extensionless
// relative import reached npm that way and broke every scaffolded
// host's `pnpm test` (issue #303). Hosts' vitest externalises
// `node_modules`, so plain Node is the loader that matters.
//
// Run after `pnpm build`:  node scripts/check-package-esm.mjs

import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packages = ['host-types', 'host-bundle-utils', 'test-utils'];

let failed = 0;
for (const name of packages) {
  const dir = join(root, 'packages', name);
  const manifest = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'));
  for (const [subpath, target] of Object.entries(manifest.exports ?? {})) {
    const file = typeof target === 'string' ? target : target.default;
    const label = `${manifest.name}${subpath === '.' ? '' : subpath.slice(1)}`;
    try {
      await import(pathToFileURL(join(dir, file)).href);
      console.log(`ok    ${label}`);
    } catch (err) {
      failed += 1;
      console.error(`FAIL  ${label}\n      ${err.message}`);
    }
  }
}

if (failed) {
  console.error(`\n${failed} entry point(s) failed to load under Node ESM.`);
  process.exit(1);
}
