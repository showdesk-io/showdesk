#!/usr/bin/env python3
"""
Showdesk -- Development environment orchestrator.

Single entry point to bootstrap and run the full dev stack.
Handles everything that init containers and Makefile targets used to do,
but in a single, readable, extensible script.

Usage:
    python dev.py                  # Full bootstrap + start
    python dev.py up               # Start services (skip init if already done)
    python dev.py init             # Run init steps only (no start)
    python dev.py seed             # Seed database with demo data
    python dev.py reset            # Nuke volumes and re-bootstrap everything
    python dev.py down             # Stop all services
    python dev.py logs             # Tail all logs
    python dev.py status           # Show service status
    python dev.py tunnel           # Tunnel "dev" -> dev.DOMAIN
    python dev.py tunnel staging   # Tunnel "staging" -> staging.DOMAIN
    python dev.py tunnel-login     # Authenticate cloudflared for Showdesk
    python dev.py tunnel-status    # Show tunnel info
    python dev.py tunnel-stop      # Stop running tunnel
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

COMPOSE_CMD = ["docker", "compose"]

# Services that must be healthy before we can run init steps
INFRA_SERVICES = ["postgres", "redis", "minio"]

# Marker file to skip init on subsequent `dev.py up`
INIT_MARKER = ROOT / ".dev-initialized"

# Cloudflare tunnel config -- separate cert from the default ~/.cloudflared/
# This allows using a different Cloudflare account than the one configured
# system-wide. The cert is stored in the project's .cloudflared/ directory.
CF_DIR = ROOT / ".cloudflared"
CF_CERT = CF_DIR / "cert.pem"
CF_DEFAULT_TUNNEL = "dev"
CF_PID_FILE = ROOT / ".tunnel.pid"

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str, color: str = GREEN) -> None:
    print(f"{color}{BOLD}>{RESET} {msg}")


def log_step(msg: str) -> None:
    print(f"\n{CYAN}{BOLD}{'_' * 60}{RESET}")
    print(f"{CYAN}{BOLD}  {msg}{RESET}")
    print(f"{CYAN}{BOLD}{'_' * 60}{RESET}\n")


def run(
    cmd: list[str] | str,
    *,
    check: bool = True,
    capture: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, printing it first."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    display = " ".join(cmd)
    log(f"$ {display}", color=YELLOW)
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        cwd=cwd or ROOT,
    )


def compose(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a docker compose command."""
    return run([*COMPOSE_CMD, *args], **kwargs)


def compose_exec(service: str, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a command inside a running service container."""
    return run([*COMPOSE_CMD, "exec", "-T", service, *args], **kwargs)


def compose_run(service: str, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a one-off command in a new container."""
    return run([*COMPOSE_CMD, "run", "--rm", "-T", service, *args], **kwargs)


def wait_healthy(service: str, timeout: int = 60) -> None:
    """Wait for a service to become healthy."""
    log(f"Waiting for {service} to be healthy...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = run(
            [*COMPOSE_CMD, "ps", "--format", "{{.Health}}", service],
            capture=True,
            check=False,
        )
        status = result.stdout.strip().lower()
        if status == "healthy":
            log(f"{service} is healthy")
            return
        time.sleep(2)
    print(f"{RED}Timeout waiting for {service} to become healthy.{RESET}")
    sys.exit(1)


def has_cloudflared() -> bool:
    """Check if cloudflared is installed."""
    return shutil.which("cloudflared") is not None


def cf_cmd(*args: str) -> list[str]:
    """Build a cloudflared command with the project-specific origincert."""
    base = ["cloudflared"]
    if CF_CERT.exists():
        base += ["--origincert", str(CF_CERT)]
    return [*base, *args]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def ensure_env() -> None:
    """Copy .env.example to .env if it doesn't exist."""
    if ENV_FILE.exists():
        log(".env already exists, skipping copy.")
        return
    if not ENV_EXAMPLE.exists():
        print(f"{RED}.env.example not found. Something is wrong.{RESET}")
        sys.exit(1)
    shutil.copy(ENV_EXAMPLE, ENV_FILE)
    log("Created .env from .env.example -- review and adjust as needed.")


def start_infra() -> None:
    """Start infrastructure services (db, cache, storage) and wait for health."""
    log_step("Starting infrastructure services")
    compose("up", "-d", *INFRA_SERVICES)
    for svc in INFRA_SERVICES:
        wait_healthy(svc)


def init_minio_buckets() -> None:
    """Create S3 buckets in MinIO."""
    log_step("Initializing MinIO buckets")

    access_key = os.environ.get("S3_ACCESS_KEY_ID", "showdesk")
    secret_key = os.environ.get("S3_SECRET_ACCESS_KEY", "showdesk-secret")
    bucket = os.environ.get("S3_BUCKET_NAME", "showdesk-media")

    # Use the minio container's mc client directly
    compose_exec(
        "minio",
        "mc", "alias", "set", "local", "http://localhost:9000", access_key, secret_key,
        check=False,
    )
    compose_exec(
        "minio",
        "mc", "mb", f"local/{bucket}", "--ignore-existing",
        check=False,
    )
    compose_exec(
        "minio",
        "mc", "anonymous", "set", "download", f"local/{bucket}/public",
        check=False,
    )
    log(f"Bucket '{bucket}' ready")


def start_app_services() -> None:
    """Start all application services."""
    log_step("Starting application services")
    compose("up", "--build", "-d")


def run_migrations() -> None:
    """Run Django database migrations."""
    log_step("Running database migrations")
    compose_exec("backend", "python", "manage.py", "migrate", "--noinput")


def seed_database() -> None:
    """Seed the database with demo data."""
    log_step("Seeding database")
    compose_exec("backend", "python", "manage.py", "seed")


def collect_static() -> None:
    """Collect Django static files."""
    compose_exec(
        "backend", "python", "manage.py", "collectstatic", "--noinput",
        check=False,
    )


def mark_initialized() -> None:
    """Write a marker file so subsequent `up` skips init."""
    INIT_MARKER.write_text(
        "# Dev environment initialized. Delete this file to force re-init.\n"
    )


def print_banner() -> None:
    """Print the final status banner."""
    print(f"""
{GREEN}{BOLD}{'=' * 60}
  Showdesk is running!
{'=' * 60}{RESET}

  {BOLD}App{RESET}          http://localhost
  {BOLD}Mailpit{RESET}      http://localhost/mailpit/
  {BOLD}MinIO{RESET}        http://localhost:9001
  {BOLD}LiveKit{RESET}      ws://localhost:7880

  {BOLD}Login{RESET}        admin@showdesk.local (OTP via email)
  {BOLD}Emails{RESET}       Check Mailpit for OTP codes

  {YELLOW}Logs:{RESET}        python dev.py logs
  {YELLOW}Stop:{RESET}        python dev.py down
  {YELLOW}Tunnel:{RESET}      python dev.py tunnel
  {YELLOW}Reset:{RESET}       python dev.py reset
""")


# ---------------------------------------------------------------------------
# Tunnel
# ---------------------------------------------------------------------------


def tunnel_stop() -> None:
    """Stop any running tunnel process."""
    if CF_PID_FILE.exists():
        pid_str = CF_PID_FILE.read_text().strip()
        try:
            pid = int(pid_str)
            os.kill(pid, signal.SIGTERM)
            log(f"Stopped tunnel process (PID {pid}).")
        except (ValueError, ProcessLookupError):
            pass
        CF_PID_FILE.unlink(missing_ok=True)


def cmd_tunnel_login() -> None:
    """Authenticate cloudflared with a Cloudflare account for Showdesk.

    Stores the cert in .cloudflared/cert.pem (project-local), completely
    independent of the system-wide ~/.cloudflared/cert.pem.
    This lets you use a different Cloudflare account for Showdesk.

    Strategy: cloudflared login always writes to ~/.cloudflared/cert.pem and
    doesn't support --origincert. So we temporarily back up any existing cert,
    run the login, move the new cert to the project dir, then restore the backup.
    """
    if not has_cloudflared():
        print(f"{RED}cloudflared is not installed.{RESET}")
        print("Install it: brew install cloudflare/cloudflare/cloudflared")
        sys.exit(1)

    CF_DIR.mkdir(exist_ok=True)

    if CF_CERT.exists():
        log(f"Existing cert found at {CF_CERT}")
        log("Delete it first if you want to re-authenticate.")
        print(f"\n  {DIM}rm {CF_CERT}{RESET}\n")
        return

    log_step("Cloudflare authentication")
    print(f"""  This will open a browser to authenticate with Cloudflare.
  The certificate will be saved to:

    {BOLD}{CF_CERT}{RESET}

  This is {BOLD}separate{RESET} from your system-wide ~/.cloudflared/cert.pem,
  so it won't affect your other Cloudflare accounts.
""")

    # cloudflared login always writes to ~/.cloudflared/cert.pem.
    # We back up any existing cert, run login, then move the new cert
    # to our project-local directory and restore the original.
    system_cf_dir = Path.home() / ".cloudflared"
    system_cert = system_cf_dir / "cert.pem"
    backup_cert = system_cf_dir / "cert.pem.showdesk-backup"

    had_existing = system_cert.exists()
    if had_existing:
        log(f"Backing up existing {system_cert}")
        shutil.copy2(system_cert, backup_cert)

    try:
        run(["cloudflared", "login"])

        if system_cert.exists():
            # Move the new cert to our project-local directory
            shutil.move(str(system_cert), str(CF_CERT))
            log(f"Cert moved to {CF_CERT}")
        else:
            print(f"{RED}Authentication failed or was cancelled.{RESET}")
            sys.exit(1)
    finally:
        # Restore the original cert if there was one
        if had_existing and backup_cert.exists():
            shutil.move(str(backup_cert), str(system_cert))
            log(f"Restored original {system_cert}")
        elif backup_cert.exists():
            backup_cert.unlink()

    if CF_CERT.exists():
        log(f"Authenticated! Cert saved to {CF_CERT}")
    else:
        print(f"{RED}Authentication failed or was cancelled.{RESET}")
        sys.exit(1)


def _get_cf_domain() -> str:
    """Read the base domain from SHOWDESK_DOMAIN env var."""
    domain = os.environ.get("SHOWDESK_DOMAIN", "").strip()
    if not domain or domain == "localhost":
        print(f"{RED}SHOWDESK_DOMAIN is not set (or is 'localhost').{RESET}")
        print(f"Set it in your .env to your Cloudflare-managed domain.")
        print(f"  Example: SHOWDESK_DOMAIN=showdesk.io")
        sys.exit(1)
    return domain


def _get_tunnel_name() -> str:
    """Get tunnel name from argv or default."""
    if len(sys.argv) >= 3 and not sys.argv[2].startswith("-"):
        return sys.argv[2]
    return CF_DEFAULT_TUNNEL


def _find_or_create_tunnel(name: str) -> str:
    """Find an existing tunnel by name or create it. Returns tunnel ID."""
    import json as _json

    # Check if tunnel already exists
    result = run(
        cf_cmd("tunnel", "list", "--output", "json"),
        capture=True,
        check=False,
    )

    if result.returncode == 0 and result.stdout.strip():
        try:
            tunnels = _json.loads(result.stdout)
            for t in tunnels:
                if t.get("name") == name:
                    tunnel_id = t["id"]
                    log(f"Found existing tunnel: {name} ({tunnel_id})")
                    return tunnel_id
        except (_json.JSONDecodeError, KeyError):
            pass

    # Create tunnel
    log(f"Creating tunnel: {name}")
    result = run(
        cf_cmd("tunnel", "create", name),
        capture=True,
    )
    # Parse tunnel ID from output: "Created tunnel <name> with id <uuid>"
    for word in result.stdout.split():
        if len(word) == 36 and word.count("-") == 4:
            log(f"Tunnel created: {word}")
            return word

    print(f"{RED}Failed to create tunnel.{RESET}")
    print(result.stdout)
    sys.exit(1)


def cmd_tunnel() -> None:
    """Create a Cloudflare tunnel and bind it to a DNS record.

    Usage:
      python dev.py tunnel              # tunnel "dev" -> dev.DOMAIN
      python dev.py tunnel staging       # tunnel "staging" -> staging.DOMAIN

    Requires tunnel-login first. Reads SHOWDESK_DOMAIN from .env.
    """
    if not has_cloudflared():
        print(f"{RED}cloudflared is not installed.{RESET}")
        print("Install it: brew install cloudflare/cloudflare/cloudflared")
        sys.exit(1)

    if not CF_CERT.exists():
        print(f"{RED}No Cloudflare cert found for Showdesk.{RESET}")
        print(f"Run {BOLD}python dev.py tunnel-login{RESET} first to authenticate.")
        print()
        print(f"  {DIM}This is separate from ~/.cloudflared/ and won't affect")
        print(f"  your other Cloudflare accounts.{RESET}")
        sys.exit(1)

    # Stop any existing tunnel
    tunnel_stop()

    tunnel_name = _get_tunnel_name()
    domain = _get_cf_domain()
    hostname = f"{tunnel_name}.{domain}"

    log_step(f"Tunnel: {tunnel_name} -> {hostname}")

    # Find or create the tunnel
    tunnel_id = _find_or_create_tunnel(tunnel_name)

    # Create DNS CNAME record (idempotent -- cloudflared updates if exists)
    log(f"Setting DNS: {hostname} -> {tunnel_id}.cfargotunnel.com")
    run(cf_cmd("tunnel", "route", "dns", "--overwrite-dns", tunnel_name, hostname), check=False)

    # Write tunnel config
    tunnel_config = CF_DIR / "config.yml"
    tunnel_config.write_text(
        f"tunnel: {tunnel_id}\n"
        f"credentials-file: {CF_DIR / (tunnel_id + '.json')}\n"
        f"\n"
        f"ingress:\n"
        f"  - hostname: {hostname}\n"
        f"    service: http://localhost:80\n"
        f"  - service: http_status:404\n"
    )
    log(f"Tunnel config written to {tunnel_config}")

    # Run the tunnel
    proc = subprocess.Popen(
        cf_cmd("tunnel", "--config", str(tunnel_config), "run", tunnel_name),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    CF_PID_FILE.write_text(str(proc.pid))

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  Tunnel is running!
{'=' * 60}{RESET}

  {BOLD}Tunnel{RESET}       {tunnel_name} ({tunnel_id})
  {BOLD}URL{RESET}          https://{hostname}
  {BOLD}Local{RESET}        http://localhost

  Press Ctrl+C to stop the tunnel.
""")

    try:
        proc.wait()
    except KeyboardInterrupt:
        log("Stopping tunnel...")
        proc.terminate()
        proc.wait(timeout=5)
    finally:
        CF_PID_FILE.unlink(missing_ok=True)


def cmd_tunnel_status() -> None:
    """Show tunnel status and info."""
    # Check for running tunnel process
    if CF_PID_FILE.exists():
        pid_str = CF_PID_FILE.read_text().strip()
        try:
            pid = int(pid_str)
            os.kill(pid, 0)  # Check if process exists (signal 0)
            log(f"Tunnel process is running (PID {pid})")
        except (ValueError, ProcessLookupError):
            log("No tunnel process running (stale PID file)")
            CF_PID_FILE.unlink(missing_ok=True)
    else:
        log("No tunnel process running")

    print()

    # Check cert
    if CF_CERT.exists():
        log(f"Cloudflare cert: {CF_CERT}")
        log("  Account: authenticated (project-local cert)")
    else:
        log("Cloudflare cert: not found")
        log(f"  Run {BOLD}python dev.py tunnel-login{RESET} to authenticate")

    print()

    # List tunnels if authenticated
    if CF_CERT.exists() and has_cloudflared():
        log("Named tunnels:")
        run(cf_cmd("tunnel", "list"), check=False)


def cmd_tunnel_stop() -> None:
    """Stop the running tunnel."""
    tunnel_stop()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_up() -> None:
    """Start services, run init only if not already done."""
    ensure_env()

    if INIT_MARKER.exists():
        log("Already initialized -- starting services only.")
        log("(Delete .dev-initialized to force re-init)")
        start_app_services()
        print_banner()
        return

    cmd_default()


def cmd_default() -> None:
    """Full bootstrap: infra -> init -> app -> migrate -> seed."""
    ensure_env()
    start_infra()
    init_minio_buckets()
    start_app_services()

    # Wait for backend to be ready (Daphne startup)
    log("Waiting for backend to accept connections...")
    time.sleep(5)

    run_migrations()
    collect_static()

    # Only seed if DB is empty (first run)
    result = compose_exec(
        "backend",
        "python", "-c",
        "import django; django.setup(); from apps.organizations.models import Organization; print(Organization.objects.count())",
        capture=True,
        check=False,
    )
    org_count = result.stdout.strip()
    if org_count == "0":
        seed_database()
    else:
        log(f"Database already has {org_count} organization(s), skipping seed.")

    mark_initialized()
    print_banner()


def cmd_init() -> None:
    """Run init steps only (no service start)."""
    ensure_env()
    start_infra()
    init_minio_buckets()

    # Need backend for migrations
    start_app_services()
    time.sleep(5)

    run_migrations()
    collect_static()
    seed_database()
    mark_initialized()
    log("Init complete")


def cmd_seed() -> None:
    """Seed the database with demo data."""
    seed_database()


def cmd_reset() -> None:
    """Nuke everything and start fresh."""
    log_step("Resetting dev environment")
    tunnel_stop()
    compose("down", "-v", "--remove-orphans")
    if INIT_MARKER.exists():
        INIT_MARKER.unlink()
        log("Removed .dev-initialized marker.")
    log("Volumes destroyed. Re-bootstrapping...")
    cmd_default()


def cmd_down() -> None:
    """Stop all services."""
    tunnel_stop()
    compose("down")
    log("All services stopped.")


def cmd_logs() -> None:
    """Tail logs for all services."""
    compose("logs", "-f", "--tail=100")


def cmd_status() -> None:
    """Show service status."""
    compose("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMANDS = {
    "up": cmd_up,
    "init": cmd_init,
    "seed": cmd_seed,
    "reset": cmd_reset,
    "down": cmd_down,
    "logs": cmd_logs,
    "status": cmd_status,
    "tunnel": cmd_tunnel,
    "tunnel-login": cmd_tunnel_login,
    "tunnel-status": cmd_tunnel_status,
    "tunnel-stop": cmd_tunnel_stop,
}


def main() -> None:
    # Load .env into os.environ for variable interpolation
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    if len(sys.argv) < 2:
        cmd_default()
        return

    command = sys.argv[1]
    if command in ("-h", "--help", "help"):
        print(__doc__)
        return

    handler = COMMANDS.get(command)
    if handler is None:
        print(f"{RED}Unknown command: {command}{RESET}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    handler()


if __name__ == "__main__":
    main()
