<div align="center">

# Showdesk

**The open-source helpdesk with native video support.**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![GitHub Stars](https://img.shields.io/github/stars/showdesk-io/showdesk?style=social)](https://github.com/showdesk-io/showdesk)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/showdesk-io/showdesk/blob/main/CONTRIBUTING.md)

*Show, don't type.* Users record their screen to explain issues. Agents see exactly what happened. Problems get solved faster.

[Website](https://showdesk.io) | [Documentation](https://github.com/showdesk-io/showdesk/wiki) | [Contributing](./CONTRIBUTING.md) | [Organization](https://github.com/showdesk-io)

</div>

---

## What is Showdesk?

Showdesk is an open-source helpdesk platform where **video is the primary medium**, not an afterthought. Users can submit support tickets with a screen recording (+ webcam + microphone) directly from an embeddable widget, without leaving your product.

### Key Features

- **Video-first tickets** — Users record their screen, webcam, and microphone in one click
- **Embeddable widget** — A single `<script>` tag, zero dependencies, works everywhere
- **Auto-captured context** — Browser, OS, URL, screen resolution captured automatically
- **Agent dashboard** — Fast, keyboard-friendly interface for processing tickets
- **Internal notes** — Collaborate with your team without the requester seeing
- **SLA policies** — Define response and resolution time targets per priority
- **Knowledge base** — Publish articles for self-service support
- **Real-time updates** — WebSocket notifications for new tickets and messages
- **Privacy by design** — Video expiration, self-hosted first, no hidden telemetry
- **100% self-hostable** — Every feature works without any external dependency

### Why Showdesk?

| | Traditional Helpdesk | Showdesk |
|---|---|---|
| Issue reporting | "Please describe the bug" | User records their screen showing the bug |
| Context gathering | "What browser are you using?" | Automatically captured |
| Understanding | Read a wall of text | Watch a 30-second video |
| Empathy | Ticket #4521 | See the person, hear their frustration |

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Python 3.10+ (for the dev orchestrator)

### Setup

```bash
# Clone the repository
git clone https://github.com/showdesk-io/showdesk.git
cd showdesk

# Bootstrap and start everything
python dev.py
```

That's it. The script handles everything:

1. Creates `.env` from `.env.example` if missing
2. Starts infrastructure (PostgreSQL, Redis, MinIO)
3. Waits for health checks
4. Creates S3 buckets
5. Starts all application services
6. Runs database migrations
7. Seeds the database with demo data

Once ready, open **http://localhost** and log in:

| | |
|---|---|
| **Email** | `admin@showdesk.local` |
| **Password** | `showdesk123` |

### Services

All traffic goes through a single entry point via [Caddy](https://caddyserver.com/) reverse proxy:

| Service | URL | Description |
|---|---|---|
| **App** | [http://localhost](http://localhost) | Frontend + API (unified) |
| **MinIO Console** | [http://localhost:9001](http://localhost:9001) | S3 storage admin |
| **LiveKit** | `ws://localhost:7880` | WebRTC signaling |

No ports exposed for PostgreSQL, Redis, or internal services — everything communicates over the Docker network.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Caddy (port 80/443)                   │
│                 Reverse Proxy + Auto TLS                 │
└────────┬──────────────┬──────────────────┬──────────────┘
         │              │                  │
    /api/* /admin/*    /ws/*          everything else
    /static/*           │                  │
         │              │                  │
   ┌─────▼─────┐  ┌────▼─────┐  ┌────────▼────────┐
   │  Backend   │  │  Backend  │  │    Frontend     │
   │  (Daphne)  │  │ (WS/ASGI)│  │   (Vite dev)    │
   └─────┬──────┘  └──────────┘  └─────────────────┘
         │
    ┌────┼─────────────┐
    │    │              │
┌───▼──┐ ┌──▼───┐ ┌────▼────┐
│Postgres│ │Redis │ │  MinIO  │
└────────┘ └──────┘ └─────────┘
```

```
showdesk/
├── backend/           # Django + DRF + Celery + Channels
├── frontend/          # React + TypeScript + Tailwind
├── widget/            # Embeddable vanilla TS widget
├── docker/            # Caddyfile, LiveKit config
├── docker-compose.yml # Dev stack
├── docker-compose.prod.yml
├── dev.py             # Dev orchestrator
└── Makefile           # Shortcuts
```

### Tech Stack

| Component | Technology |
|---|---|
| Backend | Django 5 · Django REST Framework · Celery |
| Database | PostgreSQL 17 |
| Cache / Broker | Redis 8 |
| Frontend | React 19 · TypeScript · Tailwind CSS · Vite |
| Widget | Vanilla TypeScript · Rollup (single file IIFE) |
| Reverse Proxy | Caddy (auto HTTPS in prod) |
| Video Recording | MediaRecorder API · LiveKit (optional) |
| Video Processing | FFmpeg via Celery workers |
| Video Storage | S3-compatible (MinIO dev, any S3 prod) |
| Real-time | Django Channels · WebSocket |
| Transcription | Whisper (optional, AI feature) |

### Widget Integration

Install via npm:

```bash
npm install @showdesk/widget
```

```javascript
import { init, open } from "@showdesk/widget";

init({
  token: "your-organization-api-token",
  user: { id: "usr_123", name: "Jane", email: "jane@example.com" },
});
```

Or use the CDN with a single script tag (no build step required):

```html
<script
  src="https://unpkg.com/@showdesk/widget/dist/widget.js"
  data-token="your-organization-api-token"
  data-color="#6366F1"
  data-position="bottom-right">
</script>
```

Or initialize programmatically:

```javascript
Showdesk.init({
  token: "your-organization-api-token",
  hideButton: true, // Use your own trigger
});

// Bind to your own button
document.getElementById("my-help-btn").addEventListener("click", () => {
  Showdesk.open();
});
```

## Business Model

Showdesk follows an **open-core model**:

- **Self-hosted**: 100% free, all core features, forever
- **Cloud**: Same product, hosted by us, with a generous free tier
- **Cloud-only**: AI features requiring GPU infrastructure (managed transcription, AI triage, smart video redaction, sentiment analysis)

All core features work without any external API calls. AI features are behind a feature flag (`AI_ENABLED=False` by default).

## Development

### Dev Orchestrator (`dev.py`)

The single entry point for the development environment:

```bash
python dev.py            # Full bootstrap (first run)
python dev.py up         # Start services (skip init if already done)
python dev.py down       # Stop all services
python dev.py reset      # Nuke volumes and re-bootstrap
python dev.py seed       # Re-seed database with demo data
python dev.py logs       # Tail all logs
python dev.py status     # Show service status
```

On first run, `dev.py` creates a `.dev-initialized` marker. Subsequent `python dev.py up` calls skip initialization for faster startup. Delete the marker or run `python dev.py reset` to force a full re-init.

### Makefile Shortcuts

All dev.py commands are also available via Make:

```bash
make dev             # python dev.py (full bootstrap)
make up              # python dev.py up
make down            # python dev.py down
make reset           # python dev.py reset
make logs            # python dev.py logs
```

Additional shortcuts for common tasks:

```bash
make migrate         # Run database migrations
make makemigrations  # Generate new migrations
make shell           # Django shell (shell_plus)
make test            # Run backend tests
make test-cov        # Tests with coverage report
make lint            # Ruff linter
make format          # Ruff formatter
make build-widget    # Build widget bundle
```

### Running Tests

```bash
make test            # Backend tests (pytest)
make test-cov        # Backend tests with coverage
```

### Production Deployment

The production stack uses pre-built images from `ghcr.io` and is designed for deployment via [Portainer](https://www.portainer.io/) or `docker compose`.

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env: set DJANGO_SECRET_KEY, DATABASE_URL, S3_*, SHOWDESK_DOMAIN, etc.

# Deploy with external managed databases (PostgreSQL, Redis, S3)
docker compose -f docker-compose.prod.yml up -d

# Or deploy all-in-one with local databases
docker compose -f docker-compose.prod.yml --profile local up -d
```

Services and images:

| Service | Image | Role |
|---|---|---|
| `caddy` | `caddy:2-alpine` | Reverse proxy, automatic HTTPS via Let's Encrypt |
| `migrate` | `ghcr.io/showdesk-io/showdesk-backend` | One-shot: runs migrations then exits |
| `backend` | `ghcr.io/showdesk-io/showdesk-backend` | Django API + WebSocket (Gunicorn/Uvicorn) |
| `celery-worker` | `ghcr.io/showdesk-io/showdesk-backend` | Async task processing |
| `celery-beat` | `ghcr.io/showdesk-io/showdesk-backend` | Periodic task scheduler |
| `frontend` | `ghcr.io/showdesk-io/showdesk-frontend` | React SPA (Nginx) |

Optional services (profile `local`):

| Service | Image | When to use |
|---|---|---|
| `postgres` | `postgres:17-alpine` | No managed PostgreSQL available |
| `redis` | `redis:8-alpine` | No managed Redis available |
| `minio` | `minio/minio` | No managed S3 available |

The backend image uses a unified entrypoint (`entrypoint.sh`) that accepts a mode argument: `server`, `worker`, `beat`, or `migrate`. Set `RUN_MIGRATIONS=true` in `.env` to apply migrations automatically on deploy.

## Contributing

We welcome contributions! Please read our [Contributing Guide](./CONTRIBUTING.md) before submitting a pull request.

## License

Showdesk is licensed under the [GNU Affero General Public License v3.0](./LICENSE).

This means you can use, modify, and distribute Showdesk freely, but if you modify and deploy it as a network service, you must make your changes available under the same license.

---

<div align="center">

Built with care by the [Showdesk](https://github.com/showdesk-io) community.

</div>
