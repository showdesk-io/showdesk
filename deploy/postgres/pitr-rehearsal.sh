#!/usr/bin/env bash
# PITR rehearsal: restore WAL-G backups into a throwaway Postgres on this
# host (ideally NOT the production host), up to <target-time>, and print
# sanity checks. Nothing outside the throwaway container/volume is touched.
#
# Usage: pitr-rehearsal.sh <walg-env-file> '<target-time>'
#   <walg-env-file>: WALG_S3_PREFIX, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#     AWS_ENDPOINT, AWS_REGION, AWS_S3_FORCE_PATH_STYLE, WALG_LIBSODIUM_KEY,
#     WALG_LIBSODIUM_KEY_TRANSFORM (the container-side names, see README.md)
#   <target-time>: e.g. '2026-01-31 14:05:00+00' -- must be followed by at
#     least one archived COMMIT, see README.md "Rehearsing".
set -euo pipefail
ENVF="$1"; TARGET="$2"
IMG=ghcr.io/showdesk-io/showdesk-postgres:17
NAME=pitr-rehearsal
VOL=pitr_rehearsal_data

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker volume create "$VOL" >/dev/null

echo "==> backup-list"
docker run --rm --env-file "$ENVF" "$IMG" wal-g backup-list --detail

echo "==> backup-fetch LATEST + recovery config (target $TARGET)"
docker run --rm --env-file "$ENVF" -v "$VOL":/var/lib/postgresql/data --user root "$IMG" sh -c "
  chown postgres:postgres /var/lib/postgresql/data &&
  su postgres -c 'wal-g backup-fetch /var/lib/postgresql/data LATEST' &&
  touch /var/lib/postgresql/data/recovery.signal &&
  printf \"restore_command = 'wal-g wal-fetch %%f %%p'\nrecovery_target_time = '%s'\nrecovery_target_action = 'promote'\narchive_mode = off\n\" '$TARGET' >> /var/lib/postgresql/data/postgresql.auto.conf &&
  chown -R postgres:postgres /var/lib/postgresql/data"

echo "==> start recovery"
start=$SECONDS
docker run -d --name "$NAME" --env-file "$ENVF" -v "$VOL":/var/lib/postgresql/data "$IMG" postgres -c archive_mode=off >/dev/null
for _ in $(seq 120); do
  if docker exec "$NAME" psql -U "${PGUSER:-showdesk}" -d "${PGDATABASE:-showdesk}" -Atc "select not pg_is_in_recovery()" 2>/dev/null | grep -q t; then break; fi
  sleep 2
done
echo "recovery + promotion took $((SECONDS - start))s"
docker logs "$NAME" 2>&1 | grep -E "recovery stopping|redo done|selected new timeline|archive recovery complete|FATAL|PANIC" || true

echo "==> checks"
docker exec "$NAME" psql -U "${PGUSER:-showdesk}" -d "${PGDATABASE:-showdesk}" -Atc "
  select 'in_recovery=' || pg_is_in_recovery();
  select 'tables=' || count(*) from pg_tables where schemaname='public';
  select 'orgs=' || count(*) from organizations_organization;
  select 'users=' || count(*) from organizations_user;
  select 'tickets=' || count(*) from tickets_ticket;
  select 'last_migration=' || max(id) from django_migrations;
  select 'max_last_login=' || coalesce(max(last_login)::text,'-') from organizations_user;"
