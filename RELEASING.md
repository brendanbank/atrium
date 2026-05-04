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

```bash
make preflight
```

That target runs every gate CI runs, in order, with defensive
teardown of the smoke stacks between them (they share named docker
volumes):

```
test-backend           # ~1 min, testcontainers-mysql
test-frontend          # vitest unit tests, ~10 s
frontend-typecheck     # tsc --noEmit
lint                   # ruff + eslint; 1 pre-existing warning is OK
smoke                  # Playwright against the e2e stack, ~30 s
smoke-down             # tear down before smoke-hello
smoke-hello            # Hello World e2e against prod images
smoke-hello-down       # final cleanup
```

Total wall-clock: ~5 min. Failures here cost seconds-to-minutes;
the same failures caught by `make ci-wait` after pushing cost a
3-5 minute GHA round-trip plus the push. Run `preflight` for any
non-trivial release branch.

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

For trivial changes (docs-only, comment fixes), skip `preflight`
and rely on `make ci-wait BR=<branch>` after push — the workflow
suite is the source of truth either way.

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
make release-bump V=X.Y.Z
```

That target runs `scripts/bump-version.sh X.Y.Z` (mutates
`backend/pyproject.toml`, every `packages/*/package.json`,
`packages/create-atrium-host/src/cli.js`'s `DEFAULT_ATRIUM_VERSION`,
the host SDK READMEs' `Pin \`^X.Y\`` pin examples, the `--atrium`
default in the scaffolder's README options table, the bootstrap
walkthroughs in `docs/new-project/`, the example Dockerfile under
`examples/hello-world/`, the scaffolder's render-test compose pin,
and the scaffolder template's override-flag README example), then
refreshes both lockfiles, then runs `scripts/check-stale-versions.sh
X.Y.Z` to confirm nothing was missed.

The four host SDK packages must move in lockstep — publish-npm.yml
fans out to every one on tag push, so a stale version anywhere blocks
the release. The bumper handles that.

The intra-workspace deps use `workspace:*`, so the `pnpm-lock.yaml`
diff after a bump shows up only in the `importers:` section — the
package versions further down don't move. A near-empty diff is
expected, not a sign that the bump didn't take.

`docs/compat-matrix.md` is **not** auto-bumped — it gets a new row
per release and that row is hand-written. Add the row before
committing the bump:

- One row per published `vX.Y.Z`, with the alembic head, any new
  registry hooks, deprecations, and env / config changes. Cells stay
  terse; the release notes carry the prose. Use an em-dash for axes
  that didn't move in this release. The link in the *Atrium* column
  points at the release you're about to publish (step 9 below).

Other docs that legitimately reference past versions (`RELEASING.md`
prose, `docs/published-images.md` "since 0.X" notes,
`docs/adr/`) are excluded from the bumper by design — they're
historical narration, not pins.

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

Three workflows fire on PR: `CI`, `CodeQL`, `Security`.

```bash
make ci-wait BR=<branch>
```

That target wraps `scripts/wait-ci.sh <branch>` which itself calls
`scripts/wait-runs.sh <branch> ci.yml codeql.yml security.yml`. It
resolves each run by branch name, watches it with
`gh run watch --exit-status`, then re-reads `gh run view --json
conclusion` because **`gh run watch --exit-status` is not reliable
on its own** — observed in this repo returning exit 0 for a
multi-job run that ultimately settled to `conclusion: failure` (the
watch returned the moment `status` became `completed`, before the
conclusion was finalised). The wrapper exits non-zero if any
workflow's final conclusion isn't `success`.

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

### 6a. Post a `Shipped:` comment when the AC offered options or moved

The `Closes #N` trailer on the squash-merge auto-closes the issue,
but the closed-issue page still shows the *as-filed* AC. Future
follow-up issues that reference the parent will be written against
that AC unless the maintainer leaves a one-liner stating what
actually shipped.

When the closed issue's AC offered alternatives (`option A OR option
B`), or when the implementation diverged from the AC (smaller
surface, deferred sub-feature, slightly different API shape), post a
`Shipped:` comment on the issue immediately after merge:

```bash
gh issue comment <N> --body "Shipped: chose option A (typed sub-object on /admin/users). Did **not** ship the sibling endpoint variant — defer to a follow-up if a host needs it. AC item *bulk role assignment* is partial; multi-role works on create but the edit form still drives a single role at a time (filed #NN)."
```

Skip the comment when the issue is small and shipped exactly as
written; it's specifically for the cases where someone reading the
issue six months later would otherwise have to diff the AC against
the merge to find out what's real. Issue #132 documents the
motivation in detail.

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
make release-wait V=<X.Y.Z>
```

That target wraps `scripts/wait-publish.sh v<X.Y.Z>` — resolves both
runs by tag, watches them serially with `gh run watch --exit-status`,
prints a one-line summary, and exits non-zero if either failed. One
foreground bash call instead of two parallel `gh run watch`s.

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
- **## Host bundle impact.** A 1-3 sentence paragraph aimed at host-
  bundle authors: which registries / SDK exports / config namespaces
  / env vars moved this release, and whether a host should re-skim
  the contract docs. This is the one section in the release notes
  *every* host author reads top-to-bottom on every upgrade, so make
  it stand alone — link the relevant
  [`compat-matrix.md`](docs/compat-matrix.md) row, name the affected
  hooks, call out the SDK-package version they should pin to.
  Write **"No host-facing changes."** verbatim when nothing moved —
  that absence is itself the answer they were looking for.
- **## Documentation.** What changed in `docs/` — even a one-liner.
  Hosts read this to know whether to re-skim the contract docs.
- **## Image details.** The registry-tag table (`X.Y.Z`, `X.Y`, `X`,
  `latest`). Keep it identical to the previous release; readers learn
  to skim it.
- **## Upgrading from v\<previous\>.** Compose snippet showing both
  the auto-uptake and fully-pinned forms. Call out migrations / env
  changes / breaking changes here, even if they're "none".

Render the working draft from the stencil:

```bash
make release-notes V=<X.Y.Z>
```

That writes `.context/release-notes-v<X.Y.Z>.md` (gitignored), built
from `.github/RELEASE_NOTES_TEMPLATE.md` with `{{VERSION}}`,
`{{MINOR}}`, `{{MAJOR}}`, `{{PREV_VERSION}}` substituted. It also
pre-stubs one `## <issue title> — closes #N` section per `closes
#N` (or `fixes #N` / `resolves #N`) referenced in commits since the
previous `v*` tag, with the issue title pulled from the GitHub issue.

Edit the prose by hand:

- Write the **Highlights** paragraph (1 paragraph, non-engineer
  audience, what shipped + motivation + what's NOT in scope).
- Fill in each per-issue section: user-visible behaviour first, then
  technical detail, then code blocks for any new API surface.
- Delete sections that don't apply (e.g. **Documentation** if nothing
  in `docs/` moved this release).
- If the alembic head moved or env vars changed, add the
  corresponding paragraph to **Upgrading from v\<previous\>**.

Then create the release:

```bash
gh release create v<X.Y.Z> \
  --title "v<X.Y.Z> — <headline>" \
  --notes-file .context/release-notes-v<X.Y.Z>.md
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
