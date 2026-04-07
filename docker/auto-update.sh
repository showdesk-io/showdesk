#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Auto-update: check for new image digests on ghcr.io and trigger
# a Portainer stack redeploy via webhook if any image has changed.
# ---------------------------------------------------------------------------

IMAGES="${WATCHED_IMAGES:-ghcr.io/showdesk-io/showdesk-backend:latest ghcr.io/showdesk-io/showdesk-frontend:latest}"
WEBHOOK_URL="${PORTAINER_WEBHOOK_URL:-}"
STATE_DIR="/state"

if [ -z "$WEBHOOK_URL" ]; then
    echo "[auto-update] PORTAINER_WEBHOOK_URL is not set, skipping."
    exit 0
fi

mkdir -p "$STATE_DIR"

update_needed=false

for image in $IMAGES; do
    registry=$(echo "$image" | cut -d/ -f1)
    path=$(echo "$image" | cut -d/ -f2- | cut -d: -f1)
    tag=$(echo "$image" | grep -o ':[^:]*$' | cut -c2-)
    tag=${tag:-latest}

    state_file="$STATE_DIR/$(echo "$image" | tr '/:' '_')"

    # Fetch current digest from registry (anonymous, works for public packages)
    remote_digest=$(curl -sf \
        -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json" \
        "https://${registry}/v2/${path}/manifests/${tag}" \
        | grep -i '"digest"' | head -1 | tr -d ' ",' | cut -d: -f2-3) || true

    if [ -z "$remote_digest" ]; then
        echo "[auto-update] Could not fetch digest for $image, skipping."
        continue
    fi

    # Compare with stored digest
    stored_digest=""
    if [ -f "$state_file" ]; then
        stored_digest=$(cat "$state_file")
    fi

    if [ "$remote_digest" != "$stored_digest" ]; then
        echo "[auto-update] New image detected: $image ($remote_digest)"
        echo "$remote_digest" > "$state_file"
        update_needed=true
    else
        echo "[auto-update] Up to date: $image"
    fi
done

if [ "$update_needed" = true ]; then
    echo "[auto-update] Triggering Portainer stack redeploy..."
    response=$(curl -sf -X POST "$WEBHOOK_URL" -w "%{http_code}" -o /dev/null) || true
    if [ "$response" = "200" ] || [ "$response" = "204" ]; then
        echo "[auto-update] Stack redeploy triggered successfully."
    else
        echo "[auto-update] Webhook call failed (HTTP $response)."
    fi
else
    echo "[auto-update] All images up to date, no action needed."
fi
