# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Unified atrium image. Builds the SPA, builds the Python venv, and
# ships a slim runtime that serves both:
#   /api routes  → FastAPI handlers
#   everything else → built SPA mounted via Starlette StaticFiles
#
# Built from the repo root so a single COPY can reach backend/ and
# frontend/. Published to ghcr.io/<owner>/atrium.
#
# Stages:
#   frontend-builder — node + pnpm, runs `pnpm build` → /app/dist
#   backend-base     — python:3.13-slim + apt deps + uv
#   backend-builder  — uv sync --no-dev into /opt/venv
#   dev              — uv sync with dev deps; expects bind-mounted source
#   runtime          — final image: venv + backend src + built dist

# ---- frontend-base ----
FROM node:25-alpine AS frontend-base
WORKDIR /app
# Node 25 unbundles corepack (``corepack enable`` fails with not-found),
# so install pnpm via npm — same outcome, forward-compatible.
RUN npm install -g pnpm@10.33.1

# ---- frontend-dev ----
# Used by docker-compose.dev.yml's web service. The frontend tree is
# bind-mounted at runtime; the COPY + install here populates
# /app/node_modules so the named volume gets seeded on first up.
FROM frontend-base AS frontend-dev
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY frontend/ ./
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]

# ---- frontend-builder ----
FROM frontend-base AS frontend-builder
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY frontend/ ./
# SPA calls /api/... — atrium mounts every JSON route under /api so
# the un-prefixed URL space (e.g. /admin/audit) is owned by the SPA
# router. Same origin as the API, no rewrite needed.
ARG VITE_API_BASE_URL="/api"
ARG VITE_DEFAULT_LANGUAGE=en
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_DEFAULT_LANGUAGE=${VITE_DEFAULT_LANGUAGE}
RUN pnpm build

# ---- backend-base ----
FROM python:3.13-slim AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential default-libmysqlclient-dev pkg-config curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip install uv

# ---- backend-builder ----
FROM backend-base AS backend-builder
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# ---- dev ----
# Used by docker-compose.dev.yml. Backend source is bind-mounted at
# runtime; the COPY here is just so the image is standalone-runnable.
FROM backend-base AS dev
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync 2>/dev/null || uv sync
COPY backend/ .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- runtime ----
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ATRIUM_STATIC_DIR=/opt/atrium/static
WORKDIR /app

# Apply Debian security updates on every build so the published image
# picks up deb13 point releases (krb5, systemd, libcap, libnghttp2,
# etc.) without waiting for the base ``python:3.13-slim`` tag to
# refresh. Trivy on this repo and on downstream consumers
# (atrium-pa, etc.) was firing on every published image until this
# was added — see milestone "Security alerts (May 2026)".
RUN apt-get update \
 && apt-get -y upgrade \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

COPY --from=backend-builder --chown=app:app /opt/venv /opt/venv
# Strip pip + setuptools from the project venv AND from the system
# Python that ``python:3.13-slim`` ships. Neither is needed at
# runtime (uv produces the venv, uvicorn runs from it) and both were
# the source of recurring Trivy alerts:
#   CVE-2026-3219 + CVE-2026-6357  (pip pre-26.1)
#   CVE-2025-47273                 (setuptools pre-78.1.1)
# Direct ``rm`` is more reliable than ``pip uninstall pip`` — the
# latter is fragile when pip is removing itself.
RUN rm -rf /opt/venv/lib/python*/site-packages/pip* \
           /opt/venv/lib/python*/site-packages/setuptools* \
           /opt/venv/lib/python*/site-packages/pkg_resources* \
           /opt/venv/lib/python*/site-packages/_distutils_hack* \
           /opt/venv/lib/python*/site-packages/distutils-precedence.pth \
           /opt/venv/bin/pip* \
           /usr/local/lib/python*/site-packages/pip* \
           /usr/local/lib/python*/site-packages/setuptools* \
           /usr/local/lib/python*/site-packages/pkg_resources* \
           /usr/local/lib/python*/site-packages/_distutils_hack* \
           /usr/local/lib/python*/site-packages/distutils-precedence.pth \
           /usr/local/bin/pip*
COPY --chown=app:app backend/ .
# Built SPA dist — FastAPI mounts this at / via SPAStaticFiles.
COPY --from=frontend-builder --chown=app:app /app/dist /opt/atrium/static

USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
