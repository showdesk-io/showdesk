#!/usr/bin/env bash
# =============================================================================
# Showdesk -- deploy a given image tag on the current host.
#
# Usage (run on the server, from the app directory):
#   ./remote-deploy.sh <image-tag>
#
# Expects docker-compose.prod.yml and .env in the same directory. Pulls the
# images, (re)starts the stack, waits for the backend health check and rolls
# back to the last known-good tag if it never turns healthy.
# =============================================================================
set -euo pipefail

TAG="${1:?usage: $0 <image-tag>}"
cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env)
LAST_GOOD_FILE=.last_good_tag
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

up() {
  IMAGE_TAG="$1" "${COMPOSE[@]}" pull --quiet
  IMAGE_TAG="$1" "${COMPOSE[@]}" up -d --remove-orphans
  recreate_on_config_change
}

# Compose does not recreate a container when only the content of an inline
# `configs:` entry changes (e.g. the Caddyfile), so track its hash ourselves.
recreate_on_config_change() {
  local current previous=""
  current="$("${COMPOSE[@]}" config | sed -n '/^configs:/,/^[a-z]/p' | sha256sum | cut -d' ' -f1)"
  [[ -f .configs.sha256 ]] && previous="$(cat .configs.sha256)"
  if [[ "$current" != "$previous" ]]; then
    echo "==> Inline configs changed, recreating caddy"
    "${COMPOSE[@]}" up -d --no-deps --force-recreate caddy
    echo "$current" >.configs.sha256
  fi
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) id status
  while ((SECONDS < deadline)); do
    id="$("${COMPOSE[@]}" ps -q backend)"
    status="$(docker inspect --format '{{.State.Health.Status}}' "$id" 2>/dev/null || echo starting)"
    echo "backend: $status"
    [[ "$status" == "healthy" ]] && return 0
    sleep 5
  done
  return 1
}

echo "==> Deploying $TAG"
up "$TAG"

if wait_healthy; then
  echo "$TAG" >"$LAST_GOOD_FILE"
  docker image prune -af --filter "until=168h" >/dev/null
  echo "==> $TAG is live"
  exit 0
fi

echo "!! $TAG did not become healthy" >&2
"${COMPOSE[@]}" logs --tail 100 backend migrate >&2 || true

if [[ -s "$LAST_GOOD_FILE" ]] && [[ "$(cat "$LAST_GOOD_FILE")" != "$TAG" ]]; then
  PREVIOUS="$(cat "$LAST_GOOD_FILE")"
  echo "==> Rolling back to $PREVIOUS" >&2
  up "$PREVIOUS"
  wait_healthy || echo "!! rollback to $PREVIOUS is not healthy either" >&2
fi
exit 1
