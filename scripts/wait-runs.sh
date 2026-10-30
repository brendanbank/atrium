#!/usr/bin/env bash
# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Wait for one or more named workflow runs on a given head ref to
# finish, then exit non-zero if any didn't end in ``success``. Used by
# both ``wait-publish.sh`` (post-tag publish workflows) and the
# ``make ci-wait`` target (pre-merge PR CI), which is why the workflow
# names are arguments rather than baked in.
#
# Usage:
#   ./scripts/wait-runs.sh <head-ref> <workflow.yml> [<workflow.yml>...]
#
# Examples:
#   ./scripts/wait-runs.sh v0.16.1 publish-images.yml publish-npm.yml
#   ./scripts/wait-runs.sh release-tooling ci.yml
#
# Why this exists vs. plain ``gh run watch``:
#
# 1. ``gh run watch --exit-status`` returns 0 in some failure
#    scenarios — observed when watching a multi-job workflow whose
#    overall conclusion settles after ``status=completed`` first
#    appears. We belt-and-braces by **also** reading
#    ``gh run view --json conclusion`` after the watch returns and
#    failing if it isn't ``success``.
# 2. Spinning two parallel ``gh run watch``s in an agent loop is
#    expensive — each cross-cache wakeup costs more than the foreground
#    watch saves. Doing it in bash is one shell, no wakeups.
# 3. Tag- and branch-triggered workflows take a few seconds to register
#    after ``git push``, so we poll briefly to resolve the run id
#    before watching.

set -euo pipefail

if [[ $# -lt 2 ]]; then
  cat >&2 <<EOF
Usage: $0 <head-ref> <workflow.yml> [<workflow.yml>...]
  <head-ref>      tag (e.g. v0.16.1) or branch name (e.g. release-tooling)
  <workflow.yml>  workflow filename(s) under .github/workflows/
EOF
  exit 64
fi

HEAD_REF="$1"
shift
WORKFLOWS=("$@")

cd "$(dirname "$0")/.."

# Resolving by head ref alone has a race: an OLDER run on the same
# branch (from a previous push) is still the most-recent when called
# right after ``git push``, before the new trigger has registered.
# Pin to the commit SHA at the tip of the ref so we wait for the run
# corresponding to *this* push, not whatever was there before.
#
# - For a tag, ``git rev-parse <tag>^{}`` (note the ``^{}``)
#   dereferences the annotated tag to its commit.
# - For a branch, ``git rev-parse <branch>`` returns the local HEAD,
#   which is what was just pushed.
# - Falls back to ``HEAD`` if rev-parse fails — happens when the
#   caller passes something git doesn't know (a bare branch name
#   from a different worktree, etc.); in that case we degrade to the
#   old "most recent by branch" behaviour with a warning.
HEAD_SHA=$(git rev-parse --verify --quiet "$HEAD_REF^{commit}" 2>/dev/null || true)
if [[ -z "$HEAD_SHA" ]]; then
  echo "Warning: could not resolve $HEAD_REF to a commit SHA;" >&2
  echo "  falling back to head-ref filter (may pick stale runs)." >&2
fi

# A run can take a few seconds to register after the trigger event
# (tag push / PR sync). Try for ~60 s before giving up, and skip
# workflows that are configured with ``paths-ignore`` and produced no
# run for this ref (CI for a docs-only branch, for example).
resolve_run() {
  local wf=$1 try
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    local id
    if [[ -n "$HEAD_SHA" ]]; then
      id=$(gh run list --workflow="$wf" --limit 10 \
          --json databaseId,headSha \
          --jq ".[] | select(.headSha == \"$HEAD_SHA\") | .databaseId" \
          | head -1)
    else
      id=$(gh run list --workflow="$wf" --limit 5 \
          --json databaseId,headBranch \
          --jq ".[] | select(.headBranch == \"$HEAD_REF\") | .databaseId" \
          | head -1)
    fi
    if [[ -n "${id:-}" ]]; then
      echo "$id"
      return 0
    fi
    sleep 5
  done
  return 1
}

declare -a RESOLVED=()
declare -a SKIPPED=()
for wf in "${WORKFLOWS[@]}"; do
  echo "Resolving run for $wf on $HEAD_REF..." >&2
  if id=$(resolve_run "$wf"); then
    echo "  $wf → run $id"
    RESOLVED+=("$wf=$id")
  else
    echo "  $wf → no run found (paths-ignore'd? skipping)" >&2
    SKIPPED+=("$wf")
  fi
done

if [[ ${#RESOLVED[@]} -eq 0 ]]; then
  echo "No runs to watch (every workflow was skipped)." >&2
  exit 0
fi

# Watch each resolved run serially. ``gh run watch --exit-status``
# blocks until completion. We don't trust its exit status alone —
# see the doc comment at the top — and re-check the conclusion via
# ``gh run view`` afterwards.
status=0
for entry in "${RESOLVED[@]}"; do
  wf="${entry%%=*}"
  id="${entry##*=}"
  echo
  echo "==> watching $wf (run $id)"
  # ``--exit-status`` is best-effort; we accept whatever it reports
  # and re-check below. ``|| true`` so a non-zero from watch alone
  # doesn't kill the loop before we've run every workflow.
  # ``WATCH_INTERVAL`` (seconds) slows the refresh; in CI each refresh
  # is a full log line, and the default 3 s buries the run log.
  gh run watch "$id" --exit-status --interval "${WATCH_INTERVAL:-3}" || true
  conclusion=$(gh run view "$id" --json conclusion --jq .conclusion 2>/dev/null || echo "")
  if [[ "$conclusion" != "success" ]]; then
    status=1
  fi
done

echo
for entry in "${RESOLVED[@]}"; do
  wf="${entry%%=*}"
  id="${entry##*=}"
  conclusion=$(gh run view "$id" --json conclusion --jq .conclusion 2>/dev/null || echo "?")
  printf '  %-22s %s\n' "$wf" "$conclusion"
done
# ``${arr[@]:+...}`` expands to nothing when the array is empty, dodging
# bash's ``set -u`` "unbound variable" error on an empty array.
for wf in "${SKIPPED[@]:+${SKIPPED[@]}}"; do
  printf '  %-22s skipped (no run)\n' "$wf"
done

exit $status
