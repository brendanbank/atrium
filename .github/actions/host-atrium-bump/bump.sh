#!/usr/bin/env bash
# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause
#
# Bump a host repo's pinned atrium version across every place it
# appears, and regenerate the frontend lockfile.
#
# The image tag and the @brendanbank/atrium-host-* npm packages are
# version-locked: a host running image X with SDK packages from Y is
# not a supported combination, and the failure is a runtime one (the
# served bundle calls endpoints the image does not serve). This script
# therefore edits all of them together or refuses — partial bumps are
# not expressible.
#
# Configuration arrives as environment variables so the same script
# serves hosts with different pin layouts. The generated host from
# create-atrium-host pins in three files; a host that also pins in its
# README or CI workflow lists those too.
#
#   ATRIUM_IMAGE      image repo, no tag   (default ghcr.io/brendanbank/atrium)
#   PIN_CANONICAL     file the current version is read from
#   PIN_FILES         newline-separated files holding the image tag
#   NPM_PACKAGES      newline-separated npm packages pinned to the same version
#   FRONTEND_DIR      directory holding package.json  (default frontend)
#   PKG_MANAGER       pnpm | npm                      (default pnpm)
#
# Usage:
#   bump.sh <new-version>            # edit + relock
#   bump.sh <new-version> --check    # dry-run, print what would change
#   bump.sh <new-version> --ci       # relock without running package scripts

set -euo pipefail

NEW="${1:-}"
MODE="${2:-apply}"

if [[ -z "$NEW" ]]; then
  echo "usage: bump.sh <new-version> [--check | --ci]" >&2
  exit 2
fi
case "$MODE" in
  apply|--check|--ci) ;;
  *) echo "error: mode must be --check or --ci (got: $MODE)" >&2; exit 2 ;;
esac

# Tolerate a leading "v" — release tags carry one, image tags do not.
NEW="${NEW#v}"
if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: version must look like X.Y.Z (got: $NEW)" >&2
  exit 1
fi

ATRIUM_IMAGE="${ATRIUM_IMAGE:-ghcr.io/brendanbank/atrium}"
PIN_CANONICAL="${PIN_CANONICAL:-.env.example}"
FRONTEND_DIR="${FRONTEND_DIR:-frontend}"
PKG_MANAGER="${PKG_MANAGER:-pnpm}"

# Newline-separated inputs, blank lines and surrounding space dropped.
# Built with a read loop rather than `readarray` so the script also runs
# under the bash 3.2 that ships with macOS — hosts wire this into a
# `make atrium-bump` target and run it on a laptop, not only on a runner.
_split_lines() {
  local _line
  _RESULT=()
  while IFS= read -r _line; do
    _line="${_line#"${_line%%[![:space:]]*}"}"
    _line="${_line%"${_line##*[![:space:]]}"}"
    # `if`, not `[ -n "$_line" ] && _RESULT+=(...)`. A YAML block scalar
    # keeps its trailing newline, so the last line read here is empty:
    # the && list then returns 1, that becomes the while loop's status
    # and so the function's return value, and `set -e` kills the script
    # with no output at all. That is exactly how this failed on its
    # first real release.
    if [ -n "$_line" ]; then
      _RESULT+=("$_line")
    fi
  done < <(printf '%s\n' "$1")
  return 0
}

_split_lines "${PIN_FILES:-}";    IMG_FILES=("${_RESULT[@]:-}")
_split_lines "${NPM_PACKAGES:-}"; NPM_PKGS=("${_RESULT[@]:-}")
# An empty split yields one empty element under the :- guard; drop it.
# Spelled as `if` for the same reason as in _split_lines: a trailing
# && that short-circuits is a silent-exit hazard under set -e, and it
# costs nothing to keep every one of them out of this script.
if [ "${#IMG_FILES[@]}" -eq 1 ] && [ -z "${IMG_FILES[0]}" ]; then
  IMG_FILES=()
fi
if [ "${#NPM_PKGS[@]}" -eq 1 ] && [ -z "${NPM_PKGS[0]}" ]; then
  NPM_PKGS=()
fi

if [[ ${#IMG_FILES[@]} -eq 0 ]]; then
  echo "error: PIN_FILES is empty — nothing to rewrite" >&2
  exit 1
fi

# Read the current version from the canonical file. Any occurrence of
# the image tag will do; the lockstep check below is what guarantees
# the rest of the files agree with it.
# Captured through an explicit `if !` rather than a bare assignment:
# under `set -e` with pipefail, a grep that matches nothing aborts the
# script on the assignment itself, so the error below could never print.
# Silent exit 1 is the worst failure mode this script has.
if ! _pin="$(grep -oE "${ATRIUM_IMAGE}:[0-9]+\.[0-9]+\.[0-9]+" "$PIN_CANONICAL" | head -n1)"; then
  echo "error: no '$ATRIUM_IMAGE:X.Y.Z' pin found in $PIN_CANONICAL (cwd: $PWD)" >&2
  exit 1
fi
CUR="${_pin##*:}"
if [[ -z "$CUR" ]]; then
  echo "error: could not parse a version out of '$_pin'" >&2
  exit 1
fi

if [[ "$CUR" == "$NEW" ]]; then
  echo "current pin is already $CUR — nothing to do."
  exit 0
fi

OLD_TAG="${ATRIUM_IMAGE}:${CUR}"
NEW_TAG="${ATRIUM_IMAGE}:${NEW}"

echo "Bumping atrium: $CUR -> $NEW"
echo

# Refuse if any pinned file disagrees with the canonical one. A repo
# that is already out of lockstep must be fixed by hand — bumping from
# a stale value would silently leave the odd file behind, which is the
# failure this script exists to prevent.
missing=0
for f in "${IMG_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "error: $f does not exist" >&2
    missing=1
  elif ! grep -qF "$OLD_TAG" "$f"; then
    echo "error: $f does not contain expected pin '$OLD_TAG'" >&2
    missing=1
  fi
done
[[ $missing -eq 0 ]] || {
  echo >&2
  echo "Refusing to proceed: pinned files are not in lockstep." >&2
  exit 1
}

PKG_JSON="$FRONTEND_DIR/package.json"
if [[ ${#NPM_PKGS[@]} -gt 0 ]]; then
  [[ -f "$PKG_JSON" ]] || { echo "error: $PKG_JSON not found" >&2; exit 1; }
  for pkg in "${NPM_PKGS[@]}"; do
    if ! grep -qE "\"${pkg}\": \"\\^?${CUR//./\\.}\"" "$PKG_JSON"; then
      echo "error: $PKG_JSON does not have $pkg pinned at $CUR" >&2
      exit 1
    fi
  done
fi

if [[ "$MODE" == "--check" ]]; then
  echo "(dry-run) Would rewrite:"
  for f in "${IMG_FILES[@]}"; do
    n=$(grep -cF "$OLD_TAG" "$f" || true)
    printf "  %-32s %d occurrence(s)\n" "$f" "$n"
  done
  for pkg in "${NPM_PKGS[@]:-}"; do
    # Last command in the loop body: a bare `&&` here makes the whole
    # for-loop exit 1 when the final element is empty, which under
    # set -e kills --check silently.
    if [[ -n "$pkg" ]]; then
      printf "  %-32s %s -> %s\n" "$PKG_JSON" "$pkg@$CUR" "$NEW"
    fi
  done
  exit 0
fi

# --- Apply ---------------------------------------------------------------

# Literal substitution via awk, not sed -i: sed -i's argument handling
# differs between BSD and GNU, and the tag contains '/' and '.' which
# would need escaping in a regex.
for f in "${IMG_FILES[@]}"; do
  tmp="$(mktemp)"
  awk -v old="$OLD_TAG" -v new="$NEW_TAG" '{
    n = old; gsub(/[][\\.^$(){}|*+?]/, "\\\\&", n)
    gsub(n, new)
    print
  }' "$f" > "$tmp"
  mv "$tmp" "$f"
  echo "  edited $f"
done

if [[ ${#NPM_PKGS[@]} -gt 0 ]]; then
  # Only the listed packages: a bare "^$CUR" match would also rewrite
  # unrelated dependencies that happen to sit on the same version.
  for pkg in "${NPM_PKGS[@]}"; do
    tmp="$(mktemp)"
    awk -v pkg="$pkg" -v cur="$CUR" -v new="$NEW" '
      index($0, "\"" pkg "\":") { sub(cur, new) }
      { print }
    ' "$PKG_JSON" > "$tmp"
    mv "$tmp" "$PKG_JSON"
  done
  echo "  edited $PKG_JSON"

  for pkg in "${NPM_PKGS[@]}"; do
    if ! grep -qE "\"${pkg}\": \"\\^?${NEW//./\\.}\"" "$PKG_JSON"; then
      echo "error: $PKG_JSON edit failed for $pkg — inspect by hand" >&2
      exit 1
    fi
  done

  # Relock. --ci uses --lockfile-only --ignore-scripts because the
  # workflow that runs it holds a write-capable token, and a full
  # install would execute lifecycle scripts from freshly-resolved
  # packages beside it. The host's own CI does the real install on the
  # resulting PR and fails on a bad relock.
  echo
  case "$PKG_MANAGER:$MODE" in
    pnpm:--ci) ( cd "$FRONTEND_DIR" && pnpm install --lockfile-only --ignore-scripts ) ;;
    pnpm:*)    ( cd "$FRONTEND_DIR" && pnpm install ) ;;
    npm:--ci)  ( cd "$FRONTEND_DIR" && npm install --package-lock-only --ignore-scripts ) ;;
    npm:*)     ( cd "$FRONTEND_DIR" && npm install ) ;;
    *) echo "error: unknown PKG_MANAGER '$PKG_MANAGER'" >&2; exit 1 ;;
  esac
fi

echo
echo "atrium pin: $CUR -> $NEW (working tree updated, not committed)"
