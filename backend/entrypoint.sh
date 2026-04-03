#!/bin/bash
set -e

if [ "${RUN_MIGRATIONS}" = "true" ]; then
    echo "[entrypoint] Applying database migrations..."
    python manage.py migrate --noinput

    echo "[entrypoint] Collecting static files..."
    python manage.py collectstatic --noinput
else
    echo "[entrypoint] Dry-run: checking for pending migrations..."
    python manage.py migrate --check
fi

exec "$@"
