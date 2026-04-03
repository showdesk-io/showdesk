#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Migration / collectstatic (runs for all modes unless RUN_MIGRATIONS=false)
# ---------------------------------------------------------------------------
if [ "${RUN_MIGRATIONS}" = "true" ]; then
    echo "[entrypoint] Applying database migrations..."
    python manage.py migrate --noinput

    echo "[entrypoint] Collecting static files..."
    python manage.py collectstatic --noinput
elif [ "${RUN_MIGRATIONS}" = "false" ]; then
    echo "[entrypoint] Dry-run: checking for pending migrations..."
    python manage.py migrate --check
fi

# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------
MODE="${1:-server}"

case "$MODE" in
    server)
        echo "[entrypoint] Starting gunicorn..."
        exec gunicorn config.asgi:application \
            -k uvicorn.workers.UvicornWorker \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-4}" \
            --timeout 120 \
            --access-logfile - \
            --error-logfile -
        ;;
    worker)
        echo "[entrypoint] Starting celery worker..."
        exec celery -A config worker \
            -l warning \
            -Q default,video_processing \
            --concurrency "${CELERY_CONCURRENCY:-4}" \
            --max-tasks-per-child 100
        ;;
    beat)
        echo "[entrypoint] Starting celery beat..."
        exec celery -A config beat -l warning
        ;;
    migrate)
        echo "[entrypoint] Migration-only mode, exiting."
        ;;
    *)
        echo "[entrypoint] Unknown mode: $MODE"
        echo "Usage: entrypoint.sh {server|worker|beat|migrate}"
        exit 1
        ;;
esac
