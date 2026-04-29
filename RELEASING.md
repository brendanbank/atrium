# Cutting an atrium release

The procedure for taking a green branch through to a published GHCR
image and a hand-written GitHub release. Atrium versions follow
semver; the registry tag fan-out (`X.Y.Z`, `X.Y`, `X`, `latest`) is
produced by `.github/workflows/publish-images.yml` on `v*` tag push,
not by hand.

## 0. Prerequisites

- GPG signing configured for commits *and* tags (the global default in
  this setup, see `~/.claude/CLAUDE.md`). The publish key is the RSA
  4096 hardware-token subkey ending `F60F2EAA7F5ACC52`.
- `gh` CLI authenticated against the `brendanbank/atrium` repo.
- `.env` present at the repo root (`make smoke` needs it). If missing:
  `cp .env.example .env`.
- A clean working tree on the feature branch.

## 1. Pre-flight tests

In order, all four must be green before opening the PR:

```bash
make test-backend            # ~1 min, testcontainers-mysql
make test-frontend           # vitest unit tests, ~10 s
( cd frontend && pnpm typecheck )
make lint                    # ruff + eslint; 1 pre-existing warning is OK
make smoke                   # Playwright against the e2e stack, ~30 s
```

Run `make smoke-hello` too if the change touches any of:

- `app/services/notifications.py` or the SSE stream
- the `frontend/src/host/` registry surface
- `examples/hello-world/`
- the published-images contract documented in `docs/published-images.md`

`make smoke-hello` has a known flaky test — `toggle on starts the
tick, toggle off stops it` — that fails with `socket hang up` when
the api container restarts mid-poll. If only that test fails, retry
just it before chasing root causes:

```bash
( cd examples/hello-world/frontend && \
  E2E_BASE_URL=http://localhost:8000 \
  E2E_ADMIN_EMAIL=admin@example.com \
  E2E_ADMIN_PASSWORD=smoke-pw-12345 \
  E2E_ADMIN_TOTP_SECRET=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP \
  E2E_COMPOSE_FILES='-f compose.yaml' E2E_COMPOSE_CWD='..' \
  CI=1 pnpm exec playwright test --grep 'toggle on starts' )
```

Tear the smoke stacks down between runs — they share named volumes:

```bash
make smoke-down              # before make smoke-hello
make smoke-hello-down        # after make smoke-hello
```

## 1.5. Bump the version + sync docs

The version that ships in the image comes from
`backend/pyproject.toml` — `app.services.app_config._atrium_version()`
reads it via `importlib.metadata.version("atrium-backend")` and exposes
it on `GET /app-config`, which the SPA mirrors onto
`window.__ATRIUM_VERSION__` for host-bundle feature detection. If you
don't bump it here, every host running the new image will report the
old version.

The frontend SDK packages (`packages/host-types`,
`packages/host-bundle-utils`, `packages/test-utils`) version in
**lockstep with the image** — a host pinning `^0.14` of either
package implies "compatible with atrium 0.14.x runtime image". Bump
all of them together along with `packages/create-atrium-host` (whose
default `--atrium` pin and emitted templates carry the same number).
The example under `examples/hello-world/frontend` consumes the
packages via `workspace:*` so it picks up the new version
automatically; no edit needed there.

The scaffolder (`packages/create-atrium-host/src/cli.js`) hard-codes
the default `--atrium` version in `DEFAULT_ATRIUM_VERSION`. Bump that
constant to the **major.minor** of the release you're cutting (e.g.
`0.14`) — the emitted host's package.json and Dockerfile both pin
through it, so a stale value would emit hosts pointing at the
previous line.

Land the bumps on the feature branch *before* tagging so master and
the git tag agree:

```bash
# backend/pyproject.toml — set ``version = "X.Y.Z"`` to match the tag
# you're about to push. Refresh the lockfile so uv.lock stays in sync:
( cd backend && uv lock --quiet )

# packages/host-types/package.json + packages/host-bundle-utils/package.json
# — set ``"version": "X.Y.Z"`` (same number as the backend bump).
# Refresh the workspace lockfile so it captures the new versions:
pnpm install --lockfile-only
```

While you're at it, sweep the documentation and the AI bootstrap
skill for stale version references — both are reader-facing and
quickly fall behind:

- `docs/compat-matrix.md` — **add a row** for the release you're
  about to cut. One row per published `vX.Y.Z`, with the alembic
  head, any new registry hooks, deprecations, and env / config
  changes. Cells stay terse; the release notes carry the prose. Use
  an em-dash for axes that didn't move in this release. The link
  in the *Atrium* column points at the release you're about to
  publish (step 9 below).
- `docs/published-images.md` — anywhere it cites a concrete atrium
  version ("since 0.X" notes, example pulls).
- `docs/new-project/README.md` and `docs/new-project/SKILL.md` —
  any pinned `ghcr.io/.../atrium:X.Y.Z` references in the bootstrap
  walkthroughs. The SKILL.md is the AI-driveable variant; missing
  it leaves agents emitting stale tags.
- `examples/hello-world/` — same sweep for any pinned base-image
  reference.
- `packages/host-types/README.md` and
  `packages/host-bundle-utils/README.md` — `^0.14` style pin
  examples should match the image's `X.Y` once you cross a minor.
  The version sweep is otherwise driven by the `package.json`
  bumps above; the README values are illustrative.
- `packages/create-atrium-host/src/cli.js` —
  `DEFAULT_ATRIUM_VERSION` (line ~30). The emitted host's compose
  + Dockerfile + frontend package.json all pin through it.
- `packages/create-atrium-host/README.md` — the `--atrium` default
  call-out in the options table.

If a doc references an atrium version, it needs updating with each
release. If it doesn't, it stays untouched.

## 2. Branch + commit hygiene

- Branch names: concrete, descriptive, **under 30 characters**, no
  `feature/` or other prefix. Recent examples:
  `sse-typed-events`, `docs-published-images`.
- Commit messages: imperative subject, no Co-Authored-By trailer,
  no "Generated with Claude Code" attribution. Wrap the body at ~72
  cols. Reference issues with `Closes #NN` so the squash-merge auto-
  closes them.
- **Bundling two independent fixes in one release: keep them as two
  commits on the branch.** Squash-merge collapses both into one
  commit on master, but the diff stays reviewable as two logical
  units in the PR view.

## 3. Push the branch — no PR yet

Pushing a feature branch is safe: `.github/workflows/ci.yml` is
gated on `pull_request` events only, no `push:` trigger on feature
branches. So:

```bash
git push -u origin <branch>
```

…fires no CI. Use this window to link the branch from the issue(s)
it implements:

```bash
gh issue comment <N> --body "WIP on branch [\`<branch>\`](https://github.com/brendanbank/atrium/tree/<branch>)."
```

That gives anyone tracking the issue a real link to the work in
progress without burning CI minutes.

## 4. Open the PR

```bash
gh pr create --base master --head <branch> \
  --title "<short, plain-English summary>" \
  --body "$(cat <<'EOF'
## Summary
<1-3 bullets — what changed, why>

## Test plan
- [x] make test-backend — N passed
- [x] make test-frontend — N passed
- [x] pnpm typecheck — clean
- [x] make lint — clean
- [x] make smoke — N/N passed
- [x] make smoke-hello — N/N passed (or note any retried flake)
EOF
)"
```

PR title is what `--squash` will use as the merged-commit subject —
keep it under ~70 chars.

## 5. Watch CI

Three workflows fire on PR: `CI`, `CodeQL`, `Security`. Find the run
IDs and watch them with `gh run watch --exit-status` — **never poll
with `gh run list`**, and don't drop `--exit-status` (bare `watch`
exits 0 even when the run failed):

```bash
gh run list --branch <branch> --limit 5
gh run watch <ci-run-id> --exit-status
```

Watching `CI` alone is usually enough; `CodeQL` and `Security` finish
faster and have rarely been the long pole. Confirm overall conclusion
afterwards:

```bash
gh run view <ci-run-id> --json conclusion,status -q '{conclusion,status}'
```

**Doc-only PRs skip CI.** All three PR workflows carry a
`paths-ignore` filter for `**.md`, `docs/**`, and `LICENCE.md`, so a
PR whose every changed file matches one of those patterns triggers
zero workflow runs. `gh run list --branch <branch>` will return
nothing — that's expected, not a "CI hung" signal. Mixed PRs (any
non-docs file alongside docs) still run the full suite; the filter
only fires when *every* changed path is in the ignore list. The
weekly Security cron and the on-demand `workflow_dispatch` for
CodeQL still cover full scans regardless.

## 6. Merge

Squash-merge — the established repo convention for the last ~10 PRs:

```bash
gh pr merge <N> --squash
```

Confirm:

```bash
gh pr view <N> --json state,mergedAt,mergeCommit \
  -q '{state, mergedAt, mergeCommit: .mergeCommit.oid}'
```

Note the merge SHA — the next step tags it directly.

## 7. Tag

**Conductor gotcha.** If you're working in a Conductor workspace, the
main `master` branch may be checked out by another worktree, in which
case `git checkout master` fails with `'master' is already used by
worktree at <path>`. Don't fight it — tag `origin/master` directly
by SHA. `git fetch origin` first to refresh the ref:

```bash
git fetch origin
git tag -s v<X.Y.Z> <merge-sha> -m "v<X.Y.Z> — <terse summary>

<one-bullet-per-issue body>"
git tag -v v<X.Y.Z>           # confirm "Good signature"
git push origin v<X.Y.Z>      # triggers publish-images.yml + publish-npm.yml
```

Use **signed annotated tags** (`-s`), not lightweight. Older tags in
the repo are mixed but signed-annotated is the established direction
and aligns with the global commit-signing default.

## 8. Watch publish-images + publish-npm

The tag push fires two workflows in parallel:

- `.github/workflows/publish-images.yml` — builds `linux/amd64` +
  `linux/arm64` and pushes to `ghcr.io/brendanbank/atrium` with the
  full semver fan-out (`0.11.3`, `0.11`, `0`, `latest`). Typical run
  time: ~3-5 minutes.
- `.github/workflows/publish-npm.yml` — builds the host SDK
  packages and publishes `@brendanbank/atrium-host-types`,
  `@brendanbank/atrium-host-bundle-utils`,
  `@brendanbank/atrium-test-utils`, and
  `@brendanbank/create-atrium-host` (each at `<X.Y.Z>`) to npmjs.org.
  Typical run time: ~1 minute. Authentication is via npm **Trusted
  Publishing** (OIDC) — the trust relationship is configured per-
  package on npmjs.com and matched against the workflow's signed
  GitHub OIDC token, so no `NPM_TOKEN` secret is stored in this repo.
  Each tarball carries a signed provenance attestation tying it to
  the exact commit + workflow run.

```bash
gh run list --workflow=publish-images.yml --limit 3
gh run list --workflow=publish-npm.yml --limit 3
gh run watch <publish-run-id> --exit-status
```

A non-zero exit on either means the corresponding artifact isn't
published — don't create the GitHub release until both are green,
otherwise users following the release notes will pull a tag (or a
package version) that doesn't exist. The npm publish is idempotent
on identical version+content; if the workflow is dispatched against
an already-published version, pnpm reports "version already exists"
and exits non-zero — re-tag with a bumped version rather than
forcing.

## 9. Hand-write the release notes

**Always hand-write atrium release notes.** Don't use
`--generate-notes` — the release email goes to non-engineers and
auto-generated bullet lists read like changelog noise. The user
reads them top-to-bottom on a phone.

Structure (match the v0.11.2 / v0.11.3 reference):

- **Title:** `v<X.Y.Z> — <plain-English headline>`. Headline focuses on
  what changed for *users*, not what changed in the code.
- **## Highlights.** Opening paragraph: what shipped, what's the
  motivation, what's *not* in scope. Mention if there are no
  migrations / no breaking changes / no env additions — the absence
  of upgrade pain is itself the headline.
- **One `##` section per closed issue or PR.** Lead with the user-
  visible behaviour, then the technical detail. Code blocks for any
  new API surface. Inline `(closes #NN)` or `(PR #NN)` at the end of
  the section so future readers can find the diff.
- **## Documentation.** What changed in `docs/` — even a one-liner.
  Hosts read this to know whether to re-skim the contract docs.
- **## Image details.** The registry-tag table (`X.Y.Z`, `X.Y`, `X`,
  `latest`). Keep it identical to the previous release; readers learn
  to skim it.
- **## Upgrading from v\<previous\>.** Compose snippet showing both
  the auto-uptake and fully-pinned forms. Call out migrations / env
  changes / breaking changes here, even if they're "none".

Then create the release:

```bash
gh release create v<X.Y.Z> \
  --title "v<X.Y.Z> — <headline>" \
  --notes "$(cat <<'EOF'
## Highlights

...
EOF
)"
```

Pre-releases use `--prerelease`; mainline releases don't need any
extra flag (the tag becomes "Latest" automatically).

## 10. Verify

```bash
gh release view v<X.Y.Z>      # confirm body, isLatest, isPrerelease
gh issue view <N>             # each "Closes #N" issue should be CLOSED
```

If you wrote `Closes #N` in the squashed commit body, GitHub closes
the issue when the commit lands on master — no manual close needed.

## Reference: prior releases as templates

- `gh release view v0.11.3` — typed SSE events + HomePage intro fix
- `gh release view v0.11.2` — `registerNotificationKind` host slot
- `gh release view v0.11.1` — resilient host bundles + width opt-out
- `gh release view v0.10.0` — single-image consolidation

When in doubt, copy the structure from the most recent release that
shipped the same flavour of change (extension-point addition, image
shape change, host-bundle ergonomics, etc.).
