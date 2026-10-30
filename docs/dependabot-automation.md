# Dependabot lockfile auto-relock, auto-merge + auto-release

Dependabot's **grouped, multi-directory npm** updates (the weekly
`npm-version-updates` group spanning `/frontend` and
`/examples/hello-world/frontend`) bump the `package.json` files but
leave both pnpm lockfiles untouched. Every such PR therefore lands red
with `ERR_PNPM_OUTDATED_LOCKFILE` across the `frontend`, `scaffolder`,
and `hello-world-e2e` jobs and needs a manual relock. This automation
removes that toil, and then carries the update all the way to a
published patch release.

> Backend (`uv.lock`) is handled separately by `uv-lock-refresh.yml` /
> `uv-lock-commit.yml`. Single-directory npm updates are fine —
> Dependabot relocks those itself. Only the grouped multi-directory
> pnpm case needs this.

## What runs

| Workflow | Trigger | Job | Does |
| --- | --- | --- | --- |
| `pnpm-lock-refresh.yml` | `pull_request` touching a frontend manifest/lock, Dependabot only | unprivileged (`contents: read`) | Checks out the PR head, regenerates the **root** lock (`pnpm install --lockfile-only --ignore-scripts`, covers the hello-world example) and the **standalone** `frontend/pnpm-lock.yaml` (`--ignore-workspace`), uploads both + PR metadata as artifacts. |
| `pnpm-lock-commit.yml` | `workflow_run` of the above completing | privileged (`contents: write`) | Validates the metadata, then commits whichever lockfiles changed back to the PR branch in **one atomic Git Data API commit** (fast-forward only). Never checks out PR code. |
| `dependabot-auto-merge.yml` | `pull_request` + `workflow_run` of `CI` | `mark` / `merge` | `mark` labels any Dependabot PR (npm, uv/pip, Docker, Actions; version or security) `dependabot-automerge` unless it contains a **major** bump. `merge` squash-merges a labelled PR once CI passes on its current head. |
| `auto-release.yml` | hourly `schedule` + `workflow_dispatch` | `release` | When master holds nothing but Dependabot merges since the last tag, cuts the next patch release: `make release-bump`, a compat-matrix row, generated notes, tag, dispatches `publish-images.yml` + `publish-npm.yml`, and creates the GitHub release once both succeed. See [Auto-release](#auto-release) below. |

The split (unprivileged relock that touches PR content vs. privileged
commit that never does) follows the GitHub Security Lab "preventing pwn
requests" guidance, mirroring the existing `uv-lock-*` pair. pnpm runs
with `--ignore-scripts`, so no package lifecycle script from the PR ever
executes.

## One-time setup (required for green CI + auto-merge)

A commit pushed with the default `GITHUB_TOKEN` does **not** re-trigger
`pull_request` workflows, so without a separate token the relock commit
would land but CI wouldn't re-run on the fixed lockfiles — the PR would
stay red and never auto-merge. Provide a token so the relock commit
re-runs CI:

1. Create a **fine-grained PAT** scoped to this repository with
   **Contents: Read and write** (and **Pull requests: Read and write**
   if you want it to be reusable). A short expiry plus calendar reminder
   to rotate is fine.
2. Add it as an **Actions** repository secret named
   **`DEPENDABOT_LOCKFILE_TOKEN`**
   (`Settings -> Secrets and variables -> Actions -> New repository
   secret`). It's read only by `pnpm-lock-commit.yml`, which runs in the
   trusted base context (not the Dependabot `pull_request` context), so
   a standard Actions secret is correct — it does **not** need to be a
   Dependabot secret.
3. Ensure **Settings -> General -> Pull Requests -> Allow squash
   merging** is enabled (it already is — the repo squash-merges).

Without the secret the workflows still commit the refreshed lockfiles
(via the fallback `GITHUB_TOKEN`); you just have to nudge CI to re-run
(e.g. close/reopen the PR) and merge manually — i.e. no worse than
today, minus the hand relock.

## Scope / safety

- Every `dependabot/*` branch is eligible: npm, uv/pip, Docker and
  GitHub Actions, version and security updates alike.
- **Major** version bumps are never auto-merged — the `mark` job leaves
  them unlabelled for human review. Patch/minor groups auto-merge only
  after the **full** CI suite (typecheck, lint, unit, build, e2e,
  scaffolder, hello-world-e2e) passes on the relocked commit.
- GitHub Actions updates edit `.github/workflows/`, which
  `GITHUB_TOKEN` may not merge. The `merge` job uses
  `DEPENDABOT_LOCKFILE_TOKEN` for those, so the PAT also needs
  **Workflows: Read and write** and **Pull requests: Read and write**.
  Without them the merge step fails and the PR waits for a hand merge;
  an Actions-only update never triggers a release, so nothing else is
  held up.
- The `merge` job re-checks that the PR is Dependabot-authored, carries
  the label, and that CI passed on the *exact* current head SHA before
  merging.

## Auto-release

`auto-release.yml` runs at :23 past every hour. It hands the decision
to `scripts/auto-release.py plan`, which releases only when **all** of
these hold:

1. Every commit on master since the last `vX.Y.Z` tag is a merged
   Dependabot PR, or touches only docs / tooling (`*.md`, `docs/`,
   `.github/`, `scripts/`, `Makefile`). Any other commit is hand-written
   work and gets a hand-written release (RELEASING.md); the auto-release
   stands aside until that release is cut, and says why in the run
   summary.
2. At least one Dependabot merge touches something outside `.github/`.
   An Actions-only bump changes CI, not the image or the npm packages.
3. `backend/pyproject.toml` still carries the last tag's version (a
   bumped-but-untagged version means a hand release is in progress).
4. The newest commit on master is at least an hour old, so the weekly
   batch of PRs lands as one release instead of one per PR. Override
   with the `AUTO_RELEASE_QUIET_MINUTES` env var on the workflow.

The release itself is the hand procedure, scripted: `make
release-bump` (every pin, both lockfiles, the stale-version check), a
generated `docs/compat-matrix.md` row, a commit + annotated tag pushed
atomically with `GITHUB_TOKEN`, a `workflow_dispatch` of both publish
workflows (a tag pushed with `GITHUB_TOKEN` doesn't fire them), and the
GitHub release once both publish runs succeed.

The notes are generated, not hand-written: a plain-English Highlights
paragraph, the advisories fixed (when the token can read Dependabot
alerts; otherwise security updates are flagged from the
`*-security-updates` branch name), one line per updated package, and
the same Image details / Upgrading sections as a hand release, taken
from `.github/RELEASE_NOTES_TEMPLATE.md`.

The commit and tag are made by `github-actions[bot]` and are not
GPG-signed.

Preview what the next run would do from a local checkout:

```bash
git fetch origin --tags && git checkout --detach origin/master
./scripts/auto-release.py plan
```

## Tuning

- **Auto-merge majors too** (CI is comprehensive): drop the
  `update-type` guard in the `mark` job so every group gets labelled.
- **Stop auto-releasing**: disable `auto-release.yml` (`gh workflow
  disable auto-release.yml`); merged updates then wait for the next hand
  release, as before.
- **Relock only, no auto-merge**: delete `dependabot-auto-merge.yml`;
  the relock pair still makes the PRs go green for a manual merge.
- **Per-package or per-developer review**: add a required reviewer or
  branch-protection rule on `master`; the `merge` job's `gh pr merge`
  will then queue behind it.
