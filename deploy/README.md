# Deploying Showdesk on your own server

This directory contains everything needed to run Showdesk on a single
Linux host with Docker Compose, provisioned with
[pyinfra](https://pyinfra.com) and deployed from GitHub Actions over SSH.
Nothing here is required: `docker compose -f docker-compose.prod.yml up -d`
on any Docker host works too (see the main README).

```
deploy/
├── postgres/                   # PostgreSQL + WAL-G image (PITR backups to S3)
├── pyinfra/
│   ├── bootstrap.py            # one-off host preparation (idempotent)
│   └── inventory.example.py    # copy to inventory.py and adapt
└── remote-deploy.sh            # pulls a tag, restarts, health-checks, rolls back
```

## Recommended topology

Keep media on S3 and either use a managed PostgreSQL, or run PostgreSQL
on the host with continuous WAL archiving to S3 (point-in-time recovery).
Redis stays local to the stack as a cache / Celery broker.

| Need | `.env` / profile |
|---|---|
| Managed PostgreSQL + S3, local Redis | `COMPOSE_PROFILES=redis` |
| Local PostgreSQL with PITR backups, S3 for media | `COMPOSE_PROFILES=redis,postgres,backup` (see [postgres/README.md](postgres/README.md)) |
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

## 2. Configure the GitHub Environments

`main` deploys to the `production` environment, `develop` to
`development`. Create the environments you need (Settings → Environments),
restrict each one to its branch, and set the repository variable
`DEPLOY_ENABLED=true`.

Deployment settings are read from one of two sources, selected per
environment by the variable `SECRETS_PROVIDER`.

### Option A -- GitHub secrets (`SECRETS_PROVIDER=github`, default)

| Kind | Name | Value |
|---|---|---|
| Secret | `DEPLOY_HOST` | server hostname or IP |
| Secret | `DEPLOY_SSH_KEY` | private key whose public half is in `deploy_authorized_keys` |
| Secret | `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -t ed25519 <host>` |
| Secret | `ENV_FILE` | the full `.env` (see `.env.example`) |
| Secret | `TLS_CERT` / `TLS_KEY` | optional custom certificate (PEM) |

Simple, but GitHub secrets are write-only: you cannot read back what is
deployed.

### Option B -- Scaleway Secret Manager (`SECRETS_PROVIDER=scaleway`)

Keep the configuration readable and versioned in Secret Manager; GitHub
only stores a read-only API key.

1. In a Scaleway project dedicated to the environment, create opaque
   secrets under the path `/deploy`: `host`, `ssh-key`, `known-hosts`,
   `env`, and optionally `tls-cert`, `tls-key` (same contents as option A).
2. Create an IAM application with the `SecretManagerSecretAccess` and
   `SecretManagerReadOnly` permission sets on that project only, and an
   API key for it.
3. In the GitHub environment: secret `SCW_SECRET_KEY` (the API key's
   secret), variables `SCW_PROJECT_ID`, and optionally `SCW_REGION`
   (default `fr-par`) and `SCW_SECRETS_PATH` (default `/deploy`).

Changing the configuration = adding a new secret version, then re-running
the deploy. Previous versions stay available for rollback.

| Variable | Default |
|---|---|
| `DEPLOY_USER` / `DEPLOY_PATH` | `deploy` / `/opt/showdesk` |

Secrets are never exposed to workflows triggered from forks, and are
masked in logs.

## 3. Deploy

Every push to `main` (production) or `develop` (development) runs
`.github/workflows/release.yml`:

1. CI (lint + tests) -- a red commit stops here;
2. images built and pushed to GHCR, tagged with the short SHA (and `latest`);
3. `docker-compose.prod.yml`, `.env`, certificates and `remote-deploy.sh`
   are copied to the host, which pulls the tag, restarts the stack, waits
   for the backend health check and rolls back to the previous tag on failure.

**Rollback / manual deploy**: Actions → Release → Run workflow, with the tag
and the target environment.

## TLS

By default Caddy obtains a Let's Encrypt certificate for
`SHOWDESK_DOMAIN`. Behind a proxy that terminates TLS (e.g. Cloudflare in
"Full (strict)" mode), provide an origin certificate instead via the
`TLS_CERT` / `TLS_KEY` secrets and set in the `.env`:

```bash
CADDY_TLS_DIRECTIVE="tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem"
```

## Staging / development hosts

Add `mailpit` to `COMPOSE_PROFILES` and point `EMAIL_HOST=mailpit`,
`EMAIL_PORT=1025`, `EMAIL_USE_SSL=False`, `EMAIL_USE_TLS=False`: no email
leaves the host. The Mailpit UI only listens on the host's loopback:

```bash
ssh -L 8025:127.0.0.1:8025 deploy@<host>   # then open http://localhost:8025
```

## Running two stacks on one database

Celery Beat must run exactly once per database. While migrating between
hosts, set `CELERY_BEAT_REPLICAS=0` on the new host until the old one is
stopped.
