// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

// CLI entry point.
//
//   create-atrium-host <name> [--yes-defaults] [--no-git] [--out <dir>]
//
// Without --yes-defaults the user is prompted for the host package
// name, brand display name, primary colour, and atrium image
// version. `--yes-defaults` derives everything from the project name
// and skips prompts (used by CI smoke tests and anyone who just wants
// the baseline).

import { fileURLToPath } from 'node:url';
import { dirname, resolve, isAbsolute } from 'node:path';
import { stat } from 'node:fs/promises';

import kleur from 'kleur';
import prompts from 'prompts';

import {
  brandPascal,
  defaultBrandName,
  defaultHostPkg,
  validateBrandName,
  validateBrandPrimary,
  validateHostName,
  validateHostPkg,
} from './names.js';
import { ensureEmptyDir, pathExists, renderTemplate } from './render.js';
import { gitAvailable, initRepo } from './git.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const TEMPLATE_DIR = resolve(__dirname, '..', 'template');

// The atrium image + SDK packages version in lockstep. Bump this when
// cutting a new atrium release so freshly scaffolded hosts pin against
// the right line.
const DEFAULT_ATRIUM_VERSION = '0.21';

const HELP = `
${kleur.bold('create-atrium-host')} — scaffold a new atrium host extension

Usage:
  npx @brendanbank/create-atrium-host <name> [options]

Arguments:
  <name>              Project name (lowercase, dashes; e.g. casa-del-leone)

Options:
  --yes-defaults      Skip prompts; derive everything from <name>
  --no-git            Skip ${kleur.cyan('git init')} + initial commit
  --out <dir>         Output directory (default: ./<name>)
  --atrium <version>  Atrium image / SDK version pin (default: ${DEFAULT_ATRIUM_VERSION})
  -h, --help          Show this help

The scaffolder emits a working repo: ${kleur.bold('make dev-bootstrap')} brings up the
stack, ${kleur.bold('make seed-admin')} + ${kleur.bold('make seed-bundle')} finish wiring it, and
${kleur.bold('make test')} is green out of the box.
`;

function parseArgs(argv) {
  const args = { positional: [], flags: {}, options: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '-h' || a === '--help') {
      args.flags.help = true;
    } else if (a === '--yes-defaults') {
      args.flags.yesDefaults = true;
    } else if (a === '--no-git') {
      args.flags.noGit = true;
    } else if (a === '--out') {
      args.options.out = argv[++i];
    } else if (a.startsWith('--out=')) {
      args.options.out = a.slice('--out='.length);
    } else if (a === '--atrium') {
      args.options.atrium = argv[++i];
    } else if (a.startsWith('--atrium=')) {
      args.options.atrium = a.slice('--atrium='.length);
    } else if (a.startsWith('--')) {
      throw new Error(`unknown option: ${a}`);
    } else {
      args.positional.push(a);
    }
  }
  return args;
}

async function gatherAnswers({ hostNameArg, yesDefaults, atriumVersion }) {
  // Fixed answers regardless of mode — derived from CLI arg so tests
  // can pass them in deterministically.
  const fixed = {
    hostName: hostNameArg,
    atriumVersion,
  };

  if (yesDefaults) {
    const hostPkg = defaultHostPkg(hostNameArg);
    const brandName = defaultBrandName(hostNameArg);
    return {
      ...fixed,
      hostPkg,
      brandName,
      brandPrimary: 'blue',
    };
  }

  const responses = await prompts([
    {
      type: 'text',
      name: 'hostPkg',
      message: 'Python module name',
      initial: defaultHostPkg(hostNameArg),
      validate: validateHostPkg,
    },
    {
      type: 'text',
      name: 'brandName',
      message: 'Brand display name',
      initial: defaultBrandName(hostNameArg),
      validate: validateBrandName,
    },
    {
      type: 'select',
      name: 'brandPrimary',
      message: 'Primary colour (Mantine palette)',
      choices: [
        { title: 'blue', value: 'blue' },
        { title: 'teal', value: 'teal' },
        { title: 'indigo', value: 'indigo' },
        { title: 'violet', value: 'violet' },
        { title: 'grape', value: 'grape' },
        { title: 'pink', value: 'pink' },
        { title: 'red', value: 'red' },
        { title: 'orange', value: 'orange' },
        { title: 'green', value: 'green' },
        { title: 'gray', value: 'gray' },
      ],
      initial: 0,
    },
  ], {
    onCancel: () => {
      console.error(kleur.red('cancelled.'));
      process.exit(130);
    },
  });

  return { ...fixed, ...responses };
}

function buildVars({ hostName, hostPkg, brandName, brandPrimary, atriumVersion }) {
  return {
    HOST_NAME: hostName,
    HOST_PKG: hostPkg,
    BRAND_NAME: brandName,
    BRAND_PASCAL: brandPascal(brandName),
    BRAND_PRIMARY: brandPrimary,
    ATRIUM_VERSION: atriumVersion,
  };
}

function printNextSteps({ outDir, hostName }) {
  const cd = `cd ${outDir}`;
  console.log();
  console.log(kleur.green().bold('done.'));
  console.log();
  console.log(`Next steps:`);
  console.log(`  ${kleur.cyan(cd)}`);
  console.log(`  ${kleur.cyan('cp .env.example .env')}                  # fill in secrets`);
  console.log(`  ${kleur.cyan('make dev-bootstrap')}                    # build + start + migrate`);
  console.log(`  ${kleur.cyan(`make seed-admin EMAIL=you@example.com PASSWORD='good-password'`)}`);
  console.log(`  ${kleur.cyan('make seed-bundle')}                      # point atrium at /host/main.js`);
  console.log(`  ${kleur.cyan('open http://localhost:8000')}`);
  console.log();
  console.log(kleur.dim(`The ${kleur.bold(hostName)} card will appear on the home page after login.`));
  console.log();
}

export async function run(argv) {
  let parsed;
  try {
    parsed = parseArgs(argv);
  } catch (err) {
    console.error(kleur.red(err.message));
    console.error(HELP);
    process.exit(2);
  }

  if (parsed.flags.help || parsed.positional.length === 0) {
    console.log(HELP);
    process.exit(parsed.flags.help ? 0 : 2);
  }

  if (parsed.positional.length > 1) {
    console.error(kleur.red(`unexpected extra args: ${parsed.positional.slice(1).join(' ')}`));
    process.exit(2);
  }

  const hostName = parsed.positional[0];
  const nameOk = validateHostName(hostName);
  if (nameOk !== true) {
    console.error(kleur.red(`invalid project name: ${nameOk}`));
    process.exit(2);
  }

  const atriumVersion = parsed.options.atrium ?? DEFAULT_ATRIUM_VERSION;

  const outDirArg = parsed.options.out ?? hostName;
  const outDir = isAbsolute(outDirArg) ? outDirArg : resolve(process.cwd(), outDirArg);

  if (await pathExists(outDir)) {
    const info = await stat(outDir);
    if (!info.isDirectory()) {
      console.error(kleur.red(`destination exists and is not a directory: ${outDir}`));
      process.exit(1);
    }
    try {
      await ensureEmptyDir(outDir);
    } catch {
      console.error(kleur.red(`destination ${outDir} exists and is not empty.`));
      console.error(kleur.dim('pick a different --out, or delete the existing tree.'));
      process.exit(1);
    }
  }

  const answers = await gatherAnswers({
    hostNameArg: hostName,
    yesDefaults: parsed.flags.yesDefaults === true,
    atriumVersion,
  });

  // Re-validate the prompted answers in case a non-interactive caller
  // passed bad values via stdin (or the user accepted a bad default).
  for (const [key, validator] of [
    ['hostPkg', validateHostPkg],
    ['brandName', validateBrandName],
    ['brandPrimary', validateBrandPrimary],
  ]) {
    const v = validator(answers[key]);
    if (v !== true) {
      console.error(kleur.red(`invalid ${key}: ${v}`));
      process.exit(2);
    }
  }

  const vars = buildVars(answers);

  console.log();
  console.log(kleur.bold(`Scaffolding ${hostName} into ${outDir}`));
  console.log(kleur.dim(`  python module : ${vars.HOST_PKG}`));
  console.log(kleur.dim(`  brand name    : ${vars.BRAND_NAME}`));
  console.log(kleur.dim(`  primary       : ${vars.BRAND_PRIMARY}`));
  console.log(kleur.dim(`  atrium image  : ghcr.io/brendanbank/atrium:${vars.ATRIUM_VERSION}`));
  console.log();

  const written = await renderTemplate({
    templateDir: TEMPLATE_DIR,
    outDir,
    vars,
  });

  console.log(kleur.green(`✓ wrote ${written.length} files`));

  if (!parsed.flags.noGit) {
    if (await gitAvailable()) {
      try {
        await initRepo(outDir);
        console.log(kleur.green('✓ initialised git, made initial commit'));
      } catch (err) {
        console.warn(kleur.yellow(`! git init failed (${err.message.split('\n')[0]}); skipping`));
      }
    } else {
      console.warn(kleur.yellow('! git not on PATH; skipping repo init'));
    }
  }

  printNextSteps({ outDir, hostName });
}
