.PHONY: help up down logs ps build rebuild migrate migration \
        seed-admin seed-super-admin \
        shell-api shell-db test test-backend test-frontend lint format \
        clean prod-build prod-up prod-down smoke smoke-dev smoke-up smoke-down \
        web-install web-reinstall reset-test-state

COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml
COMPOSE_E2E := docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml
COMPOSE_PROD := docker compose -f docker-compose.yml

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
	@echo "  make smoke              Run Playwright against the e2e stack"
	@echo "                          (prod web image; mirrors CI)"
	@echo "  make smoke-dev          Run Playwright against the dev stack"
	@echo "                          (vite dev server + --reload api; stack stays up)"

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
# this target re-establishes the privilege.
seed-super-admin:
	@if [ -z "$(email)" ] || [ -z "$(password)" ] || [ -z "$(name)" ]; then \
		echo "usage: make seed-super-admin email=you@example.com password=secret123 name='Your Name'"; \
		exit 1; \
	fi
	$(COMPOSE_DEV) run --rm api python -m app.scripts.seed_admin \
		--email "$(email)" --password "$(password)" --full-name "$(name)" \
		--super-admin

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

# --- Prod ---
prod-build:
	$(COMPOSE_PROD) build

prod-up:
	$(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down
