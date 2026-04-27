#!/bin/sh
# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Generate a self-signed cert on first boot. The cert lives in a named
# volume so it's stable across container restarts (same fingerprint to
# pin against from the edge Caddy). Delete the volume to rotate.
set -e

CERT_DIR=/etc/nginx/certs
CERT=$CERT_DIR/server.crt
KEY=$CERT_DIR/server.key
CN=${PROXY_CERT_CN:-atrium-internal}

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
    exit 0
fi

# nginx:alpine ships without openssl, so install it for the one-shot.
if ! command -v openssl >/dev/null 2>&1; then
    apk add --no-cache openssl >/dev/null
fi

mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -subj "/CN=$CN" \
    -keyout "$KEY" -out "$CERT" >/dev/null 2>&1

echo "proxy: generated self-signed cert for CN=$CN"
