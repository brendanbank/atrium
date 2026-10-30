#!/usr/bin/env python3
# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Decide on, and write up, an automatic dependency release.

Driven by ``.github/workflows/auto-release.yml``; runnable locally
too (it only reads git + the GitHub API, and ``plan`` never writes
anything outside ``.context/``).

Usage:
  ./scripts/auto-release.py plan                 # key=value lines on stdout
  ./scripts/auto-release.py matrix-row X.Y.Z     # insert the compat-matrix row
  ./scripts/auto-release.py notes X.Y.Z          # release notes on stdout
  ./scripts/auto-release.py title X.Y.Z          # release title on stdout

``plan`` releases only when ALL of these hold:

1. Every commit on master since the last ``vX.Y.Z`` tag is either a
   merged Dependabot PR or a docs / tooling-only change (see
   ``RIDE_ALONG``). Anything else is hand-written work, and that gets a
   hand-written release - the auto-release stands aside rather than
   ship it under a "dependency updates" headline.
2. At least one of the Dependabot merges touches something outside
   ``.github/``. An Actions-only bump changes CI, not the image or the
   npm packages, so there is nothing new to publish.
3. ``backend/pyproject.toml`` still carries the last tag's version. A
   bumped-but-untagged version means a human release is in progress.
4. The newest commit is at least ``AUTO_RELEASE_QUIET_MINUTES`` (default
   60) old. Dependabot's weekly run opens several PRs at once; waiting
   for master to go quiet folds them into one release instead of one
   per PR.

``plan`` also writes the qualifying PRs to ``.context/auto-release.json``;
``matrix-row``, ``notes`` and ``title`` read that file, so run ``plan``
first.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".context" / "auto-release.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "brendanbank/atrium")
QUIET_MINUTES = int(os.environ.get("AUTO_RELEASE_QUIET_MINUTES", "60"))
DEPENDABOT = "dependabot[bot]"

# Paths that never reach a published artifact (the image is built from
# backend/ + frontend/, the npm packages from packages/). A hand-written
# commit touching only these can ride along in an automatic release.
RIDE_ALONG = re.compile(r"(^docs/|^\.github/|^scripts/|^Makefile$|\.md$)")

ECOSYSTEMS = {
    "uv": "Python backend",
    "pip": "Python backend",
    "npm_and_yarn": "npm",
    "docker": "Docker base image",
    "github_actions": "GitHub Actions (CI only)",
}

# "Bumps [pyjwt](https://...) from 2.13.0 to 2.15.0." (single update)
# "Updates `axios` from 1.18.0 to 1.20.0"            (grouped update)
_BUMPS = re.compile(r"^Bumps \[([^\]]+)\]\([^)]*\) from (\S+) to (\S+?)\.?$", re.M)
_UPDATES = re.compile(r"^Updates `([^`]+)` from (\S+) to (\S+?)\.?$", re.M)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def gh_api(path: str):
    out = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def emit(**kv: str) -> None:
    # One line per key, newlines squashed: the workflow appends this to
    # $GITHUB_OUTPUT verbatim.
    for k, v in kv.items():
        print(f"{k}={' '.join(str(v).split())}")


def skip(reason: str) -> int:
    log(f"No release: {reason}")
    emit(release="no", reason=reason)
    return 0


def latest_tag() -> str | None:
    # Highest release tag reachable from HEAD, so a tag cut on a side
    # branch can't become the diff base.
    for tag in git("tag", "--merged", "HEAD", "-l", "v*", "--sort=-v:refname").splitlines():
        if re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            return tag
    return None


def pyproject_version() -> str:
    text = (ROOT / "backend" / "pyproject.toml").read_text()
    m = re.search(r'^version = "([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("no version in backend/pyproject.toml")
    return m.group(1)


def alembic_head() -> str:
    versions = sorted((ROOT / "backend" / "alembic" / "versions").glob("*.py"))
    m = re.search(r'^revision = "([^"]+)"', versions[-1].read_text(), re.M)
    return m.group(1) if m else versions[-1].stem


def merged_pr(sha: str) -> dict | None:
    for pr in gh_api(f"repos/{REPO}/commits/{sha}/pulls"):
        if pr.get("merged_at"):
            return pr
    return None


def parse_updates(body: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for rx in (_BUMPS, _UPDATES):
        for name, old, new in rx.findall(body or ""):
            # Multi-directory groups repeat the same package once per
            # directory; one line in the notes is enough.
            seen.setdefault(name, {"name": name, "from": old, "to": new})
    return list(seen.values())


def major(version: str) -> str:
    m = re.match(r"v?(\d+)", version)
    return m.group(1) if m else version


def fixed_alerts(since: str) -> list[dict]:
    """Dependabot alerts closed as fixed since ``since`` (ISO date).

    Best effort: the alerts API needs a token with Dependabot-alerts
    read access, which the workflow's GITHUB_TOKEN may not have. When
    it can't be read, security fixes are still flagged from the
    ``*-security-updates`` branch name; only the advisory detail is lost.
    """
    try:
        alerts = gh_api(f"repos/{REPO}/dependabot/alerts?state=fixed&sort=updated&per_page=100")
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        log("Dependabot alerts not readable with this token; advisory detail skipped.")
        return []
    out = []
    for a in alerts:
        if (a.get("fixed_at") or "") < since:
            continue
        adv = a.get("security_advisory") or {}
        out.append(
            {
                "package": (a.get("dependency") or {}).get("package", {}).get("name", ""),
                "ghsa": adv.get("ghsa_id", ""),
                "cve": adv.get("cve_id") or "",
                "severity": adv.get("severity", ""),
                "summary": adv.get("summary", ""),
                "url": a.get("html_url", ""),
            }
        )
    return out


def cmd_plan() -> int:
    prev = latest_tag()
    if not prev:
        return skip("no vX.Y.Z tag to release from")
    prev_version = prev[1:]
    if pyproject_version() != prev_version:
        return skip(
            f"backend/pyproject.toml is at {pyproject_version()}, not {prev_version}"
            " - a hand release is in progress; tag it by hand"
        )

    shas = git("rev-list", "--first-parent", "--reverse", f"{prev}..HEAD").split()
    if not shas:
        return skip(f"nothing on master since {prev}")

    bumps: list[dict] = []
    riders: list[dict] = []
    for sha in shas:
        files = git("diff", "--name-only", f"{sha}^", sha).splitlines()
        subject = git("log", "-1", "--format=%s", sha)
        pr = merged_pr(sha)
        entry = {
            "sha": sha,
            "subject": subject,
            "files": files,
            "number": pr["number"] if pr else None,
            "title": pr["title"] if pr else subject,
            "url": pr["html_url"] if pr else "",
        }
        if pr and pr["user"]["login"] == DEPENDABOT and pr["head"]["ref"].startswith("dependabot/"):
            ref = pr["head"]["ref"]
            entry["branch"] = ref
            entry["ecosystem"] = ref.split("/")[1]
            entry["security"] = "-security-updates" in ref
            entry["updates"] = parse_updates(pr.get("body") or "")
            bumps.append(entry)
        elif files and all(RIDE_ALONG.search(f) for f in files):
            riders.append(entry)
        else:
            return skip(f"{sha[:12]} {subject} is hand-written work; it ships with a hand release")

    if not bumps:
        return skip(f"no Dependabot merges since {prev}")
    if not any(not f.startswith(".github/") for b in bumps for f in b["files"]):
        return skip("the Dependabot merges only touch .github/ - nothing new to publish")

    age = (time.time() - int(git("log", "-1", "--format=%ct", "HEAD"))) / 60
    if age < QUIET_MINUTES:
        return skip(f"last merge is {age:.0f} min old; waiting for {QUIET_MINUTES} min of quiet")

    since = git("log", "-1", "--format=%cI", prev)
    bumped = {u["name"] for b in bumps for u in b["updates"]}
    alerts = [a for a in fixed_alerts(since) if a["package"] in bumped]
    for b in bumps:
        if any(a["package"] in {u["name"] for u in b["updates"]} for a in alerts):
            b["security"] = True

    maj, mnr, pat = prev_version.split(".")
    nxt = f"{maj}.{mnr}.{int(pat) + 1}"
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {
                "prev": prev_version,
                "next": nxt,
                "bumps": bumps,
                "riders": riders,
                "alerts": alerts,
            },
            indent=2,
        )
    )
    numbers = ", ".join(f"#{b['number']}" for b in bumps)
    log(f"Release {nxt}: {numbers}")
    emit(
        release="yes",
        version=nxt,
        prev=prev_version,
        prs=numbers,
        reason=f"Dependabot merges since {prev}: {numbers}",
    )
    return 0


def load(version: str) -> dict:
    state = json.loads(STATE.read_text())
    if state["next"] != version:
        raise SystemExit(f"{STATE} is for {state['next']}, not {version}; rerun plan")
    return state


def describe(update: dict) -> str:
    tag = " (major)" if major(update["from"]) != major(update["to"]) else ""
    return f"`{update['name']}` {update['from']} -> {update['to']}{tag}"


def bump_line(b: dict) -> str:
    what = ", ".join(describe(u) for u in b["updates"]) or b["title"]
    return f"{ECOSYSTEMS.get(b['ecosystem'], b['ecosystem'])}: {what}"


def advisory(a: dict) -> str:
    ident = a["cve"] or a["ghsa"]
    sev = f", {a['severity']}" if a["severity"] else ""
    return f"[{ident}]({a['url']}){sev}: {a['summary']}"


def cmd_title(version: str) -> int:
    state = load(version)
    kind = (
        "dependency security release"
        if any(b["security"] for b in state["bumps"])
        else "dependency updates"
    )
    print(f"v{version} — {kind}")
    return 0


def cmd_matrix_row(version: str) -> int:
    state = load(version)
    prev = state["prev"]
    items = []
    for b in state["bumps"]:
        if b["ecosystem"] == "github_actions":
            continue
        items.append(f"{bump_line(b)} (#{b['number']})")
    for a in state["alerts"]:
        items.append(f"**{a['cve'] or a['ghsa']}** ({a['package']})")
    detail = "; ".join(items).replace("|", "\\|")
    row = (
        f"| [{version}](https://github.com/{REPO}/releases/tag/v{version}) "
        f"| unchanged (`{alembic_head()}`) | — | — | Automatic dependency release, "
        f"no migrations, no new env vars and no host code changes. {detail}. |"
    )

    path = ROOT / "docs" / "compat-matrix.md"
    lines = path.read_text().splitlines(keepends=True)
    anchor = f"| [{prev}]("
    at = next((i for i, ln in enumerate(lines) if ln.startswith(anchor)), None)
    if at is None:
        # Fall back to the end of the first table.
        start = next(i for i, ln in enumerate(lines) if ln.startswith("| ---"))
        at = start
        while at + 1 < len(lines) and lines[at + 1].startswith("|"):
            at += 1
    lines.insert(at + 1, row + "\n")
    path.write_text("".join(lines))
    log(f"compat-matrix: added the {version} row after line {at + 1}")
    return 0


def cmd_notes(version: str) -> int:
    state = load(version)
    prev = state["prev"]
    bumps, riders, alerts = state["bumps"], state["riders"], state["alerts"]
    security = [b for b in bumps if b["security"]]
    shipped = [b for b in bumps if b["ecosystem"] != "github_actions"]
    majors = any(major(u["from"]) != major(u["to"]) for b in bumps for u in b["updates"])

    out = ["## Highlights", ""]
    # Count packages, not PRs: one grouped PR can carry a dozen updates.
    n = sum(len(b["updates"]) or 1 for b in shipped)
    lead = (
        f"An automatic maintenance release. It ships {n} dependency update"
        f"{'s' if n != 1 else ''} that Dependabot opened and that merged once "
        "the full CI suite (backend tests, frontend typecheck, lint and unit "
        "tests, and the Playwright end-to-end run) had passed."
    )
    if security:
        lead += (
            (" At least one of them fixes" if n > 1 else " It fixes")
            + " a published security advisory, so "
            "image scanners that flagged the previous release should come up "
            "clean on this one."
        )
    if majors:
        lead += " Some updates cross a major version of the library; they are marked below."
    out += [
        lead,
        "",
        "Nothing in atrium's own code changed. There are no database "
        "migrations, no new environment variables and nothing on the host "
        "extension contract moved. If you run atrium in production, bump the "
        "image pin and redeploy. That is the whole upgrade.",
        "",
    ]

    if alerts:
        out += ["## Security fixes", ""]
        out += [f"- `{a['package']}`: {advisory(a)}" for a in alerts]
        out.append("")

    out += ["## What's updated", ""]
    for b in bumps:
        flag = "**Security.** " if b["security"] else ""
        out.append(f"- {flag}{bump_line(b)} ([#{b['number']}]({b['url']}))")
    out.append("")

    if riders:
        out += ["## Also included", ""]
        for r in riders:
            ref = f" ([#{r['number']}]({r['url']}))" if r["number"] else ""
            out.append(f"- {r['title']}{ref}")
        out.append("")

    out += [
        "## Host bundle impact",
        "",
        f"No host-facing changes. The host SDK packages moved to `{version}` in "
        "lockstep with the image but carry no changes, so bumping them is "
        f"optional. See the [v{version} row](https://github.com/{REPO}/blob/"
        "master/docs/compat-matrix.md) in the compatibility matrix.",
        "",
    ]

    # The image-tag table and the upgrade snippet are identical on every
    # release; take them from the hand-release stencil so the two kinds
    # of release can't drift apart.
    stencil = (ROOT / ".github" / "RELEASE_NOTES_TEMPLATE.md").read_text()
    tail = stencil[stencil.index("## Image details") :]
    tail = re.sub(r"<!--.*?-->\n*", "", tail, flags=re.S)
    maj, mnr, _ = version.split(".")
    for k, v in {
        "{{VERSION}}": version,
        "{{MINOR}}": f"{maj}.{mnr}",
        "{{MAJOR}}": maj,
        "{{PREV_VERSION}}": prev,
    }.items():
        tail = tail.replace(k, v)
    out.append(tail.rstrip())
    print("\n".join(out))
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["plan"] and len(argv) == 1:
        return cmd_plan()
    cmds = {"matrix-row": cmd_matrix_row, "notes": cmd_notes, "title": cmd_title}
    if len(argv) == 2 and argv[0] in cmds and re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        return cmds[argv[0]](argv[1])
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
