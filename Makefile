.PHONY: help up down logs ps build rebuild migrate migration \
        seed-admin seed-super-admin dev-bootstrap \
        shell-api shell-db test test-backend test-frontend lint format \
        clean prod-build prod-up prod-down \
        smoke smoke-extended smoke-dev smoke-up smoke-down \
        smoke-hello smoke-hello-dev smoke-hello-down \
        web-install web-reinstall reset-test-state

COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml
COMPOSE_E2E := docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml
COMPOSE_PROD := docker compose -f docker-compose.yml

# Hello World example: dev = dev stack + example overlay + smoke-tick
# overlay; e2e = e2e stack + example overlay + smoke-tick + e2e overlay.
COMPOSE_HELLO_DEV := $(COMPOSE_DEV) \
    -f examples/hello-world/compose.yaml \
    -f examples/hello-world/compose.dev.yaml
COMPOSE_HELLO_E2E := $(COMPOSE_E2E) \
    -f examples/hello-world/compose.yaml \
    -f examples/hello-world/compose.dev.yaml \
    -f examples/hello-world/compose.e2e.yaml

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
	@echo ""
	@echo "  make shell-api          Shell into the api container"
	@echo "  make shell-db           MySQL shell"
	@echo ""
	@echo "  make test               Run all tests"
	@echo "  make test-backend       pytest + testcontainers"
	@echo "  make test-frontend      vitest (unit). Playwright lives in make smoke."
	@echo "  make lint               ruff + eslint"
	@echo "  make format             ruff format + prettier"
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
		curl -fsS http://localhost:8000/readyz > /dev/null 2>&1 && break; \
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
test-frontend:
	cd frontend && pnpm install --silent && pnpm test

# --- Lint / format ---
lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

format:
	cd backend && uv run ruff format .
	cd frontend && pnpm format

clean:
	$(COMPOSE_DEV) down -v --remove-orphans
	rm -rf backend/.pytest_cache backend/.ruff_cache frontend/node_modules frontend/dist

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
		curl -fsS http://localhost:8000/readyz > /dev/null && break; \
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
	cd frontend && E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_EMAIL_OTP_EMAIL=$(SMOKE_EMAIL_OTP_EMAIL) \
		E2E_EMAIL_OTP_PASSWORD=$(SMOKE_EMAIL_OTP_PASSWORD) \
		pnpm playwright test --project=smoke

# Runs both the ``smoke`` and ``extended`` Playwright projects against
# the e2e stack — the full pre-prune behaviour. Use before risky
# frontend changes; the PR-gating ``make smoke`` only runs the four
# golden-path specs.
smoke-extended: smoke-up
	cd frontend && E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
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
		curl -fsS http://localhost:8000/readyz > /dev/null && break; \
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
	cd frontend && pnpm install --silent
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

# Both dev and e2e atrium stacks bake the SPA with
# VITE_API_BASE_URL=http://localhost:8000 (no /api proxy on either
# variant's web container). Keep the host bundle aligned so its
# /hello/* fetches reach the api on :8000 and not the SPA-fallback
# index.html on :5173.
smoke-hello-build-bundle:
	cd examples/hello-world/frontend && pnpm install --frozen-lockfile=false --silent && \
		VITE_API_BASE_URL=http://localhost:8000 pnpm build

smoke-hello-dev: smoke-hello-build-bundle
	$(COMPOSE_HELLO_DEV) up -d --build api worker web mysql proxy hello-bundle
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/readyz > /dev/null && break; \
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
		E2E_COMPOSE_FILES='-f docker-compose.yml -f docker-compose.dev.yml -f examples/hello-world/compose.yaml -f examples/hello-world/compose.dev.yaml' \
		pnpm exec playwright test

smoke-hello: smoke-hello-build-bundle
	# Build the atrium-backend runtime image first so the example's
	# Dockerfile (FROM atrium-backend:latest) has something to extend.
	docker build -t atrium-backend:latest --target runtime backend
	# Build the host backend image (atrium-backend + pip install host pkg).
	docker build -t atrium-hello-backend:latest \
		--build-arg ATRIUM_BACKEND_IMAGE=atrium-backend:latest \
		-f examples/hello-world/backend/Dockerfile .
	$(COMPOSE_HELLO_E2E) up -d --build
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		curl -fsS http://localhost:8000/readyz > /dev/null && break; \
		sleep 2; \
	done
	$(COMPOSE_HELLO_E2E) exec -T api alembic upgrade head
	$(COMPOSE_HELLO_E2E) exec -T api alembic -c /opt/host_app/alembic.ini upgrade head
	$(COMPOSE_HELLO_E2E) exec -T api python -m app.scripts.seed_admin \
		--email "$(SMOKE_EMAIL)" --password "$(SMOKE_PASSWORD)" --full-name 'Smoke Admin' \
		--super-admin --totp-secret "$(SMOKE_TOTP_SECRET)"
	$(COMPOSE_HELLO_E2E) exec -T api python -m atrium_hello_world.scripts.seed_host_bundle "$(HELLO_BUNDLE_URL_E2E)"
	cd examples/hello-world/frontend && \
		E2E_ADMIN_EMAIL=$(SMOKE_EMAIL) \
		E2E_ADMIN_PASSWORD=$(SMOKE_PASSWORD) \
		E2E_ADMIN_TOTP_SECRET=$(SMOKE_TOTP_SECRET) \
		E2E_COMPOSE_FILES='-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml -f examples/hello-world/compose.yaml -f examples/hello-world/compose.dev.yaml -f examples/hello-world/compose.e2e.yaml' \
		CI=1 pnpm exec playwright test

smoke-hello-down:
	$(COMPOSE_HELLO_E2E) down -v --remove-orphans
	$(COMPOSE_HELLO_DEV) down -v --remove-orphans

# --- Prod ---
prod-build:
	$(COMPOSE_PROD) build

prod-up:
	$(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down
