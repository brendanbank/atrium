# @brendanbank/create-atrium-host

Scaffolder for a new [atrium](https://github.com/brendanbank/atrium)
host extension. One command, working repo: backend Python package +
frontend Vite host bundle + compose stack + CI, all wired against
atrium's published image and host SDK packages.

## Usage

```sh
npx @brendanbank/create-atrium-host casa-del-leone
```

Walks you through a short prompt sequence (Python module name, brand
display name, primary colour) and emits a git-initialised repo that's
ready to `make dev-bootstrap`.

For non-interactive use:

```sh
npx @brendanbank/create-atrium-host test-host --yes-defaults
```

### Options

| Flag                    | Effect                                                |
|-------------------------|-------------------------------------------------------|
| `--yes-defaults`        | Skip prompts; derive everything from the project name |
| `--no-git`              | Skip `git init` + initial commit                      |
| `--out <dir>`           | Output directory (default: `./<name>`)                |
| `--atrium <version>`    | Atrium image / SDK version pin (default: `0.21`)      |
| `-h`, `--help`          | Show help                                             |

## What it emits

```
casa-del-leone/
  Dockerfile           frontend-builder + FROM atrium runtime
  compose.yaml         api + worker + mysql
  .env.example         secrets template (copy to .env)
  Makefile             dev-bootstrap / migrate / seed-* / test
  backend/             Python host package (`casa_del_leone`)
    pyproject.toml
    alembic.ini
    alembic/           alembic_version_app chain
    src/casa_del_leone/
      bootstrap.py     init_app + init_worker
      models.py        HostBase + demo singleton
      router.py        /casa_del_leone/state + /casa_del_leone/bump
      scripts/seed_host_bundle.py
    tests/             pytest smoke tests
  frontend/            Vite library project (single main.js)
    package.json       @brendanbank/atrium-host-bundle-utils + -types + -test-utils
    vite.config.ts     hostBundleConfig({ entry: 'src/main.tsx' })
    src/
      main.tsx         ~10 lines of registry calls — no wrapper element code
      api.ts           plain fetch with credentials: include
      queryClient.ts
      CasaDelLeoneWidget.tsx       home widget + admin tab + page demo
      CasaDelLeonePage.tsx
      CasaDelLeoneAdminTab.tsx
      CasaDelLeoneProfileItem.tsx
    src/test/          vitest setup + worked example using @brendanbank/atrium-test-utils
  .github/
    workflows/ci.yml   typecheck + tests + smoke
    dependabot.yml     weekly grouped bumps
```

The seeded BrandConfig (in the first migration) materialises the
brand name + primary colour into `app_settings[brand]` so the SPA
renders with the host's identity from the first page load.

## What atrium gives you (don't reimplement)

The host repo's README enumerates this — auth, RBAC, audit, email
pipeline, scheduled jobs, notifications, admin shell, theme, i18n,
maintenance mode, account deletion. Atrium ships all of it; the
scaffolder leaves only the domain-specific surface for you to fill
in.

## Updating the template

The template lives under `template/` with `__HOST_NAME__`,
`__HOST_PKG__`, `__BRAND_NAME__`, `__BRAND_PASCAL__`, `__BRAND_PRIMARY__`,
`__ATRIUM_VERSION__` placeholders. Add a new placeholder by:

1. Use it in template files / paths.
2. Add a derivation + validator in `src/names.js`.
3. Add it to the prompt list (or default block) in `src/cli.js`.
4. Map it to the upper-snake key in `buildVars()`.

The CI smoke target is `pnpm smoke` — it scaffolds `__smoke_test_host__`
into `/tmp` non-interactively and reports failure if anything in the
template ends up unparseable.
