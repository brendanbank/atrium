---
name: atrium-fix-bug
description: >
  Diagnose and fix a bug reported in the atrium repo (typically a GitHub issue,
  often a UI/mobile bug). Use whenever the user asks to "fix issue #N",
  "investigate #N", "look at this bug", or pastes an atrium issue URL / body
  and asks for a fix. The skill enforces a diagnose-first workflow: try to
  reproduce and form a concrete hypothesis from the code before bouncing the
  issue back to the reporter. Only ask the reporter for more info when an
  honest investigation has failed to produce a hypothesis — and even then,
  ask specific yes/no questions, not "please provide more information".
---

# Atrium bug-fix workflow

You are fixing a real bug in the atrium repo. The reporter has done you the
favour of writing the issue down — your job is to **work the problem from
the code first**, not to immediately ask them to do more work.

The bar: don't ping the reporter unless you've genuinely tried to reproduce
or trace the bug and got stuck. Vague reports are normal; most can be
diagnosed from the code path alone once you find the right component.

## Phase 1 — Read the issue

1. Pull the issue: `gh issue view <N> --comments`. Save any attached
   screenshots locally with `gh issue view <N> --json body -q .body` →
   extract the user-attachments URL → `curl -L -o /tmp/issue-<N>.png <url>`,
   then read it. Screenshots almost always point straight at the affected
   component. Download every screenshot — the body screenshot and the
   comment screenshots can show different things.
2. **Check whether the issue body has already been addressed.** Run
   `gh issue view <N> --json closedByPullRequestsReferences` and
   `git log --oneline -- <suspected-file>`. If a recent PR claims to close
   this issue and the issue is still open with new comments, the **comment
   is the real bug** — the body has already shipped, and the reporter is
   re-scoping. Read the comment's text + screenshot before trusting the
   body's "Proposed change" section.
3. Note the platform: desktop / iOS Safari / iOS Chrome / Android. Mobile
   issues need different repro tooling than desktop.
4. Note the gesture or sequence: "click A then B then A", "scroll to
   bottom", "open both menus". The exact sequence is the repro recipe.

## Phase 2 — Diagnose from the code (don't skip this)

The point of this phase is to get from "vague report" to "concrete
hypothesis about which file/function is wrong" without asking the reporter
anything.

For a UI bug:

- Use `Grep` for strings from the screenshot (button labels, headings,
  i18n keys).
- Use `Grep` for the i18n key if the report mentions one
  (`home.welcomeNamed`, `nav.admin`, etc.) → trace which component reads
  it. If the key has multiple variants per locale, also read the bundle
  files under `frontend/src/i18n/locales/` so you don't miss a translation
  that diverges from English.
- Read the suspect component end-to-end. Don't just skim — UI bugs are
  almost always state-management or layout issues that need the full
  component model in your head.
- For mobile-specific bugs, check the component for: `position: fixed`,
  `100vh` (broken on iOS Safari — should be `100dvh`), `overflow: hidden`,
  pointer-event handlers, `useDisclosure` toggles, scroll containers, and
  Mantine `Drawer` / `NavLink` `opened` state.

For a backend bug:

- Trace from route → service → model. The CLAUDE.md "App configuration"
  and "RBAC contract" sections explain how the most load-bearing pieces
  are wired.
- Check Alembic migrations for the column shape if the bug touches the DB.

After this phase you should be able to write a one-paragraph hypothesis:
"the bug is that `<Component>` does X when it should do Y, because
`<file:line>` does Z." If you cannot, try harder before falling back to
Phase 2b.

### Phase 2b — Reproduce locally (when the hypothesis isn't obvious)

- Desktop UI: bring up the dev stack (`make up-dev`) and click through the
  reported sequence in a browser.
- Mobile UI: use Playwright with a mobile device profile (iPhone 14, Pixel
  7) — see existing specs for the pattern. This catches *most* mobile
  layout bugs but **not all**: iOS Safari has unique overscroll, viewport,
  and `100vh` behaviour that Chromium DevTools does not emulate. If
  Playwright mobile emulation does not reproduce, that is itself a strong
  signal the bug is iOS-specific (overscroll bounce, dynamic toolbar,
  `100vh` vs `100dvh`).

### Phase 2c — Last resort: ask the reporter

Only after Phase 2 + 2b have failed to produce a hypothesis. When you do
ask:

- Ask **specific, falsifiable questions**, not "please provide more
  information". Bad: "can you give me steps to reproduce?". Good: "is this
  on iOS 17 or 18? Are you in the home-screen PWA or in the Safari tab? Did
  the scroll-jump happen at the bottom of the page or only when a menu was
  also open?"
- Lead with your current hypothesis so they can confirm or refute: "I
  suspect this is the iOS Safari dynamic toolbar resizing the viewport at
  the bottom of the page — does the jump happen even when the toolbar is
  already collapsed?"
- Use `gh issue comment <N> --body "$(cat <<'EOF' ... EOF)"` so the comment
  formats correctly.

## Phase 3 — Fix the root cause

- Fix the underlying problem. Do not patch the symptom (e.g. don't `try /
  except` an exception you should be preventing; don't `pointer-events:
  none` something whose state machine is wrong).
- Stay narrow. A bug fix is not a refactor — touch only what's needed. The
  CLAUDE.md preamble is explicit about this.
- For UI bugs in shared components (`AppLayout`, `RequireAuth`,
  `ThemedApp`), trace every caller before changing the contract.
- Watch out for the failure modes listed in CLAUDE.md "Things to remember"
  — many bugs are repeats of those.

## Phase 4 — Add a regression test

Every fix gets a test that would have caught the bug:

- Backend: a `pytest` case under `backend/tests/` exercising the route or
  service. The autouse fixtures in `conftest.py` reset RBAC and
  `app_settings` between tests — use them, don't reinvent them.
- Frontend logic: a Vitest spec.
- UI flows: a Playwright spec under `frontend/tests-e2e/`. For mobile bugs,
  add a spec that uses a mobile device profile so it runs in
  `make smoke-extended`.

If a regression test is genuinely impractical (true iOS-only quirks), say
so explicitly in the PR description rather than skipping silently.

## Phase 5 — Verify before declaring done

For backend changes:

```sh
cd backend && uv run pytest
```

For frontend changes (run inside the dev web container — pnpm's virtual
store does not expose binaries on the host):

```sh
docker compose -f docker-compose.dev.yml exec web node_modules/.bin/tsc --noEmit
docker compose -f docker-compose.dev.yml exec web node_modules/.bin/vitest run
```

For anything touching auth / app shell / login / admin sidebar:

```sh
make smoke
```

Use `make ci-wait` / `make release-wait` to watch CI rather than `gh run
watch --exit-status` — the wrappers re-check `gh run view` because the
plain command can return 0 on a failed multi-job run.

## Phase 6 — Open the PR

- Branch name: concrete and specific, no prefix, under 30 characters
  (e.g. `mobile-sidebar-toggle`, not `fix/issue-102-bugfix`).
- PR title under 70 chars, body has a Summary + Test plan.
- Link the issue with `Closes #N` so it auto-closes on merge.
- Hand-write the PR body — don't paste the issue back. Explain the root
  cause in one or two sentences and what specifically changed.
- Never add Co-Authored-By or "Generated with Claude Code" lines.
- All commits are GPG-signed globally; don't pass `--no-gpg-sign`.

## Atrium-specific reminders

- **Mobile viewport**: iOS Safari uses a dynamic toolbar — `100vh` includes
  it at first paint, then collapses on scroll, causing layout shifts. Use
  `100dvh` (dynamic viewport height) for full-height containers.
- **Mantine `useDisclosure` / `NavLink` toggles**: the `opened` prop is
  controlled. If a parent collapses children when a sibling opens, make
  sure the close path resets state on the previously-open sibling — not
  just the new one.
- **Mantine v9 `<NavLink defaultOpened>` desync on iOS**: when a parent
  group is uncontrolled (`defaultOpened={…}`) and a sibling re-renders
  with a changed `defaultOpened`, the chevron and the `<Collapse>`
  content can desync under iOS WebKit — chevron flips closed but the
  children stay visible (issue #102). For any group that can be
  toggled-closed-then-reopened, prefer **controlled** `opened` +
  `onChange` backed by `useState<Record<string, boolean>>` keyed by the
  group's stable key.
- **Mobile drawer scroll**: `<AppShell.Navbar>` does not auto-scroll its
  contents. When expandable groups can push the navbar past viewport
  height, wrap the children in `<AppShell.Section grow component={ScrollArea}>`
  per the Mantine AppShell docs. iOS Safari's collapsing toolbar makes
  `100vh` overshoot, so combine with `100dvh` on any height containers.
- **Global overscroll**: iOS Safari rubber-bands the document by default
  and the dynamic toolbar adds further jump. Set
  `overscroll-behavior-y: none` on `html, body` in the root CSS to stop
  the bottom-of-page snap (issue #104).
- **The admin shell has TWO sidebar groups (Settings + Admin)** since
  v0.17. Bugs about "the menu" almost always need both groups checked,
  not just the obvious one. See `src/admin/sections.tsx` and
  `useAdminSectionItems` / `useSettingsSectionItems`.
- **`/users/me` cache**: TanStack Query `invalidateQueries` is not enough
  on logout — use `queryClient.clear()`. Bugs about "stuck logged-in
  state" are usually this.
- **`app_settings` namespaces leak between tests** unless the autouse
  fixture cleans them. If your test mutates a new namespace, add it to
  the cleanup list.
- **Maintenance flag has a 2-second cache.** Tests that flip it must call
  `maintenance.reset_cache()` or wait.
