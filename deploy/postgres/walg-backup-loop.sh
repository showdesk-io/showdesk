#!/bin/sh
# Periodic base backups + retention, meant to run as a sidecar container
# sharing the PostgreSQL data volume (as the postgres user).
#
#   WALG_BACKUP_INTERVAL   seconds between full backups (default 86400)
#   WALG_RETAIN_FULL       full backups to keep (default 7)
set -eu

: "${WALG_S3_PREFIX:?WALG_S3_PREFIX must be set}"
INTERVAL="${WALG_BACKUP_INTERVAL:-86400}"
RETAIN="${WALG_RETAIN_FULL:-7}"

until pg_isready -q; do sleep 5; done

while true; do
  echo "[walg] base backup starting"
  if wal-g backup-push "$PGDATA"; then
    wal-g delete retain FULL "$RETAIN" --confirm || echo "[walg] retention failed" >&2
    echo "[walg] base backup done; next in ${INTERVAL}s"
  else
    echo "[walg] base backup FAILED; retrying in 15 min" >&2
    sleep 900
    continue
  fi
  sleep "$INTERVAL"
done
