# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Multi-stage backend Dockerfile. Shared by api + worker containers.
# - builder: installs deps into a virtualenv
# - dev:     adds dev deps, bind-mounts source at runtime
# - runtime: slim image with only the virtualenv + app code

FROM python:3.14-slim AS base
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

# uv is the package manager (fast, reproducible)
RUN pip install uv

# ---- builder ----
FROM base AS builder
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# ---- dev ----
FROM base AS dev
COPY pyproject.toml uv.lock* ./
RUN uv sync 2>/dev/null || uv sync
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- runtime ----
FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends default-libmysqlclient-dev curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app . .

USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
