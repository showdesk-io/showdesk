"""Auto-update: monitor Docker image digests and trigger Portainer redeploy."""

import logging
import os
import time
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="[auto-update] %(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

STATE_DIR = Path(os.environ.get("STATE_DIR", "/state"))
WEBHOOK_URL = os.environ.get("PORTAINER_WEBHOOK_URL", "")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "300"))
WATCHED_IMAGES = os.environ.get(
    "WATCHED_IMAGES",
    "ghcr.io/showdesk-io/showdesk-backend:latest ghcr.io/showdesk-io/showdesk-frontend:latest",
).split()

ACCEPT_HEADERS = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def parse_image(image: str) -> tuple[str, str, str]:
    """Parse 'registry/path:tag' into (registry, path, tag)."""
    parts = image.split("/", 1)
    registry = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    if ":" in rest:
        path, tag = rest.rsplit(":", 1)
    else:
        path, tag = rest, "latest"
    return registry, path, tag


def fetch_remote_digest(registry: str, path: str, tag: str) -> str | None:
    """Fetch the manifest digest from the container registry."""
    url = f"https://{registry}/v2/{path}/manifests/{tag}"
    try:
        resp = requests.get(url, headers={"Accept": ACCEPT_HEADERS}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # Look for digest in manifest list or image index
        if "manifests" in data:
            return data["manifests"][0].get("digest")
        # Single manifest — use Docker-Content-Digest header
        return resp.headers.get("Docker-Content-Digest")
    except Exception:
        log.warning("Failed to fetch digest for %s/%s:%s", registry, path, tag)
        return None


def load_stored_digest(state_file: Path) -> str | None:
    """Load the previously stored digest."""
    if state_file.exists():
        return state_file.read_text().strip()
    return None


def save_digest(state_file: Path, digest: str) -> None:
    """Save a digest to the state file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(digest)


def state_file_for(image: str) -> Path:
    """Return the state file path for an image."""
    safe_name = image.replace("/", "_").replace(":", "_")
    return STATE_DIR / safe_name


def check_for_updates() -> bool:
    """Check all watched images for new digests. Return True if any changed."""
    update_needed = False

    for image in WATCHED_IMAGES:
        registry, path, tag = parse_image(image)
        remote_digest = fetch_remote_digest(registry, path, tag)

        if not remote_digest:
            log.warning("Skipping %s (could not fetch digest)", image)
            continue

        state_file = state_file_for(image)
        stored_digest = load_stored_digest(state_file)

        if remote_digest != stored_digest:
            log.info("New image detected: %s (%s)", image, remote_digest)
            save_digest(state_file, remote_digest)
            update_needed = True
        else:
            log.info("Up to date: %s", image)

    return update_needed


def trigger_redeploy() -> None:
    """Call the Portainer stack webhook to redeploy."""
    try:
        resp = requests.post(WEBHOOK_URL, timeout=30)
        log.info("Portainer webhook response: %s", resp.status_code)
    except Exception:
        log.exception("Failed to call Portainer webhook")


def main() -> None:
    if not WEBHOOK_URL:
        log.warning("PORTAINER_WEBHOOK_URL is not set, running in dry-run mode.")

    log.info(
        "Starting (interval=%ds, images=%s)",
        CHECK_INTERVAL,
        ", ".join(WATCHED_IMAGES),
    )

    while True:
        try:
            if check_for_updates():
                if WEBHOOK_URL:
                    trigger_redeploy()
                else:
                    log.info("Update detected but no webhook configured (dry-run).")
            else:
                log.info("All images up to date.")
        except Exception:
            log.exception("Unexpected error during check")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
