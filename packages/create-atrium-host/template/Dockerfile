# __BRAND_NAME__ host extension image. Two stages:
#
#   1. frontend-builder — node + pnpm, builds the host SPA bundle
#      (a single main.js dynamic-imported by atrium at runtime).
#   2. runtime — FROM the published atrium image, pip-installs the
#      host backend package into atrium's venv, and copies the host
#      bundle into /opt/atrium/static/host so atrium serves it at
#      /host/main.js (same origin as the SPA, no CORS).

ARG ATRIUM_IMAGE=ghcr.io/brendanbank/atrium:__ATRIUM_VERSION__

# ---- frontend-builder ----
FROM node:25-alpine AS frontend-builder
WORKDIR /app
RUN npm install -g pnpm@10.33.1

COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY frontend/ ./

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build

# ---- runtime ----
FROM ${ATRIUM_IMAGE} AS runtime

USER root
COPY backend /opt/host_app
# atrium's runtime image uses uv to build the venv but doesn't install
# pip into it. ensurepip bootstraps pip so we can install the host
# package — slightly slower than uv but avoids adding uv to the
# runtime image just for this one install.
RUN /opt/venv/bin/python -m ensurepip --upgrade \
 && /opt/venv/bin/python -m pip install --no-cache-dir /opt/host_app

# Bake the host bundle into atrium's static dir at /host/main.js.
COPY --from=frontend-builder /app/dist /opt/atrium/static/host

USER app

# Re-declare HEALTHCHECK on the derived image. The base atrium image
# already ships one (curl /healthz on :8000), but image scanners flag
# absence at the leaf Dockerfile because they don't trace inheritance.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1
