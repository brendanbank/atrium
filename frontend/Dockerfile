# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Multi-stage frontend Dockerfile.
# - dev:     pnpm dev server with HMR (used by docker-compose.dev.yml)
# - builder: pnpm build → dist/
# - runtime: nginx:alpine serving dist/ (used in prod)

FROM node:25-alpine AS base
WORKDIR /app
# Node 25 unbundles corepack, so ``corepack enable`` fails with
# ``corepack: not found``. Install pnpm directly via npm instead —
# forward-compatible with however Node upstream moves from here.
RUN npm install -g pnpm@10.33.1

# ---- dev ----
FROM base AS dev
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY . .
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]

# ---- builder ----
FROM base AS builder
ARG VITE_API_BASE_URL
ARG VITE_DEFAULT_LANGUAGE=en
ARG VITE_CKEDITOR_LICENSE_KEY=GPL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_DEFAULT_LANGUAGE=${VITE_DEFAULT_LANGUAGE} \
    VITE_CKEDITOR_LICENSE_KEY=${VITE_CKEDITOR_LICENSE_KEY}
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY . .
RUN pnpm build

# ---- runtime ----
# nginxinc/nginx-unprivileged is the official image variant that runs as
# UID 101 (no root master process) and listens on 8080 by default. Same
# nginx upstream — only the privilege model changes.
FROM nginxinc/nginx-unprivileged:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Redundant with the base image's default, but Trivy DS-0002 is
# text-based on the Dockerfile and won't trust an inherited USER.
USER 101
EXPOSE 8080
# ``localhost`` in nginx-unprivileged resolves to ``::1`` (IPv6-only) but
# nginx here listens on IPv4 only (``listen 8080;``), so the healthcheck
# must use 127.0.0.1 explicitly — otherwise wget gets ECONNREFUSED and
# the container flaps to ``unhealthy`` despite serving traffic fine.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
