# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Host frontend image — extends atrium-web by baking the pre-built
# host bundle into /usr/share/nginx/html/host. atrium's nginx config
# already SPA-falls-back to index.html under /, so a real file at
# /host/main.js is served directly without further nginx changes.
#
# Two-stage so the bundle build is reproducible from source rather
# than depending on a host-side ``pnpm build`` having run first. The
# builder uses the same node + pnpm versions as atrium's frontend
# Dockerfile to keep behaviour aligned.
#
# Built from the repo root so the COPY can reach examples/:
#   docker build -t atrium-hello-web \
#     --build-arg ATRIUM_WEB_IMAGE=ghcr.io/brendan-bank/atrium-web:0.9.1 \
#     -f examples/hello-world/frontend/Dockerfile .

# Global ARG — must be declared before the first FROM to be usable as
# the base image of a later stage.
ARG ATRIUM_WEB_IMAGE=ghcr.io/brendan-bank/atrium-web:latest

# ---- builder ----
FROM node:25-alpine AS builder
WORKDIR /app
RUN npm install -g pnpm@10.33.1
COPY examples/hello-world/frontend/package.json examples/hello-world/frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY examples/hello-world/frontend/ ./
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build

# ---- runtime ----
FROM ${ATRIUM_WEB_IMAGE} AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html/host
