# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Host backend image — extends atrium-backend with the example package
# pip-installed into atrium's virtualenv. The base image's CMD (uvicorn)
# is unchanged; the host's behaviour is wired in by setting
# ATRIUM_HOST_MODULE in the runtime environment.
#
# Built from the repo root so the COPY can reach examples/:
#   docker build -t atrium-hello-backend -f examples/hello-world/backend/Dockerfile .
#
# In CI we tag this as `atrium-hello-backend:latest` and reuse the same
# image for the api and worker services in compose.e2e.yaml.

ARG ATRIUM_BACKEND_IMAGE=atrium-backend:latest
FROM ${ATRIUM_BACKEND_IMAGE}

USER root
COPY examples/hello-world/backend /opt/host_app
# atrium's runtime image uses uv to build the venv but doesn't install
# pip into it (uv installs deps directly). Bootstrap pip via ensurepip
# so we can pip-install the host package — slightly slower than uv but
# avoids adding uv to the runtime image just for this one install.
RUN /opt/venv/bin/python -m ensurepip --upgrade \
 && /opt/venv/bin/python -m pip install --no-cache-dir /opt/host_app
USER app
