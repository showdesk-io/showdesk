# Deploying Showdesk on your own server

This directory contains everything needed to run Showdesk on a single
Linux host with Docker Compose, provisioned with
[pyinfra](https://pyinfra.com) and deployed from GitHub Actions over SSH.
Nothing here is required: `docker compose -f docker-compose.prod.yml up -d`
on any Docker host works too (see the main README).

```
deploy/
├── pyinfra/
│   ├── bootstrap.py            # one-off host preparation (idempotent)
│   └── inventory.example.py    # copy to inventory.py and adapt
└── remote-deploy.sh            # pulls a tag, restarts, health-checks, rolls back
```

## Recommended topology

Keep the application host **stateless**: PostgreSQL and S3 on managed
services (or a separate, backed-up host), Redis local to the stack as a
cache / Celery broker. Replacing the host then only means re-running the
bootstrap and the deploy job.

| Need | `.env` / profile |
|---|---|
| Managed PostgreSQL + S3, local Redis | `COMPOSE_PROFILES=redis` |
| Everything on the host | `COMPOSE_PROFILES=local` |
| Portainer stack with auto-redeploy | `COMPOSE_PROFILES=portainer` (+ `PORTAINER_*`) |

## 1. Prepare the host (pyinfra)

Requirements: Ubuntu 24.04+ with root SSH access. LXC containers work
when created **unprivileged with `nesting=1,keyctl=1`** (Docker needs both).

```bash
cp deploy/pyinfra/inventory.example.py deploy/pyinfra/inventory.py   # git-ignored
# edit host, SSH keys, firewall allow-lists
uvx pyinfra deploy/pyinfra/inventory.py deploy/pyinfra/bootstrap.py
```

The bootstrap installs Docker from the official repository, creates the
`deploy` user and `/opt/showdesk`, disables password SSH logins, enables
UFW + fail2ban and unattended security upgrades. When the host sits behind
the Cloudflare proxy, set `http_allow_cidrs = "cloudflare"` so ports 80/443
only accept Cloudflare's ranges (enforced in the `DOCKER-USER` chain,
since Docker-published ports bypass UFW).

## 2. Configure the GitHub Environment

Create an environment named `production` (Settings → Environments),
restrict it to the `main` branch, then add:

| Kind | Name | Value |
|---|---|---|
| Variable (repository) | `DEPLOY_ENABLED` | `true` |
| Secret | `DEPLOY_HOST` | server hostname or IP |
| Secret | `DEPLOY_SSH_KEY` | private key whose public half is in `deploy_authorized_keys` |
| Secret | `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -t ed25519 <host>` |
| Secret | `ENV_FILE` | the full production `.env` (see `.env.example`) |
| Secret | `TLS_CERT` / `TLS_KEY` | optional custom certificate (PEM) |
| Variable | `DEPLOY_USER` / `DEPLOY_PATH` | optional, default `deploy` / `/opt/showdesk` |

Secrets are never exposed to workflows triggered from forks, and are
masked in logs.

## 3. Deploy

Every push to `main` runs `.github/workflows/release.yml`:

1. CI (lint + tests) -- a red commit stops here;
2. images built and pushed to GHCR, tagged with the short SHA (and `latest`);
3. `docker-compose.prod.yml`, `.env`, certificates and `remote-deploy.sh`
   are copied to the host, which pulls the tag, restarts the stack, waits
   for the backend health check and rolls back to the previous tag on failure.

**Rollback**: Actions → Release → Run workflow, with the tag to redeploy.

## TLS

By default Caddy obtains a Let's Encrypt certificate for
`SHOWDESK_DOMAIN`. Behind a proxy that terminates TLS (e.g. Cloudflare in
"Full (strict)" mode), provide an origin certificate instead via the
`TLS_CERT` / `TLS_KEY` secrets and set in the `.env`:

```bash
CADDY_TLS_DIRECTIVE="tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem"
```

## Running two stacks on one database

Celery Beat must run exactly once per database. While migrating between
hosts, set `CELERY_BEAT_REPLICAS=0` on the new host until the old one is
stopped.
