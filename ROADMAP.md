# Showdesk Roadmap

> Last updated: 2026-03-07

This document tracks the overall progress of the Showdesk project, from initial scaffolding to a fully functional MVP and beyond.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| :white_check_mark: | Done |
| :construction: | In progress / partially done |
| :hourglass: | Not started yet |

---

## Phase 0 — Project Scaffolding

Everything needed before writing real feature code.

### Infrastructure & DevOps

| Task | Status | Notes |
|------|--------|-------|
| Git repository initialization | :white_check_mark: | `main` branch, remote on `showdesk-io/showdesk` |
| `.gitignore` (Python, Node, IDE, env) | :white_check_mark: | |
| `.env.example` with all variables | :white_check_mark: | |
| `docker-compose.yml` (dev) | :white_check_mark: | PostgreSQL, Redis, MinIO, LiveKit, backend, frontend, Celery |
| `docker-compose.prod.yml` | :white_check_mark: | Portainer-ready, managed DB expected |
| LiveKit config (`docker/livekit.yaml`) | :white_check_mark: | |
| `Makefile` with dev commands | :white_check_mark: | `dev`, `stop`, `migrate`, `shell`, `test`, `build-widget`, etc. |
| LICENSE (AGPL-3.0) | :white_check_mark: | |
| `README.md` | :white_check_mark: | Badges, quickstart, architecture, widget usage |
| `CONTRIBUTING.md` | :white_check_mark: | Branch conventions, commit conventions, PR process |
| `ROADMAP.md` | :white_check_mark: | This file |

### Backend — Django Skeleton

| Task | Status | Notes |
|------|--------|-------|
| Django project config (`config/`) | :white_check_mark: | Settings split: `base.py`, `development.py`, `production.py` |
| Celery configuration | :white_check_mark: | `config/celery.py` |
| ASGI + Channels setup | :white_check_mark: | `config/asgi.py` with WebSocket routing |
| API URL routing (`/api/v1/`) | :white_check_mark: | DRF router in `config/api_urls.py` |
| JWT authentication config | :white_check_mark: | `djangorestframework-simplejwt` |
| S3 storage config | :white_check_mark: | `django-storages` with boto3 |
| `Dockerfile` (backend) | :white_check_mark: | Python 3.13, FFmpeg installed |
| `requirements.txt` | :white_check_mark: | All dependencies pinned |

### Backend — Django Apps & Models

| App | Models | Serializers | ViewSets | Admin | Status |
|-----|--------|-------------|----------|-------|--------|
| `core` | `TimestampedModel`, `UsageRecord` | — | `HealthCheckView` | :white_check_mark: | :white_check_mark: |
| `organizations` | `Organization`, `User`, `Team` | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| `tickets` | `Ticket`, `TicketMessage`, `TicketAttachment`, `Tag`, `SLAPolicy` | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| `videos` | `VideoRecording` | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| `knowledge_base` | `Category`, `Article` | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| `notifications` | — (consumers) | — | — | — | :white_check_mark: |

### Backend — Key Features in Models

| Feature | Status | Location |
|---------|--------|----------|
| UUID primary keys on all models | :white_check_mark: | `core.TimestampedModel` |
| Ticket statuses (open/in_progress/waiting/resolved/closed) | :white_check_mark: | `tickets.Ticket` |
| Ticket priorities (low/medium/high/urgent) | :white_check_mark: | `tickets.Ticket` |
| Ticket source tracking (widget/email/api/agent) | :white_check_mark: | `tickets.Ticket` |
| Internal notes vs public replies | :white_check_mark: | `tickets.TicketMessage` |
| Technical context fields (URL, OS, browser, resolution) | :white_check_mark: | `tickets.Ticket` |
| Video expiration (`expires_at`) | :white_check_mark: | `videos.VideoRecording` |
| Video transcription fields (AI-gated) | :white_check_mark: | `videos.VideoRecording` |
| Video processing pipeline (Celery tasks) | :white_check_mark: | `videos.tasks` |
| Expired video cleanup task | :white_check_mark: | `videos.tasks.cleanup_expired_videos` |
| SLA policy model | :white_check_mark: | `tickets.SLAPolicy` |
| Usage tracking for billing | :white_check_mark: | `core.UsageRecord` |
| Widget token authentication | :white_check_mark: | `Organization.api_token` + `X-Widget-Token` header |
| Widget submit endpoint (`/tickets/widget_submit/`) | :white_check_mark: | `tickets.views` |
| Widget video upload endpoint (`/videos/widget_upload/`) | :white_check_mark: | `videos.views` |
| Feature flag `AI_ENABLED` | :white_check_mark: | `settings.base` |
| WebSocket consumer for ticket updates | :white_check_mark: | `notifications.consumers` |
| WebSocket notification signals | :white_check_mark: | `notifications.signals` |

### Frontend — React Skeleton

| Task | Status | Notes |
|------|--------|-------|
| Vite + TypeScript + Tailwind setup | :white_check_mark: | |
| `package.json` with all dependencies | :white_check_mark: | React 19, React Query, Zustand, React Router 7 |
| `tsconfig.json` (strict mode) | :white_check_mark: | Path aliases `@/` |
| Tailwind config with brand colors | :white_check_mark: | Primary indigo palette |
| `Dockerfile` (dev) | :white_check_mark: | |
| `Dockerfile.prod` + nginx | :white_check_mark: | Multi-stage build |
| TypeScript types (`src/types/`) | :white_check_mark: | All API models typed |
| API client with JWT interceptor | :white_check_mark: | Axios + auto-refresh |
| Auth store (Zustand + persist) | :white_check_mark: | |
| React Query hooks for tickets | :white_check_mark: | `useTickets`, `useTicket`, `useCreateMessage`, etc. |
| App layout with sidebar | :white_check_mark: | |
| Login page | :white_check_mark: | |
| Dashboard page (placeholder) | :white_check_mark: | Stats cards, data not wired |
| Ticket list page + filters | :white_check_mark: | Status, priority, search |
| Ticket detail page + message thread | :white_check_mark: | Reply + internal note toggle |
| Video player component | :white_check_mark: | Status-aware, transcription display |
| Status/Priority badge components | :white_check_mark: | |
| Settings page (placeholder) | :white_check_mark: | |

### Widget — Embeddable JS

| Task | Status | Notes |
|------|--------|-------|
| Rollup build config (single IIFE file) | :white_check_mark: | Production minification via terser |
| `tsconfig.json` (strict mode) | :white_check_mark: | |
| Auto-init from `<script data-token>` | :white_check_mark: | |
| Programmatic `Showdesk.init()` / `Showdesk.open()` | :white_check_mark: | |
| `Showdesk.destroy()` cleanup | :white_check_mark: | |
| Floating action button (configurable position/color) | :white_check_mark: | |
| `hideButton` option for custom trigger | :white_check_mark: | |
| Ticket submission modal (name, email, title, description) | :white_check_mark: | |
| Screen recording via MediaRecorder API | :white_check_mark: | VP9/VP8 codec detection |
| Microphone toggle | :white_check_mark: | On by default |
| Camera toggle | :white_check_mark: | |
| Recording timer display | :white_check_mark: | |
| Recording preview (video playback) | :white_check_mark: | |
| Auto-captured technical context | :white_check_mark: | URL, OS, browser, resolution, timezone, language, referrer |
| Ticket submission via API (`/tickets/widget_submit/`) | :white_check_mark: | `X-Widget-Token` auth |
| Video upload via API (`/videos/widget_upload/`) | :white_check_mark: | Multipart form data |
| Success confirmation with ticket reference | :white_check_mark: | Auto-close after 4s |
| CSS scoped under `#showdesk-widget-container` | :white_check_mark: | No host page conflicts |
| Zero external dependencies | :white_check_mark: | Vanilla TS only |

---

## Phase 1 — MVP (functional product)

Make everything actually work end-to-end.

### Backend

| Task | Status | Notes |
|------|--------|-------|
| Generate and run initial migrations | :hourglass: | `makemigrations` + `migrate` |
| Seed data management command | :white_check_mark: | `python manage.py seed` with demo org, agents, tickets |
| Ticket reference auto-increment (robust) | :white_check_mark: | Atomic counter via `Organization.next_ticket_reference()` |
| Email notifications on ticket creation | :hourglass: | Via Celery |
| Email notifications on ticket reply | :hourglass: | |
| Password reset flow | :hourglass: | |
| Pagination on all list endpoints | :white_check_mark: | DRF PageNumberPagination configured |
| Rate limiting on widget endpoints | :hourglass: | Prevent abuse |
| File upload validation (size, type) | :hourglass: | |
| Video duration validation against org settings | :hourglass: | |
| Celery Beat schedule for `cleanup_expired_videos` | :hourglass: | |
| Whisper transcription integration | :hourglass: | Behind `AI_ENABLED` flag |
| API tests (pytest) | :white_check_mark: | Tickets, widget submit, messages, organizations |
| Model tests | :white_check_mark: | Organizations, tickets, videos |
| Factory classes (factory_boy) | :white_check_mark: | All models covered |

### Frontend

| Task | Status | Notes |
|------|--------|-------|
| Auth guard (redirect to login if unauthenticated) | :white_check_mark: | `AuthGuard` component wrapping protected routes |
| Dashboard stats wired to API | :white_check_mark: | Live counts: open, in progress, urgent, total |
| Ticket creation form (agent-side) | :hourglass: | |
| Ticket assignment UI (agent + team picker) | :hourglass: | |
| Ticket status change actions (resolve, close, reopen) | :hourglass: | |
| Video player wired to real video URLs | :hourglass: | |
| Agent video reply (record + attach to message) | :hourglass: | |
| File attachment upload on messages | :hourglass: | |
| Tag management (create, assign, filter) | :hourglass: | |
| Team management page | :white_check_mark: | Teams + agents list with avatars and roles |
| Agent management page | :white_check_mark: | Combined in Team page |
| Settings page: organization branding | :hourglass: | |
| Settings page: widget configuration preview | :hourglass: | |
| Settings page: SLA policy editor | :hourglass: | |
| Keyboard shortcuts for agents | :hourglass: | Navigate tickets, reply, assign |
| Bulk actions on ticket list | :hourglass: | Multi-select, bulk assign/close |
| Real-time ticket updates via WebSocket | :hourglass: | |
| Responsive layout adjustments | :hourglass: | |
| Dark mode (optional) | :hourglass: | |

### Widget

| Task | Status | Notes |
|------|--------|-------|
| File attachment upload (non-video) | :white_check_mark: | File picker with name display |
| Screenshot capture button | :hourglass: | |
| Form validation with user feedback | :white_check_mark: | Red borders, error messages |
| Loading states and error handling | :white_check_mark: | Submit states, error display, retry |
| Upload progress indicator for video | :white_check_mark: | XHR-based with progress bar + percentage |
| Retry on upload failure | :hourglass: | |
| Configurable max recording duration | :hourglass: | Read from org settings |
| i18n support (language detection) | :hourglass: | |
| Accessibility (ARIA, keyboard nav, focus trap) | :hourglass: | |
| E2E browser tests | :hourglass: | |

### DevOps

| Task | Status | Notes |
|------|--------|-------|
| CI pipeline (GitHub Actions) | :white_check_mark: | Backend lint+test, frontend build, widget build |
| Docker image build + push in CI | :hourglass: | |
| Automated migrations on deploy | :hourglass: | |
| Health check endpoint | :white_check_mark: | `/api/v1/health/` |
| Logging and monitoring setup | :hourglass: | Structured JSON logs |
| Backup strategy documentation | :hourglass: | For self-hosters |

---

## Phase 2 — Post-MVP Enhancements

| Feature | Status | Notes |
|---------|--------|-------|
| Knowledge base: public-facing portal | :hourglass: | Standalone page for end-users |
| Knowledge base: smart deflection in widget | :hourglass: | Suggest articles before ticket creation |
| Video annotations / timeline markers | :hourglass: | Agents can annotate specific timestamps |
| Canned responses / macros | :hourglass: | Pre-written reply templates |
| Customer satisfaction (CSAT) surveys | :hourglass: | Post-resolution feedback |
| Ticket merge | :hourglass: | Merge duplicate tickets |
| Ticket followers / CC | :hourglass: | |
| Custom fields on tickets | :hourglass: | Per-organization configurable |
| Automation rules / triggers | :hourglass: | Auto-assign, auto-tag, auto-close |
| Reporting & analytics dashboard | :hourglass: | Resolution time, agent performance, volume |
| Multi-language support (i18n) | :hourglass: | Widget + frontend + KB articles |
| SSO / SAML / OAuth integration | :hourglass: | |
| API v1 rate limiting + usage quotas | :hourglass: | |
| Webhook integrations (Slack, Discord, etc.) | :hourglass: | |

---

## Phase 3 — AI Layer (Cloud-only features)

These features require GPU infrastructure and are behind `AI_ENABLED` / feature flags.

| Feature | Status | Notes |
|---------|--------|-------|
| Whisper transcription (self-hosted) | :hourglass: | Celery worker with GPU |
| Whisper transcription (managed API) | :hourglass: | OpenAI Whisper API |
| AI ticket summary generation | :hourglass: | |
| AI triage / auto-categorization | :hourglass: | |
| Smart video redaction (PII detection) | :hourglass: | |
| Sentiment analysis on video/text | :hourglass: | |
| AI-powered search across tickets + KB | :hourglass: | |
| User-provided API keys for AI features | :hourglass: | Bring your own OpenAI/Anthropic key |

---

## Current Status Summary

| Area | Progress | Detail |
|------|----------|--------|
| **Project scaffolding** | :white_check_mark: **100%** | All files, config, Docker, docs, CI |
| **Backend models & API** | :white_check_mark: **~95%** | Models, serializers, views, tasks, seed command, atomic refs. Missing: migrations run, email notifs |
| **Frontend UI** | :construction: **~75%** | Auth guard, dashboard wired, team page, ticket list/detail. Missing: ticket create form, assignment UI, video reply |
| **Widget** | :white_check_mark: **~90%** | Full flow: form + validation + screen recording + upload progress + file attach. Missing: screenshot, i18n, a11y |
| **DevOps / CI** | :white_check_mark: **~70%** | Docker + GitHub Actions (lint, test, build). Missing: image push, deploy automation |
| **Tests** | :construction: **~50%** | Factories, model tests, API tests for tickets/orgs/widget. Missing: video API tests, frontend tests |
| **Post-MVP features** | :hourglass: **0%** | |
| **AI layer** | :hourglass: **0%** | Models/flags ready, no implementation |

### Immediate Next Steps

1. **Run `make dev` + `make migrate`** — Boot the full stack and verify schema
2. **Run `python manage.py seed`** — Populate with demo data
3. **Test the full widget flow** — Script tag embed -> record -> submit -> appears in dashboard
4. **Ticket creation form (agent-side)** — Agents should be able to create tickets manually
5. **Ticket assignment UI** — Agent and team picker in ticket detail
6. **Email notifications** — Notify on ticket creation and reply
7. **Screenshot capture in widget** — Instant screenshot button alongside recording
8. **Frontend tests** — Add Vitest for React component tests

---

*This roadmap is a living document. Last updated: 2026-03-07.*
