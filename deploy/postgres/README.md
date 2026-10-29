# PostgreSQL with point-in-time recovery (WAL-G)

`ghcr.io/showdesk-io/showdesk-postgres:17` is the official `postgres:17`
image plus [WAL-G](https://github.com/wal-g/wal-g). It is used by the
`local` and `postgres` compose profiles.

- **Continuous archiving**: every WAL segment is pushed to S3 (at the latest
  every `WALG_ARCHIVE_TIMEOUT` seconds, default 60). Without
  `WALG_S3_PREFIX` archiving is a no-op and the image behaves like upstream.
- **Base backups**: the `postgres-backup` sidecar (profile `backup`) takes a
  full backup every `WALG_BACKUP_INTERVAL` seconds (default daily) and keeps
  the last `WALG_RETAIN_FULL` (default 7).

Base backups + archived WAL let you restore the database to **any point in
time** inside the retention window.

## Configuration (`.env`)

```bash
COMPOSE_PROFILES=redis,postgres,backup        # or local,backup
DATABASE_URL=postgres://showdesk:<password>@postgres:5432/showdesk
POSTGRES_PASSWORD=<password>

WALG_S3_PREFIX=s3://<bucket>/<path>
WALG_S3_ENDPOINT=https://s3.<region>.example.com
WALG_S3_REGION=<region>
WALG_S3_ACCESS_KEY_ID=...
WALG_S3_SECRET_ACCESS_KEY=...
# Client-side encryption (strongly recommended). 32 random bytes, hex:
#   openssl rand -hex 32
# Store it outside the server too: without it the backups are unreadable.
WALG_LIBSODIUM_KEY=...
```

Use a dedicated bucket with credentials that cannot reach your media bucket.

## Operations

```bash
dc() { docker compose -f docker-compose.prod.yml --env-file .env "$@"; }

dc exec postgres-backup wal-g backup-list --detail   # list base backups
dc exec postgres-backup wal-g backup-push "$PGDATA"  # backup now
dc logs -f postgres-backup
```

## Restore (point in time)

1. Stop everything that writes to the database:
   `dc stop backend celery-worker celery-beat postgres-backup postgres`
2. Move the current data aside (keep it until the restore is validated):
   `docker volume create showdesk_postgres_data_old` and copy, or rename the
   volume via a temporary container.
3. Fetch the base backup into an empty data volume and request recovery:

   ```bash
   dc run --rm --no-deps --user postgres --entrypoint sh postgres -c '
     rm -rf "$PGDATA"/* &&
     wal-g backup-fetch "$PGDATA" LATEST &&
     touch "$PGDATA/recovery.signal" &&
     cat >> "$PGDATA/postgresql.auto.conf" <<EOF
   restore_command = '"'"'wal-g wal-fetch %f %p'"'"'
   recovery_target_time = '"'"'2026-01-31 14:05:00+00'"'"'
   recovery_target_action = '"'"'promote'"'"'
   EOF'
   ```

   Omit `recovery_target_time` to replay up to the last archived segment.
   Use a backup name from `backup-list` instead of `LATEST` for older targets.
4. `dc up -d postgres` and watch `dc logs -f postgres` until
   "database system is ready to accept connections".
5. Remove the recovery lines from `postgresql.auto.conf`, then start the
   rest of the stack. Take a fresh base backup right away
   (`dc up -d postgres-backup` does it on start) since recovery opens a new
   timeline.

Rehearse a restore on a scratch host periodically -- an untested backup is
not a backup.
