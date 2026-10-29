#!/bin/sh
# archive_command wrapper: push the WAL segment when WAL-G is configured,
# otherwise report success so PostgreSQL can recycle it.
[ -n "${WALG_S3_PREFIX:-}" ] || exit 0
exec wal-g wal-push "$1"
