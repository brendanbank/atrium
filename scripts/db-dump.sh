#!/usr/bin/env bash
# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

# Stream a full mysqldump of the running MySQL container to stdout.
#
# Usage:
#   ./scripts/db-dump.sh > dump.sql
#   ./scripts/db-dump.sh | gzip > dump.sql.gz
#   ./scripts/db-dump.sh | ssh host 'mysql -u … -p… atrium'
#
# Runs against whichever compose project is active (dev by default).

set -euo pipefail

cd "$(dirname "$0")/.."

# --single-transaction:       consistent InnoDB snapshot, no locks
# --set-gtid-purged=OFF:      drop GTID SET stmts so replay works on a non-replicated target
# --no-tablespaces:           suppresses PROCESS-privilege warnings on recent MySQL 8.x
# --default-character-set:    matches the schema
# --routines / --events:      include stored procs + scheduled events if any ever exist
exec docker compose exec -T mysql sh -c '
  mysqldump \
    -u root -p"$MYSQL_ROOT_PASSWORD" \
    --single-transaction \
    --set-gtid-purged=OFF \
    --no-tablespaces \
    --default-character-set=utf8mb4 \
    --routines --events \
    "$MYSQL_DATABASE"
'
