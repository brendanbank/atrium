# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Hello World host extension image. Two stages:
#
#   1. frontend-builder — node + pnpm, builds the host SPA bundle
#      (a single main.js dynamic-imported by atrium at runtime).
#   2. runtime — FROM the published atrium image, pip-installs the
#      host backend package into atrium's venv, and copies the host
#      bundle into /opt/atrium/static/host so atrium serves it at
#      /host/main.js (same origin as the SPA, no CORS).
#
# Built from the repo root so COPY can reach examples/hello-world/.
# The compose file does this for you.

# Global ARG — must be declared before the first FROM to be usable as
# the base image of a later stage. Pinned to a concrete minor line
# rather than ``:latest`` so a passive image scan reports the actual
# build base; CI / compose typically override this via build args
# (``ATRIUM_IMAGE=atrium-local:source`` for PR tests).
ARG ATRIUM_IMAGE=ghcr.io/brendan-bank/atrium:0.14

# ---- frontend-builder ----
#
# The example consumes the host SDK packages via `workspace:*`
# references (see `examples/hello-world/frontend/package.json`), so
# the build needs the full pnpm workspace context — the lockfile, the
# workspace yaml, the `.npmrc` that maps `@brendan-bank` at GitHub
# Packages, and every workspace member's `package.json`. We bring
# those in first (cache-friendly: lockfile changes invalidate this
# layer but a source-only edit doesn't), install, then bring in the
# actual source for `packages/*` and the example.
FROM node:25-alpine AS frontend-builder
WORKDIR /app
RUN npm install -g pnpm@10.33.1

# Workspace skeleton — package.json + lockfile + workspace yaml are
# enough for `pnpm install --frozen-lockfile` to resolve every
# transitive dep and link the workspace members.
COPY pnpm-lock.yaml pnpm-workspace.yaml .npmrc package.json ./
COPY packages/host-types/package.json ./packages/host-types/
COPY packages/host-bundle-utils/package.json ./packages/host-bundle-utils/
COPY examples/hello-world/frontend/package.json ./examples/hello-world/frontend/

RUN pnpm install --frozen-lockfile

# Bring in the SDK package sources and build them — the example's
# vite.config.ts imports from `@brendan-bank/atrium-host-bundle-utils/vite`,
# which resolves through the workspace symlink to `packages/host-bundle-utils/dist/vite/`.
# That dist directory must exist before vite runs.
COPY packages/host-types/ ./packages/host-types/
COPY packages/host-bundle-utils/ ./packages/host-bundle-utils/
RUN pnpm -r --filter './packages/*' build

# Now the example source + the actual bundle build.
COPY examples/hello-world/frontend/ ./examples/hello-world/frontend/
WORKDIR /app/examples/hello-world/frontend

# Same default as the unified atrium image — bundle calls relative
# paths (`/hello/state`, `/hello/toggle`) so it lands on whatever
# origin the SPA was loaded from.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build

# ---- runtime ----
FROM ${ATRIUM_IMAGE} AS runtime

USER root
COPY examples/hello-world/backend /opt/host_app
# atrium's runtime image uses uv to build the venv but doesn't install
# pip into it (uv installs deps directly). Bootstrap pip via ensurepip
# so we can pip-install the host package — slightly slower than uv but
# avoids adding uv to the runtime image just for this one install.
RUN /opt/venv/bin/python -m ensurepip --upgrade \
 && /opt/venv/bin/python -m pip install --no-cache-dir /opt/host_app

# Bake the host bundle into atrium's static dir at /host/main.js.
COPY --from=frontend-builder /app/examples/hello-world/frontend/dist /opt/atrium/static/host

USER app

# Re-declare HEALTHCHECK on the derived image. The base atrium image
# already ships one (curl /healthz), but image scanners flag absence
# at the leaf Dockerfile because they don't trace inheritance.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1
