// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { describe, it } from 'node:test';
import { strict as assert } from 'node:assert';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { renderTemplate, substitute } from '../src/render.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const TEMPLATE_DIR = resolve(__dirname, '..', 'template');

describe('substitute', () => {
  it('replaces every placeholder occurrence', () => {
    const out = substitute('hello __NAME__ and __NAME__ again', { NAME: 'world' });
    assert.equal(out, 'hello world and world again');
  });

  it('leaves unreferenced placeholders alone', () => {
    const out = substitute('keep __OTHER__', { NAME: 'x' });
    assert.equal(out, 'keep __OTHER__');
  });
});

describe('renderTemplate', () => {
  it('renders the full template tree without leftover placeholders', async () => {
    const out = await mkdtemp(join(tmpdir(), 'atrium-scaffold-'));
    try {
      const written = await renderTemplate({
        templateDir: TEMPLATE_DIR,
        outDir: out,
        vars: {
          HOST_NAME: 'test-host',
          HOST_PKG: 'test_host',
          BRAND_NAME: 'Test Host',
          BRAND_PASCAL: 'TestHost',
          BRAND_PRIMARY: 'blue',
          ATRIUM_VERSION: '0.23',
        },
      });

      assert.ok(written.length > 10, `expected to write many files, got ${written.length}`);
      assert.ok(
        written.some((p) => p.includes('test_host')),
        'expected at least one path renamed to host_pkg',
      );

      const ren = (p) => readFile(join(out, p), 'utf8');

      // Backend python module + bootstrap + router + models all
      // substituted.
      const bootstrap = await ren('backend/src/test_host/bootstrap.py');
      assert.ok(bootstrap.includes('test_host.bootstrap'));
      assert.ok(!bootstrap.includes('__HOST_PKG__'));

      const router = await ren('backend/src/test_host/router.py');
      assert.ok(router.includes('TestHost'));
      assert.ok(router.includes('/test_host/state'));
      assert.ok(!router.includes('__BRAND_PASCAL__'));

      // Frontend main.tsx is the load-bearing one — the issue says
      // ~10 lines, no wrapper element code.
      const main = await ren('frontend/src/main.tsx');
      assert.ok(main.includes('TestHost'));
      assert.ok(!main.includes('__BRAND_PASCAL__'));
      assert.ok(!main.includes('__HOST_NAME__'));
      assert.ok(main.includes('makeWrapperElement'));

      // Composer + Dockerfile carry the atrium image pin.
      const compose = await ren('compose.yaml');
      assert.ok(compose.includes('atrium:0.23'));
      assert.ok(compose.includes('test-host'));
      assert.ok(!compose.includes('__ATRIUM_VERSION__'));

      // The brand seed migration carries the primary colour.
      const migration = await ren('backend/alembic/versions/0001_init.py');
      assert.ok(migration.includes('"blue"'));
      assert.ok(migration.includes('Test Host'));
    } finally {
      await rm(out, { recursive: true, force: true });
    }
  });

  it('renders without leftover __PLACEHOLDER__ tokens anywhere', async () => {
    const out = await mkdtemp(join(tmpdir(), 'atrium-scaffold-'));
    try {
      await renderTemplate({
        templateDir: TEMPLATE_DIR,
        outDir: out,
        vars: {
          HOST_NAME: 'casa-del-leone',
          HOST_PKG: 'casa_del_leone',
          BRAND_NAME: 'Casa del Leone',
          BRAND_PASCAL: 'CasaDelLeone',
          BRAND_PRIMARY: 'teal',
          ATRIUM_VERSION: '0.23',
        },
      });

      // Walk and assert no __X__ pattern that looks like one of our
      // placeholders survived. Acceptable false positives: Python
      // dunders like __init__, __name__, __main__, __file__,
      // __future__ — the regex skips lower-case dunders by requiring
      // at least one upper-case letter.
      const PLACEHOLDER_RE = /__([A-Z][A-Z0-9_]*)__/g;
      // Atrium-owned globals that legitimately appear in template
      // sources without being scaffolder placeholders. Add to this
      // list when atrium introduces a new __FOO__ surface.
      const KNOWN_DUNDERS = new Set(['ATRIUM_REGISTRY', 'ATRIUM_VERSION_LITERAL']);

      async function scan(dir) {
        const { readdir } = await import('node:fs/promises');
        const entries = await readdir(dir, { withFileTypes: true });
        for (const entry of entries) {
          const full = join(dir, entry.name);
          if (entry.isDirectory()) {
            await scan(full);
          } else if (entry.isFile() && !entry.name.endsWith('.png')) {
            const txt = await readFile(full, 'utf8');
            for (const match of txt.matchAll(PLACEHOLDER_RE)) {
              const tok = match[1];
              if (KNOWN_DUNDERS.has(tok)) continue;
              throw new Error(`leftover placeholder __${tok}__ in ${full}`);
            }
          }
        }
      }

      await scan(out);
    } finally {
      await rm(out, { recursive: true, force: true });
    }
  });
});
