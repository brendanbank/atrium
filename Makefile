# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

.PHONY: help up down logs ps build rebuild migrate migration \
        seed-admin seed-super-admin dev-bootstrap \
        shell-api shell-db test test-backend test-frontend lint format \
        frontend-typecheck preflight \
        release-bump release-wait release-notes ci-wait \
        clean clean-atrium prod-build prod-up prod-down \
        smoke smoke-extended smoke-dev smoke-up smoke-down \
        smoke-hello smoke-hello-dev smoke-hello-down smoke-hello-ghcr \
        dev-bootstrap-hello dev-bootstrap-hello-down \
        dev-bootstrap-hello-ghcr dev-bootstrap-hello-ghcr-down hello-smoke-env \
        smoke-hello-build-bundle-dev \
        web-install web-reinstall reset-test-state

COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml
COMPOSE_E2E := docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml
COMPOSE_PROD := docker compose -f docker-compose.yml

# Hello World example:
#   * dev — atrium dev stack + example dev overlay (bind-mounted host
#     code, sidecar nginx for the host bundle, fast tick).
#   * prod — example's self-contained compose.yaml (atrium-from-GHCR +
#     host extension built locally on top, single image, plain HTTP
#     on :8000). Used by both ``smoke-hello`` and ``smoke-hello-ghcr``;
#     the difference is which atrium image they resolve.
COMPOSE_HELLO_DEV := $(COMPOSE_DEV) \
    -f examples/hello-world/dev/compose.dev.yaml
COMPOSE_HELLO_PROD := docker compose -f examples/hello-world/compose.yaml

help:
	@echo "Atrium — common tasks"
	@echo ""
	@echo "  make up                 Start dev stack (MySQL + api + web + worker)"
	@echo "  make down               Stop dev stack"
	@echo "  make logs               Tail dev logs"
	@echo "  make ps                 Show dev containers"
	@echo "  make build              Build dev images"
	@echo "  make rebuild            Rebuild dev images from scratch"
	@echo "  make web-install        pnpm install inside the running web container"
	@echo "  make web-reinstall      Wipe node_modules volume and reinstall"
	@echo ""
	@echo "  make migrate            Run alembic upgrade head"
	@echo "  make migration m=…      Create new alembic revision (autogenerate)"
	@echo "  make seed-admin …       Create/reset bootstrap admin (email/password/name)"
	@echo "  make seed-super-admin … Same as seed-admin, plus the super_admin role"
	@echo "                          Optional: totp_secret=<base32> pre-enrolls TOTP"
	@echo "  make dev-bootstrap      Clean wipe + up + migrate + seed super_admin"
	@echo "                          with TOTP. Pulls credentials from 1Password"
	@echo "                          (item 'atrium dev', vault 'Private' by default;"
	@echo "                          override with OP_VAULT=… OP_ITEM=…). Copies"
	@echo "                          .env.example -> .env when .env is missing."
	@echo "  make reset-test-state   Truncate runtime tables (keeps users + auth + templates)"
	@echo "  make clean-atrium       Force-remove every atrium_* container, volume, and"
	@echo "                          network across ALL workspaces (not just this one)"
	@echo ""
	@echo "  make shell-api          Shell into the api container"
	@echo "  make shell-db           MySQL shell"
	@echo ""
	@echo "  make test               Run all tests"
	@echo "  make test-backend       pytest + testcontainers"
	@echo "  make test-frontend      vitest (unit). Playwright lives in make smoke."
	@echo "  make lint               ruff + eslint"
	@echo "  make format             ruff format + prettier"
	@echo "  make frontend-typecheck"
	@echo "                          tsc --noEmit on the frontend"
	@echo "  make preflight          Run every gate CI runs, locally, before pushing"
	@echo "                          a release branch. ~5 min — catches what would"
	@echo "                          otherwise cost a CI round-trip. RELEASING.md step 1."
	@echo ""
	@echo "  make release-bump V=X.Y.Z"
	@echo "                          Bump every version pin in lockstep, refresh"
	@echo "                          lockfiles, check for stale references."
	@echo "                          See RELEASING.md step 1.5."
	@echo "  make release-wait V=X.Y.Z"
	@echo "                          Block until publish-images.yml + publish-npm.yml"
	@echo "                          finish for the v\$$(V) tag. See step 8."
	@echo "  make ci-wait BR=<branch>"
	@echo "                          Block until ci.yml + codeql.yml + security.yml"
	@echo "                          finish for the named PR branch. Pre-merge sibling"
	@echo "                          of release-wait."
	@echo "  make release-notes V=X.Y.Z"
	@echo "                          Render .github/RELEASE_NOTES_TEMPLATE.md to"
	@echo "                          .context/release-notes-v\$$(V).md, pre-stubbed"
	@echo "                          with sections for each \`closes #N\` since the"
	@echo "                          previous tag. See step 9."
	@echo ""
	@echo "  make prod-build         Build prod images"
	@echo "  make prod-up            Start prod stack"
	@echo "  make prod-down          Stop prod stack"
	@echo ""
	@echo "  make smoke              Run the Playwright smoke project (4 specs)"
	@echo "                          against the e2e stack — mirrors CI"
	@echo "  make smoke-extended     Run the full Playwright suite (smoke + extended)"
	@echo "                          against the e2e stack"
	@echo "  make smoke-dev          Run the full Playwright suite against the dev stack"
	@echo "                          (vite + --reload api; stack stays up)"
	@echo ""
	@echo "  make smoke-hello-dev    Hello World example smoke against the dev stack."
	@echo "                          Builds the host bundle, layers the example overlay,"
	@echo "                          runs host alembic + seeds host_bundle_url, runs the"
	@echo "                          example's Playwright spec. Stack stays up."
	@echo "  make smoke-hello        Hello World example smoke against the e2e stack"
	@echo "                          (prod images + baked-in host backend image)."
	@echo "                          What CI runs."
	@echo "  make smoke-hello-down   Tear down the Hello World e2e stack."
	@echo "  make dev-bootstrap-hello"
	@echo "                          Hello World bootstrap on a locally-built atrium"
	@echo "                          image. Builds atrium-local:source, brings up the"
	@echo "                          example compose, runs atrium + host migrations,"
	@echo "                          seeds a super_admin from 1Password (item 'atrium"
	@echo "                          dev'). URL: http://localhost:8000."
	@echo "  make dev-bootstrap-hello-down  Tear down the local Hello World stack."

# --- Dev stack ---
up:
	$(COMPOSE_DEV) up -d

down:
	$(COMPOSE_DEV) down

logs:
	$(COMPOSE_DEV) logs -f --tail=100

ps:
	$(COMPOSE_DEV) ps

build:
	$(COMPOSE_DEV) build

rebuild:
	$(COMPOSE_DEV) build --no-cache

# After editing frontend/package.json, run this to sync deps inside the
# running web container without touching the node_modules volume.
web-install:
	$(COMPOSE_DEV) exec web pnpm install

# Wipes the node_modules volume and reinstalls from scratch.
web-reinstall:
	$(COMPOSE_DEV) stop web
	-docker volume rm atrium_frontend_node_modules
	$(COMPOSE_DEV) up -d web

# --- DB / migrations ---
migrate:
	$(COMPOSE_DEV) run --rm api alembic upgrade head

migration:
	@if [ -z "$(m)" ]; then echo "usage: make migration m='message'"; exit 1; fi
	$(COMPOSE_DEV) run --rm api alembic revision --autogenerate -m "$(m)"

seed-admin:
	@if [ -z "$(email)" ] || [ -z "$(password)" ] || [ -z "$(name)" ]; then \
		echo "usage: make seed-admin email=you@example.com password=secret123 name='Your Name'"; \
		exit 1; \
	fi
	$(COMPOSE_DEV) run --rm api python -m app.scripts.seed_admin \
		--email "$(email)" --password "$(password)" --full-name "$(name)"

# Same as seed-admin but also grants the 'super_admin' role — required
# for user.impersonate. The init migration grants super_admin to the
# first user the host app creates; on a fresh DB after wipe-and-reseed,
# this target re-establishes the privilege. Pass `totp_secret=<base32>`
# to also pre-enroll TOTP so a password manager (1Password etc.) holding
# the same secret can generate codes immediately.
seed-super-admin:
	@if [ -z "$(email)" ] || [ -z "$(password)" ] || [ -z "$(name)" ]; then \
		echo "usage: make seed-super-admin email=you@example.com password=secret123 name='Your Name' [totp_secret=BASE32]"; \
		exit 1; \
	fi
	$(COMPOSE_DEV) run --rm api python -m app.scripts.seed_admin \
		--email "$(email)" --password "$(password)" --full-name "$(name)" \
		--super-admin \
		$(if $(totp_secret),--totp-secret "$(totp_secret)",)

# --- Dev bootstrap: one-shot clean + up + migrate + seed super_admin ---
# Pulls the admin credentials (email + password + TOTP secret) from a
# 1Password login item via the `op` CLI, copies .env.example -> .env if
# .env is missing, wipes the dev stack, brings it back up, runs the
# migrations, and seeds the user as a super_admin with the TOTP
# pre-enrolled. The same TOTP secret is shared with 1Password so its
# Authenticator field generates valid codes immediately after seeding.
#
# Override OP_VAULT / OP_ITEM if your 1Password layout differs:
#   make dev-bootstrap OP_VAULT='Familie Bank' OP_ITEM='Atrium Dev'
#
# Override DEV_ADMIN_NAME if the full name on the seeded user should
# differ from the 1Password item title; default is the operator's name.
OP_VAULT ?= Private
OP_ITEM ?= atrium dev
DEV_ADMIN_NAME ?= Brendan Bank

dev-bootstrap:
	@command -v op >/dev/null 2>&1 || { \
		echo "1Password CLI not found. Install with: brew install 1password-cli"; \
		exit 1; \
	}
	@op account list >/dev/null 2>&1 || { \
		echo "1Password CLI is not signed in. Run: eval \$$(op signin)"; \
		exit 1; \
	}
	@if [ ! -f .env ]; then \
		echo "creating .env from .env.example"; \
		cp .env.example .env; \
	else \
		echo ".env exists; leaving it alone (delete it first to re-copy from .env.example)"; \
	fi
	$(MAKE) clean
	$(MAKE) up
	@echo "waiting for api /readyz..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null 2>&1 && break; \
		sleep 2; \
	done
	$(MAKE) migrate
	@set -eu; \
	echo "fetching admin credentials from 1Password (vault='$(OP_VAULT)', item='$(OP_ITEM)')..."; \
	EMAIL=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields label=username); \
	PASSWORD=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields label=password --reveal); \
	TOTP_SECRET=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields type=otp --format=json \
		| python3 -c "import json,sys; print(json.load(sys.stdin)['value'])"); \
	if [ -z "$$EMAIL" ] || [ -z "$$PASSWORD" ] || [ -z "$$TOTP_SECRET" ]; then \
		echo "missing field in 1Password item '$(OP_ITEM)' (need username + password + OTP)"; exit 1; \
	fi; \
	$(COMPOSE_DEV) run --rm api python -m app.scripts.seed_admin \
		--email "$$EMAIL" \
		--password "$$PASSWORD" \
		--full-name "$(DEV_ADMIN_NAME)" \
		--super-admin --totp-secret "$$TOTP_SECRET"; \
	echo ""; \
	echo "dev environment ready:"; \
	echo "  email:       $$EMAIL"; \
	echo "  password:    (from 1Password '$(OP_ITEM)')"; \
	echo "  totp secret: (from 1Password '$(OP_ITEM)' -> Authenticator)"; \
	echo "  url:         http://localhost:5173"

# --- Shells ---
shell-api:
	$(COMPOSE_DEV) exec api bash

shell-db:
	$(COMPOSE_DEV) exec mysql sh -c 'mysql -u"$$MYSQL_USER" -p"$$MYSQL_PASSWORD" "$$MYSQL_DATABASE"'

# --- Tests ---
test: test-backend test-frontend

# testcontainers-python probes /var/run/docker.sock by default, but
# Docker Desktop on macOS puts the socket at ~/.docker/run/docker.sock.
# Detect which one exists and point DOCKER_HOST at it.
DOCKER_SOCK := $(shell \
	if [ -S /var/run/docker.sock ]; then echo /var/run/docker.sock; \
	elif [ -S $$HOME/.docker/run/docker.sock ]; then echo $$HOME/.docker/run/docker.sock; \
	fi)

test-backend:
	cd backend && DOCKER_HOST=unix://$(DOCKER_SOCK) uv run pytest

# Vitest only. Playwright lives in `make smoke` because it needs the
# whole stack booted + a seeded admin + a fixed TOTP secret.
#
# `--ignore-workspace` is required because the repo root carries a
# `pnpm-workspace.yaml` for the host SDK packages (`packages/*`,
# `examples/hello-world/frontend`). Atrium's main SPA under
# `frontend/` is intentionally NOT a workspace member — it ships as a
# standalone package with its own `pnpm-lock.yaml` so the Dockerfile's
# `COPY frontend/package.json frontend/pnpm-lock.yaml*` continues to
# work. Without the flag, `cd frontend && pnpm install` walks up to
# the workspace root and skips `frontend/` entirely.
test-frontend:
	cd frontend && pnpm install --ignore-workspace --silent && pnpm test

# Vitest covers runtime behaviour; tsc covers shape. Both are wanted
# in pre-flight, neither alone is sufficient.
frontend-typecheck:
	cd frontend && pnpm typecheck

# --- Lint / format ---
lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

format:
	cd backend && uv run ruff format .
	cd frontend && pnpm format

# --- Pre-flight (RELEASING.md step 1) ---
#
# Run every gate CI runs, locally, before pushing the release branch.
# A failed CI round-trip costs ~5 min on GHA; the same failure here
# costs as long as the offending suite — usually seconds. Catches the
# mistakes ``make ci-wait`` would otherwise catch only after push.
#
# Order matters for the smoke gates: ``smoke`` and ``smoke-hello``
# share named docker volumes (atrium_mysql_data, atrium_proxy_certs,
# atrium_frontend_node_modules), so the second one stomps on the
# first if its stack is still up. Tear down between them.
#
# Defensive teardown: if ``smoke`` or ``smoke-hello`` fails, capture
# the exit, run the ``-down`` target anyway, then propagate the
# original exit. Without this a flaky red leaves containers
# accumulating across retries.
preflight:
	$(MAKE) test-backend
	$(MAKE) test-frontend
	$(MAKE) frontend-typecheck
	$(MAKE) lint
	$(MAKE) smoke || (s=$$?; $(MAKE) smoke-down; exit $$s)
	$(MAKE) smoke-down
	$(MAKE) smoke-hello || (s=$$?; $(MAKE) smoke-hello-down; exit $$s)
	$(MAKE) smoke-hello-down
	@echo
	@echo "preflight: all gates green. safe to push."

# --- Release ---
#
# The mechanical parts of cutting a release (version bumps + lockfile
# refresh + doc sweep + release-notes scaffold) all live in scripts/.
# These targets are thin wrappers so the maintainer flow is:
#
#   make release-bump V=0.16.0   # mutate the tree
#   git diff                     # eyeball
#   git add … && git commit
#   git push -u origin <branch>
#   gh pr create … && gh pr merge --squash
#   git tag -s vX.Y.Z <sha> && git push origin vX.Y.Z
#   make release-wait V=0.16.0   # block on publish-images + publish-npm
#   make release-notes V=0.16.0  # write .context/release-notes-vX.Y.Z.md
#   gh release create vX.Y.Z --notes-file .context/…
#
# See RELEASING.md for the full procedure (this captures step 1.5 + 8 + 9).

# Bump every version pin in lockstep, refresh both lockfiles, then verify
# nothing stale is left. Idempotent — re-running with the same V is safe.
release-bump:
	@test -n "$(V)" || (echo "Usage: make release-bump V=X.Y.Z"; exit 64)
	./scripts/bump-version.sh $(V)
	cd backend && uv lock --quiet
	pnpm install --lockfile-only
	./scripts/check-stale-versions.sh $(V)
	@echo
	@echo "Bumped to $(V). Next:"
	@echo "  - add a row to docs/compat-matrix.md"
	@echo "  - git diff           # review"
	@echo "  - git add … && git commit"

# Block until both publish-images.yml and publish-npm.yml finish for
# the named tag. Replaces the dance of two parallel ``gh run watch``.
# Exits non-zero if either workflow failed; safe to re-run.
release-wait:
	@test -n "$(V)" || (echo "Usage: make release-wait V=X.Y.Z"; exit 64)
	./scripts/wait-publish.sh v$(V)

# Block until the pre-merge CI workflows (ci.yml, codeql.yml,
# security.yml) finish for the named branch. Same exit-status
# semantics as release-wait, sharing the underlying wait-runs.sh.
# Symmetric with release-wait — pre-merge is to PR what
# post-tag is to publish.
ci-wait:
	@test -n "$(BR)" || (echo "Usage: make ci-wait BR=<branch-name>"; exit 64)
	./scripts/wait-ci.sh $(BR)

# Render .github/RELEASE_NOTES_TEMPLATE.md with the current version's
# substitutions and pre-stub one section per ``closes #N`` referenced
# in commits since the previous tag. Writes to .context/ (gitignored)
# so the maintainer fills in the per-issue prose, then passes the file
# to ``gh release create --notes-file``.
release-notes:
	@test -n "$(V)" || (echo "Usage: make release-notes V=X.Y.Z"; exit 64)
	./scripts/release-notes.sh v$(V)

clean:
	$(COMPOSE_DEV) down -v --remove-orphans
	rm -rf backend/.pytest_cache backend/.ruff_cache frontend/node_modules frontend/dist

# Cross-workspace cleanup. The compose files explicitly name volumes
# (atrium_mysql_data, atrium_proxy_certs, atrium_frontend_node_modules)
# and networks (atrium_edge, atrium_internal) with an atrium_ prefix,
# so they're shared across every Conductor workspace. `make clean`
# only detaches the current compose project — this target nukes the
# shared resources outright, including any container from any
# workspace still attached to them.
clean-atrium:
	@echo "force-removing containers attached to atrium_* networks/volumes..."
	@CIDS=$$( { \
	    docker ps -aq --filter "network=atrium_edge"; \
	    docker ps -aq --filter "network=atrium_internal"; \
	    docker ps -aq --filter "volume=atrium_mysql_data"; \
	    docker ps -aq --filter "volume=atrium_proxy_certs"; \
	    docker ps -aq --filter "volume=atrium_frontend_node_modules"; \
	  } | sort -u); \
	if [ -n "$$CIDS" ]; then docker rm -f $$CIDS; else echo "  (none)"; fi
	@echo "removing atrium_* volumes..."
	@VOLS=$$(docker volume ls -q --filter "name=^atrium_"); \
	if [ -n "$$VOLS" ]; then docker volume rm $$VOLS; else echo "  (none)"; fi
	@echo "removing atrium_* networks..."
	@NETS=$$(docker network ls --format '{{.Name}}' --filter "name=^atrium_"); \
	if [ -n "$$NETS" ]; then docker network rm $$NETS; else echo "  (none)"; fi

# --- Smoke (mirrors CI) ---
SMOKE_EMAIL := admin@example.com
SMOKE_PASSWORD := smoke-pw-12345
# Fixed TOTP secret so Playwright can compute valid codes without a real
# authenticator. Not a credential — the smoke admin exists only inside
# the e2e DB.
SMOKE_TOTP_SECRET := JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP
# Second smoke user pre-enrolled with email-OTP (no TOTP) so the
# email-otp.spec can drive the "receive a code by email" challenge.
SMOKE_EMAIL_OTP_EMAIL := email-otp-admin@example.com
SMOKE_EMAIL_OTP_PASSWORD := email-otp-pw-12345

smoke-up:
	$(COMPOSE_E2E) up -d --build
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_E2E) run --rm api alembic upgrade head
	$(COMPOSE_E2E) run --rm api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL)" --password "$(SMOKE_PASSWORD)" --full-name 'Smoke Admin' \
		--super-admin --totp-secret "$(SMOKE_TOTP_SECRET)"
	$(COMPOSE_E2E) run --rm api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL_OTP_EMAIL)" --password "$(SMOKE_EMAIL_OTP_PASSWORD)" \
		--full-name 'Email-OTP Smoke Admin' --email-otp

smoke-down:
	$(COMPOSE_E2E) down -v

smoke: smoke-up
	cd frontend && E2E_BASE_URL=http://localhost:8000 \
		E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_EMAIL_OTP_EMAIL=$(SMOKE_EMAIL_OTP_EMAIL) \
		E2E_EMAIL_OTP_PASSWORD=$(SMOKE_EMAIL_OTP_PASSWORD) \
		pnpm playwright test --project=smoke

# Runs both the ``smoke`` and ``extended`` Playwright projects against
# the e2e stack — the full pre-prune behaviour. Use before risky
# frontend changes; the PR-gating ``make smoke`` only runs the four
# golden-path specs.
smoke-extended: smoke-up
	cd frontend && E2E_BASE_URL=http://localhost:8000 \
		E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_EMAIL_OTP_EMAIL=$(SMOKE_EMAIL_OTP_EMAIL) \
		E2E_EMAIL_OTP_PASSWORD=$(SMOKE_EMAIL_OTP_PASSWORD) \
		pnpm playwright test

# Truncate runtime tables so smoke-dev starts from a known-empty state.
# Preserves users + auth + email_templates + permissions/roles so the
# smoke admins and TOTP enrolments survive. Mirrors the conftest
# truncate-list used between backend tests.
reset-test-state:
	$(COMPOSE_DEV) exec -T mysql sh -c 'mysql -uroot -p"$$MYSQL_ROOT_PASSWORD" -D"$$MYSQL_DATABASE" -e "SET FOREIGN_KEY_CHECKS=0; TRUNCATE TABLE scheduled_jobs; TRUNCATE TABLE notifications; TRUNCATE TABLE audit_log; TRUNCATE TABLE email_log; SET FOREIGN_KEY_CHECKS=1;"'

# Run the Playwright suite against the running dev stack (vite dev
# server, api with --reload, bind-mounted source).
smoke-dev:
	$(COMPOSE_DEV) build api worker web
	$(COMPOSE_DEV) up -d --force-recreate api worker web
	$(COMPOSE_DEV) up -d mysql proxy
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null && break; \
		sleep 2; \
	done
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		curl -fsS http://localhost:5173/ > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_DEV) exec -T api alembic upgrade head
	$(COMPOSE_DEV) exec -T api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL)" --password "$(SMOKE_PASSWORD)" --full-name 'Smoke Admin' \
		--super-admin --totp-secret "$(SMOKE_TOTP_SECRET)"
	$(COMPOSE_DEV) exec -T api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL_OTP_EMAIL)" --password "$(SMOKE_EMAIL_OTP_PASSWORD)" \
		--full-name 'Email-OTP Smoke Admin' --email-otp
	$(MAKE) reset-test-state
	# Playwright runs on the host, not in the web container — the dev
	# container is on node:22-alpine (musl libc) and Playwright's
	# chromium binary is glibc-only. Idempotent no-op when already done.
	cd frontend && pnpm install --ignore-workspace --silent
	cd frontend && pnpm exec playwright install chromium --with-deps 2>/dev/null \
		|| pnpm exec playwright install chromium
	cd frontend && E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_EMAIL_OTP_EMAIL=$(SMOKE_EMAIL_OTP_EMAIL) \
		E2E_EMAIL_OTP_PASSWORD=$(SMOKE_EMAIL_OTP_PASSWORD) \
		E2E_COMPOSE_FILES='-f docker-compose.yml -f docker-compose.dev.yml' \
		pnpm exec playwright test

# --- Hello World example smoke ---
#
# Two entry points mirroring smoke-dev / smoke:
#  * smoke-hello-dev  → dev stack, bind-mounted host package, fast iteration
#  * smoke-hello      → e2e stack, host backend image baked, what CI runs
#
# Both build the host frontend bundle into examples/hello-world/frontend/dist
# (mounted into atrium's web container at /host so the SPA can dynamic-import
# /host/main.js), bring the stack up, run atrium + host migrations,
# seed the smoke admin, write system.host_bundle_url, then drive the
# Playwright spec from examples/hello-world/frontend.

# Reused from the generic smoke setup so the same admin + TOTP secret
# work across both atrium and the example.
#
# Bundle URL differs by overlay:
#   * dev — sidecar nginx on a separate port, cross-origin URL.
#     Vite's dev server rewrites public/ dynamic-imports with
#     ?import and tries to transform them, so we can't piggy-back
#     on atrium's web container in dev.
#   * e2e — atrium's prod nginx serves /host/main.js directly from a
#     bind-mounted dist (compose.e2e.yaml), same-origin, no CORS.
HELLO_BUNDLE_URL_DEV := http://localhost:5174/main.js
HELLO_BUNDLE_URL_E2E := /host/main.js

# The dev variant bind-mounts the host backend and serves the prebuilt
# host bundle from a sidecar nginx on :5174 (Vite dev server can't
# serve a prebuilt module cleanly — it tries to transform it as
# source). The host-bundle URL must point at that sidecar so the SPA's
# dynamic import resolves.
smoke-hello-build-bundle-dev:
	# `pnpm install` runs from the example dir but the workspace marker
	# at the repo root causes it to install the whole workspace
	# (`packages/*` + this example). The SDK packages must be built
	# *before* the example's vite runs — the example imports from
	# `@brendanbank/atrium-host-bundle-utils/vite`, which resolves
	# through the workspace symlink to `packages/host-bundle-utils/dist/`.
	# Without the build step, that dist directory is empty and vite
	# errors out at config load.
	cd examples/hello-world/frontend && pnpm install --frozen-lockfile=false --silent
	pnpm -r --filter './packages/*' build
	cd examples/hello-world/frontend && VITE_API_BASE_URL=http://localhost:8000/api pnpm build

smoke-hello-dev: smoke-hello-build-bundle-dev
	$(COMPOSE_HELLO_DEV) up -d --build api worker web mysql proxy hello-bundle
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null && break; \
		sleep 2; \
	done
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		curl -fsS http://localhost:5173/ > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_HELLO_DEV) exec -T api alembic upgrade head
	$(COMPOSE_HELLO_DEV) exec -T api alembic -c /host_app/alembic.ini upgrade head
	$(COMPOSE_HELLO_DEV) exec -T api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL)" --password "$(SMOKE_PASSWORD)" --full-name 'Smoke Admin' \
		--super-admin --totp-secret "$(SMOKE_TOTP_SECRET)"
	$(COMPOSE_HELLO_DEV) exec -T api python -m atrium_hello_world.scripts.seed_host_bundle "$(HELLO_BUNDLE_URL_DEV)"
	cd examples/hello-world/frontend && pnpm exec playwright install chromium 2>/dev/null \
		|| pnpm exec playwright install chromium
	cd examples/hello-world/frontend && \
		E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) \
		E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_COMPOSE_FILES='-f docker-compose.yml -f docker-compose.dev.yml -f examples/hello-world/dev/compose.dev.yaml' \
		pnpm exec playwright test

# The prod variant builds the unified atrium-hello-world image (one
# image, atrium + host backend pkg + host bundle baked in), runs it
# from the example's self-contained compose.yaml on plain HTTP :8000,
# and points Playwright at the same origin (api serves both API and
# SPA). Used by both ``smoke-hello`` (atrium built locally) and
# ``smoke-hello-ghcr`` (atrium pulled from GHCR).
# Write to .env (not .smoke.env) so compose auto-loads it from the
# project directory for every subsequent `docker compose ... exec`
# call — `--env-file` only applies to the single command it's passed
# to, so reaching for it forces every later call to thread the same
# flag through. Auto-loading is simpler and matches what a developer
# would have on disk during the demo. Removed by smoke-hello-down.
HELLO_SMOKE_ENV := examples/hello-world/.env

# Write a smoke-specific env file so the example's compose.yaml has
# deterministic secrets without touching whatever the developer has in
# .env. Idempotent; safe to call between runs.
#
# Wrapped in a single ``{ ...; } > $@`` so the whole block runs in one
# shell invocation — Make recipes execute one shell per line by default,
# and a heredoc opened on line 1 closes immediately, leaving the body
# lines to be executed as commands (which then fails on values
# containing spaces like "Atrium Hello World").
hello-smoke-env:
	@{ \
	  echo 'ENVIRONMENT=dev'; \
	  echo 'APP_TIMEZONE=UTC'; \
	  echo 'APP_SECRET_KEY=smoke-secret-do-not-use-in-prod'; \
	  echo 'APP_BASE_URL=http://localhost:8000'; \
	  echo 'MYSQL_ROOT_PASSWORD=smoke-root-pw'; \
	  echo 'MYSQL_DATABASE=atrium'; \
	  echo 'MYSQL_USER=atrium'; \
	  echo 'MYSQL_PASSWORD=smoke-pw'; \
	  echo 'DATABASE_URL=mysql+aiomysql://atrium:smoke-pw@mysql:3306/atrium'; \
	  echo 'JWT_SECRET=smoke-jwt-secret-do-not-use-in-prod'; \
	  echo 'JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080'; \
	  echo 'WEBAUTHN_RP_ID=localhost'; \
	  echo 'WEBAUTHN_RP_NAME=Atrium Hello World'; \
	  echo 'WEBAUTHN_ORIGIN=http://localhost:8000'; \
	  echo 'MAIL_BACKEND=console'; \
	  echo 'MAIL_FROM=no-reply@example.com'; \
	  echo 'HELLO_TICK_SECONDS=2'; \
	} > $(HELLO_SMOKE_ENV)

smoke-hello: hello-smoke-env
	# Build the atrium runtime image locally so the example Dockerfile
	# (FROM atrium-hello-world:source) has something to extend without
	# pulling from GHCR.
	docker build -t atrium-local:source --target runtime .
	ATRIUM_IMAGE=atrium-local:source $(COMPOSE_HELLO_PROD) up -d --build
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_HELLO_PROD) exec -T api alembic upgrade head
	$(COMPOSE_HELLO_PROD) exec -T api alembic -c /opt/host_app/alembic.ini upgrade head
	$(COMPOSE_HELLO_PROD) exec -T api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL)" --password "$(SMOKE_PASSWORD)" --full-name 'Smoke Admin' \
		--super-admin --totp-secret "$(SMOKE_TOTP_SECRET)"
	$(COMPOSE_HELLO_PROD) exec -T api python -m atrium_hello_world.scripts.seed_host_bundle "$(HELLO_BUNDLE_URL_E2E)"
	# pnpm install + chromium are needed because the host bundle is now
	# baked inside the Dockerfile; the frontend dir's dependencies are
	# only used by Playwright. Idempotent on warm caches.
	cd examples/hello-world/frontend && pnpm install --silent
	cd examples/hello-world/frontend && pnpm exec playwright install chromium 2>/dev/null \
		|| pnpm exec playwright install chromium
	cd examples/hello-world/frontend && \
		E2E_BASE_URL=http://localhost:8000 \
		E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) \
		E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_COMPOSE_FILES='-f compose.yaml' \
		E2E_COMPOSE_CWD='..' \
		CI=1 pnpm exec playwright test

smoke-hello-down:
	$(COMPOSE_HELLO_PROD) down -v --remove-orphans
	$(COMPOSE_HELLO_DEV) down -v --remove-orphans
	rm -f $(HELLO_SMOKE_ENV)

# --- Hello World bootstrap (local atrium build) ---
# Same shape as ``dev-bootstrap-hello-ghcr`` but resolves the atrium
# runtime from a local ``docker build`` instead of pulling from GHCR.
# Useful when iterating on atrium itself and you want the example
# extension layered on top of your in-tree changes.
dev-bootstrap-hello: hello-smoke-env
	@command -v op >/dev/null 2>&1 || { \
		echo "1Password CLI not found. Install with: brew install 1password-cli"; \
		exit 1; \
	}
	@op account list >/dev/null 2>&1 || { \
		echo "1Password CLI is not signed in. Run: eval \$$(op signin)"; \
		exit 1; \
	}
	docker build -t atrium-local:source --target runtime .
	ATRIUM_IMAGE=atrium-local:source $(COMPOSE_HELLO_PROD) up -d --build
	@echo "waiting for api /readyz..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_HELLO_PROD) exec -T api alembic upgrade head
	$(COMPOSE_HELLO_PROD) exec -T api alembic -c /opt/host_app/alembic.ini upgrade head
	@set -eu; \
	echo "fetching admin credentials from 1Password (vault='$(OP_VAULT)', item='$(OP_ITEM)')..."; \
	EMAIL=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields label=username); \
	PASSWORD=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields label=password --reveal); \
	TOTP_SECRET=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields type=otp --format=json \
		| python3 -c "import json,sys; print(json.load(sys.stdin)['value'])"); \
	if [ -z "$$EMAIL" ] || [ -z "$$PASSWORD" ] || [ -z "$$TOTP_SECRET" ]; then \
		echo "missing field in 1Password item '$(OP_ITEM)' (need username + password + OTP)"; exit 1; \
	fi; \
	$(COMPOSE_HELLO_PROD) exec -T api python -m app.scripts.seed_admin \
		--email "$$EMAIL" \
		--password "$$PASSWORD" \
		--full-name "$(DEV_ADMIN_NAME)" \
		--super-admin --totp-secret "$$TOTP_SECRET"; \
	$(COMPOSE_HELLO_PROD) exec -T api python -m atrium_hello_world.scripts.seed_host_bundle "$(HELLO_BUNDLE_URL_E2E)"; \
	echo ""; \
	echo "hello-world (local atrium image) ready:"; \
	echo "  email:       $$EMAIL"; \
	echo "  password:    (from 1Password '$(OP_ITEM)')"; \
	echo "  totp secret: (from 1Password '$(OP_ITEM)' -> Authenticator)"; \
	echo "  url:         http://localhost:8000"

dev-bootstrap-hello-down:
	$(COMPOSE_HELLO_PROD) down -v --remove-orphans
	rm -f $(HELLO_SMOKE_ENV)

# --- Hello World against published GHCR images ---
# Same self-contained example compose.yaml as ``smoke-hello`` and
# ``dev-bootstrap-hello`` — the only difference is that ATRIUM_IMAGE
# points at the published ghcr.io/brendanbank/atrium tag instead of a
# locally-built one. Faithful test of the published-image extension
# model.
ATRIUM_GHCR_VERSION ?= latest
ATRIUM_GHCR_IMAGE := ghcr.io/brendanbank/atrium:$(ATRIUM_GHCR_VERSION)

dev-bootstrap-hello-ghcr: hello-smoke-env
	@command -v op >/dev/null 2>&1 || { \
		echo "1Password CLI not found. Install with: brew install 1password-cli"; \
		exit 1; \
	}
	@op account list >/dev/null 2>&1 || { \
		echo "1Password CLI is not signed in. Run: eval \$$(op signin)"; \
		exit 1; \
	}
	@gh auth token | docker login ghcr.io -u brendanbank --password-stdin >/dev/null 2>&1 || { \
		echo "docker login to ghcr.io failed (gh auth required for private images)"; exit 1; \
	}
	docker pull $(ATRIUM_GHCR_IMAGE)
	ATRIUM_IMAGE=$(ATRIUM_GHCR_IMAGE) $(COMPOSE_HELLO_PROD) up -d --build
	@echo "waiting for api /readyz..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_HELLO_PROD) exec -T api alembic upgrade head
	$(COMPOSE_HELLO_PROD) exec -T api alembic -c /opt/host_app/alembic.ini upgrade head
	@set -eu; \
	echo "fetching admin credentials from 1Password (vault='$(OP_VAULT)', item='$(OP_ITEM)')..."; \
	EMAIL=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields label=username); \
	PASSWORD=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields label=password --reveal); \
	TOTP_SECRET=$$(op item get "$(OP_ITEM)" --vault "$(OP_VAULT)" --fields type=otp --format=json \
		| python3 -c "import json,sys; print(json.load(sys.stdin)['value'])"); \
	if [ -z "$$EMAIL" ] || [ -z "$$PASSWORD" ] || [ -z "$$TOTP_SECRET" ]; then \
		echo "missing field in 1Password item '$(OP_ITEM)' (need username + password + OTP)"; exit 1; \
	fi; \
	$(COMPOSE_HELLO_PROD) exec -T api python -m app.scripts.seed_admin \
		--email "$$EMAIL" \
		--password "$$PASSWORD" \
		--full-name "$(DEV_ADMIN_NAME)" \
		--super-admin --totp-secret "$$TOTP_SECRET"; \
	$(COMPOSE_HELLO_PROD) exec -T api python -m atrium_hello_world.scripts.seed_host_bundle "$(HELLO_BUNDLE_URL_E2E)"; \
	echo ""; \
	echo "hello-world (GHCR images) ready:"; \
	echo "  email:       $$EMAIL"; \
	echo "  password:    (from 1Password '$(OP_ITEM)')"; \
	echo "  totp secret: (from 1Password '$(OP_ITEM)' -> Authenticator)"; \
	echo "  url:         http://localhost:8000"

dev-bootstrap-hello-ghcr-down:
	$(COMPOSE_HELLO_PROD) down -v --remove-orphans

smoke-hello-ghcr: hello-smoke-env
	@gh auth token | docker login ghcr.io -u brendanbank --password-stdin >/dev/null 2>&1 || { \
		echo "docker login to ghcr.io failed (gh auth required for private images)"; exit 1; \
	}
	docker pull $(ATRIUM_GHCR_IMAGE)
	ATRIUM_IMAGE=$(ATRIUM_GHCR_IMAGE) $(COMPOSE_HELLO_PROD) up -d --build
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/api/readyz > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_HELLO_PROD) exec -T api alembic upgrade head
	$(COMPOSE_HELLO_PROD) exec -T api alembic -c /opt/host_app/alembic.ini upgrade head
	$(COMPOSE_HELLO_PROD) exec -T api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL)" --password "$(SMOKE_PASSWORD)" --full-name 'Smoke Admin' \
		--super-admin --totp-secret "$(SMOKE_TOTP_SECRET)"
	$(COMPOSE_HELLO_PROD) exec -T api python -m atrium_hello_world.scripts.seed_host_bundle "$(HELLO_BUNDLE_URL_E2E)"
	cd examples/hello-world/frontend && pnpm install --silent
	cd examples/hello-world/frontend && pnpm exec playwright install chromium 2>/dev/null \
		|| pnpm exec playwright install chromium
	cd examples/hello-world/frontend && \
		E2E_BASE_URL=http://localhost:8000 \
		E2E_API_URL=http://localhost:8000/api \
		E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) \
		E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_COMPOSE_FILES='-f compose.yaml' \
		E2E_COMPOSE_CWD='..' \
		CI=1 pnpm exec playwright test

# --- Prod ---
prod-build:
	$(COMPOSE_PROD) build

prod-up:
	$(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down
