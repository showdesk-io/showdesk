# Showdesk Roadmap

> Last updated: 2026-03-07

---

## Legend

| Symbol | Meaning |
|--------|---------|
| Done | [x] |
| In progress | [~] |
| Not started | [ ] |

---

## Phase 0 -- Project Scaffolding (100% done)

Everything needed before writing real feature code. **All done.**

### Infrastructure & DevOps

- [x] Git repository (`showdesk-io/showdesk` on GitHub)
- [x] `.gitignore`, `.env.example`
- [x] `docker-compose.yml` (dev): PostgreSQL, Redis, MinIO, LiveKit, Caddy, Mailpit, Celery
- [x] `docker-compose.prod.yml` (Portainer-ready)
- [x] `dev.py` orchestrator (single entry point: boot, seed, tunnel, widget build)
- [x] `Makefile` with dev commands
- [x] LICENSE (AGPL-3.0), README, CONTRIBUTING

### Backend -- Django Skeleton

- [x] Django config (base/development/production settings)
- [x] Celery + Redis config
- [x] ASGI + Django Channels (WebSocket)
- [x] API routing (`/api/v1/`), JWT auth, S3 storage
- [x] Dockerfile (Python 3.13, FFmpeg)

### Backend -- Django Apps & Models

- [x] `core`: TimestampedModel, UsageRecord, HealthCheck
- [x] `organizations`: Organization, User (OTP auth), Team
- [x] `tickets`: Ticket, TicketMessage, TicketAttachment, Tag, SLAPolicy
- [x] `videos`: VideoRecording (processing pipeline, expiration, transcription fields)
- [x] `knowledge_base`: Category, Article
- [x] `notifications`: WebSocket consumer + signals

### Backend -- Key Features

- [x] UUID primary keys everywhere
- [x] Ticket statuses (open/in_progress/waiting/resolved/closed)
- [x] Ticket priorities (low/medium/high/urgent)
- [x] Ticket source tracking (widget/email/api/agent)
- [x] Internal notes vs public replies
- [x] Technical context (URL, OS, browser, resolution)
- [x] Video expiration, transcription fields (AI-gated)
- [x] Video processing pipeline (Celery tasks)
- [x] SLA policy model, usage tracking for billing
- [x] Widget token auth (`X-Widget-Token`) + submit/upload endpoints
- [x] WebSocket consumer + notification signals

### Frontend -- React Skeleton

- [x] Vite + React 19 + TypeScript + Tailwind CSS
- [x] React Query, Zustand (auth store with persist), React Router 7
- [x] API client with JWT interceptor + auto-refresh
- [x] All TypeScript types for API models
- [x] App layout with sidebar, login page, dashboard, ticket list/detail
- [x] Video player component, status/priority badges
- [x] Dockerfile dev + prod (multi-stage with nginx)

### Widget -- Embeddable JS

- [x] Rollup IIFE build, zero dependencies, vanilla TypeScript
- [x] Auto-init from `<script data-token>` + programmatic API
- [x] Floating action button (configurable color/position)
- [x] Ticket form (name, email, subject, details)
- [x] Screen recording (MediaRecorder, VP9/VP8), camera, mic toggle
- [x] Recording timer + preview
- [x] Auto-captured technical context
- [x] Video upload with progress bar
- [x] Success confirmation with ticket reference
- [x] CSS scoped, no host page conflicts

---

## Phase 1 -- MVP (make it work end-to-end)

### Backend

- [x] Auto-migrations on startup (via `dev.py`)
- [x] Seed data command (`python manage.py seed`)
- [x] Atomic ticket reference counter
- [x] Pagination on all endpoints
- [x] Email notification: new ticket (Celery task, all agents notified)
- [x] Email notification: agent reply (notify requester)
- [x] Email notification: requester reply (notify assigned agent)
- [x] Email notification: ticket assigned (notify agent)
- [x] Email notification: ticket resolved (notify requester)
- [x] WebSocket signals wired in all ticket views
- [x] API tests: 60 pytest tests (tickets, widget, messages, orgs, users, invite, toggle, reopen)
- [x] Model tests + factory_boy factories
- [ ] Rate limiting on widget endpoints
- [ ] File upload validation (size, type)
- [ ] Video duration validation against org settings
- [ ] Celery Beat schedule for expired video cleanup

### Frontend

- [x] Auth guard (redirect to /login)
- [x] Dashboard with live stats
- [x] Ticket list page + filters (status, priority, search)
- [x] Ticket creation form (agent-side, modal)
- [x] Ticket detail + message thread (reply + internal note)
- [x] Ticket assignment UI (agent + team dropdowns)
- [x] Ticket status actions (resolve, close, reopen)
- [x] Team management page (CRUD, agent list)
- [x] Settings page: Agents tab (invite, deactivate, role change)
- [x] Settings page: Widget tab (color, position, greeting, embed snippet, token regen)
- [x] Settings page: Organization tab (name, slug, domain)
- [ ] Real-time ticket updates via WebSocket (backend ready, frontend not wired)
- [ ] Video player wired to real video URLs
- [ ] Agent video reply (record + attach to message)
- [ ] File attachment upload on messages
- [ ] Tag management (create, assign, filter)
- [ ] SLA policy editor
- [ ] Keyboard shortcuts
- [ ] Bulk actions on ticket list
- [ ] Responsive layout
- [ ] Dark mode (optional)

### Widget

- [x] File attachment upload
- [x] Form validation + error handling + loading states
- [x] Upload progress indicator
- [x] E2E browser tests (Playwright, 19 tests)
- [ ] Screenshot capture button
- [ ] Retry on upload failure
- [ ] Configurable max recording duration
- [ ] i18n support
- [ ] Accessibility (ARIA, keyboard nav, focus trap)

### DevOps

- [x] CI pipeline (GitHub Actions: lint, test, build)
- [x] Health check endpoint
- [ ] Docker image build + push in CI
- [ ] Automated migrations on deploy
- [ ] Logging and monitoring (structured JSON)
- [ ] Backup strategy docs

### Tests

- [x] Backend: 60 pytest tests (API + models)
- [x] Frontend: 15 Vitest tests (components + stores)
- [x] E2E: 19 Playwright tests (widget demo, auth, API health)
- Total: **94 tests**

---

## Phase 2 -- Admin Console

### Org Admin (per-organization settings)

- [x] P0: Agent management (invite, deactivate, roles)
- [x] P0: Team management (CRUD, assign agents)
- [x] P0: Widget configuration (colors, position, embed snippet, token regen)
- [ ] P1: Organization branding (logo, primary color, white-label)
- [ ] P1: Custom domain for widget/portal
- [ ] P1: Tags & categories management
- [ ] P1: Canned responses / macros
- [ ] P2: SLA policy editor
- [ ] P2: Notification preferences (per-agent, webhooks)
- [ ] P2: Audit log
- [ ] P3: Automation rules / triggers
- [ ] P3: Data export (CSV/JSON)
- [ ] P3: GDPR compliance tools

### Platform Admin (SaaS operator panel)

- [ ] P0: Organization list (create, suspend, delete)
- [ ] P0: Organization detail (usage stats)
- [ ] P1: Usage & quotas dashboard
- [ ] P1: Billing / Plans management
- [ ] P1: Feature flags per tenant
- [ ] P2: Global monitoring dashboard
- [ ] P2: Impersonation ("login as")
- [ ] P3: Platform-wide announcements
- [ ] P3: Tenant data migration tools

---

## Phase 3 -- Post-MVP Enhancements

- [ ] Knowledge base: public portal
- [ ] Knowledge base: smart deflection in widget
- [ ] Video annotations / timeline markers
- [ ] Customer satisfaction (CSAT) surveys
- [ ] Ticket merge
- [ ] Ticket followers / CC
- [ ] Custom fields on tickets
- [ ] Reporting & analytics dashboard
- [ ] Multi-language support (i18n)
- [ ] SSO / SAML / OAuth
- [ ] Rate limiting + usage quotas
- [ ] Webhook integrations (Slack, Discord)

---

## Phase 4 -- AI Layer (Cloud-only, behind feature flags)

- [ ] Whisper transcription (self-hosted or managed API)
- [ ] AI ticket summary generation
- [ ] AI triage / auto-categorization
- [ ] Smart video redaction (PII detection)
- [ ] Sentiment analysis
- [ ] AI-powered search (tickets + KB)
- [ ] User-provided API keys (bring your own OpenAI/Anthropic)

---

## Summary

| Area | Progress | What's done | What's left |
|------|----------|-------------|-------------|
| Scaffolding | **100%** | All infra, Docker, CI, docs | -- |
| Backend API | **~95%** | Models, views, tasks, seeds, email notifs, WebSocket signals | Rate limiting, file validation, Celery Beat |
| Frontend | **~85%** | Auth, tickets CRUD, assignment, status, settings, teams | WebSocket, video player, tags, shortcuts |
| Widget | **~90%** | Full form, recording, upload, e2e tests | Screenshot, i18n, a11y |
| Tests | **~80%** | 94 tests (pytest + Vitest + Playwright) | Video API tests, more frontend tests |
| Admin (org) | **~40%** | Agent/team CRUD, widget config | Tags, canned responses, SLA, audit log |
| Admin (platform) | **0%** | -- | Everything |
| Post-MVP | **0%** | -- | Everything |
| AI | **0%** | Models/flags ready | All implementation |

### Next priorities

1. Real-time ticket updates (wire WebSocket to frontend)
2. Tag management UI
3. Rate limiting on widget endpoints
4. Celery Beat for video cleanup
5. Platform admin console (P0: org list + details)

---

*This roadmap is a living document. Last updated: 2026-03-07.*
