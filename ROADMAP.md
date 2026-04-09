# Showdesk Roadmap

> Last updated: 2026-04-09

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
- [x] `tickets`: Ticket, TicketMessage, TicketAttachment, Tag, SLAPolicy, SavedView
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

## Known Bugs

- [x] **Auth: stale user after re-login** -- logging out then logging in with a different email shows the previous user's data (cached in Zustand/localStorage). Eventually switches to the correct user. The auth store should be fully cleared on logout and refreshed on login.
- [x] **Team page: cross-org user visibility** -- non-superuser agents can see users from other organizations and superusers with no organization. The team list API should filter out users without an organization and scope to the current user's org only.
- [ ] **WebSocket fails on dev.showdesk.io** -- WSS connection to `/ws/tickets/` fails when accessed via Cloudflare proxy. **Root cause: Cloudflare tunnel configuration** -- the frontend code correctly derives WSS URL from `window.location` and Caddy handles WebSocket upgrades natively. Fix requires enabling WebSocket support in Cloudflare Zero Trust tunnel config (not a code issue). Note: `VITE_WS_BASE_URL` env var is defined but unused (can be cleaned up).
- [x] **Widget: screen capture fails** -- screenshot button was disabled ("Coming soon"). Implemented full screenshot capture via getDisplayMedia single-frame, with overlay hiding, thumbnail previews, and backend widget attachment upload endpoint. Also fixed PipCompositor captureStream caching and added video track validation.
- [x] **Widget: modal overlay blocks recording** -- when recording starts, the overlay and modal are now hidden and the FAB is replaced by a compact recording bar (dot + timer + PiP controls + stop) at the FAB position. User can interact freely with the page. On stop, the modal reappears with the recording preview.
- [ ] **Agent dashboard: no real-time updates** -- when viewing a ticket detail, new messages (from widget users) and message deletions do not appear until the page is manually refreshed or the agent navigates away and back. **Root cause:** the WebSocket hook used `invalidateQueries()` which only marks the React Query cache as stale, but with `staleTime: 60s` and `refetchOnWindowFocus: false` (in `main.tsx`), no refetch is triggered while the component is mounted. **Partial fix applied:** switched to `refetchQueries()` in `useWebSocket.ts` (commit `97bd6a6`). **To verify:** confirm WebSocket connection is established, events are received, and `refetchQueries` triggers visible re-renders. If still broken, check: (1) WebSocket not connecting (auth/infra issue), (2) backend not sending notifications (missing `notify_*` calls), (3) React Query `refetchQueries` still not triggering for active observers.

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
- [x] API tests: 88 pytest tests (tickets, widget, messages, orgs, users, tags, attachments, priorities, saved views)
- [x] Model tests + factory_boy factories
- [x] Rate limiting on widget endpoints (10/min submit, 20/min upload)
- [x] Celery Beat schedule for expired video cleanup (every 6 hours)
- [x] File upload validation (size, type: 20 MB limit, blocked executables)
- [x] Video upload validation (size, MIME type)
- [x] Saved views API (CRUD, per-org, personal + shared, unique name validation)
- [x] Filtered ticket stats endpoint (status/priority breakdown, agent workload, avg age)
- [x] S3 public URL rewriting for presigned URLs (custom storage backend)
- [x] Video processing pipeline fix: S3-compatible temp download for FFprobe/FFmpeg
- [ ] Video duration validation against org settings

### Frontend

- [x] Auth guard (redirect to /login)
- [x] Dashboard with live stats
- [x] Ticket list page + filters (status, priority, search, agent, team)
- [x] Ticket list: compact/expanded view modes (toggle)
- [x] Ticket list: inline quick actions (priority, assign, tags)
- [x] Ticket list: inline tag creation in dropdown
- [x] Ticket list: saved filter views (chips bar, save/delete, personal + shared)
- [x] Ticket list: filtered stats popup (KPIs, status/priority bars, agent workload)
- [x] Ticket creation form (agent-side, modal)
- [x] Ticket detail + message thread (reply + internal note)
- [x] Ticket detail: inline tag creation in picker
- [x] Ticket assignment UI (agent + team dropdowns)
- [x] Ticket status actions (resolve, close, reopen)
- [x] Team management page (CRUD, agent list)
- [x] Settings page: Agents tab (invite, deactivate, role change)
- [x] Settings page: Widget tab (color, position, greeting, embed snippet, token regen)
- [x] Settings page: Organization tab (name, slug, domain)
- [~] Real-time ticket updates via WebSocket (JWT auth, auto-reconnect, cache invalidation, toast notifications) -- **see Known Bugs: no real-time updates in ticket detail**
- [x] Video player wired to real video URLs
- [ ] Agent video reply (record + attach to message)
- [x] File attachment upload on messages
- [x] Tag management (CRUD in Settings, assign on tickets, filter in list)
- [ ] SLA policy editor
- [ ] Keyboard shortcuts
- [ ] Bulk actions on ticket list
- [ ] WebSocket URL derived from window.location (no hardcoded env var)
- [ ] Responsive layout
- [ ] Dark mode (optional)

### Widget

- [x] File attachment upload
- [x] Form validation + error handling + loading states
- [x] Upload progress indicator
- [x] E2E browser tests (Playwright, 19 tests)
- [x] Screenshot capture button (getDisplayMedia single-frame capture, hides overlay during capture, thumbnail previews with remove, uploaded as ticket attachment)
- [ ] Retry on upload failure
- [x] Multi-page site support (`data-navigation-mode="mpa"`, popup-based recording)
- [ ] Configurable max recording duration
- [ ] Custom trigger button -- allow the host app to use its own help button instead of the auto-created FAB. `Showdesk.init({ hideButton: true })` already exists; add `Showdesk.open()` / `Showdesk.startRecording()` / `Showdesk.close()` so the host app can drive the full flow programmatically.
- [ ] Video review before submit -- after recording, allow the user to play back the video and decide to keep it, re-record, or discard before submitting the ticket.
- [ ] Bookmarklet mode -- generate a bookmarklet URL (from Settings > Widget) that injects the widget script into any page. Allows clients to test the widget directly on their own site/app without deploying the embed snippet.
- [ ] i18n support
- [ ] Accessibility (ARIA, keyboard nav, focus trap)

### DevOps

- [x] CI pipeline (GitHub Actions: lint, test, build)
- [x] Health check endpoint
- [~] Docker image build + push in CI (workflow created, pending first run)
- [ ] Automated migrations on deploy
- [ ] Logging and monitoring (structured JSON)
- [ ] Backup strategy docs
- [ ] Publish widget to npmjs.com (`@showdesk/widget`) + CDN via unpkg/jsdelivr

### Tests

- [x] Backend: 88 pytest tests (API + models, including saved views)
- [x] Frontend: 15 Vitest tests (components + stores)
- [x] E2E: 19 Playwright tests (widget demo, auth, API health)
- Total: **122 tests**

---

## Phase 2 -- Widget UX Overhaul

Transforming the widget from a simple form into a guided, context-rich support experience.

### Widget: Distribution & API URL (Priority 0 -- prerequisite)

The widget runs on external customer websites and must communicate with the correct Showdesk instance. Each instance (cloud, on-premise, dev) serves its own widget version.

- [x] **Auto-detect API URL from script src**: `getApiUrl()` helper in `widget/src/widget.ts` — priority: `data-api-url` > origin from `src` > `/api/v1` (same-origin fallback).
- [x] **Serve widget at `/cdn/widget.js`**: Route in `docker/Caddyfile` (dev) and inline Caddyfile in `docker-compose.prod.yml` (prod, via `widget_dist` volume).
- [x] **Fix embed snippet in Settings**: `SettingsPage.tsx` now uses `window.location.origin` + `/cdn/widget.js` instead of hardcoded `cdn.showdesk.io`.
- [x] **Add "Preview" button in Settings > Widget**: Opens `/widget-demo?token={api_token}` in a new tab.
- [x] **Demo page auto-load via `?token=`**: Reads `?token=xxx` from URL, auto-fills and loads widget.
- Note: npm publish (`@showdesk/widget`) for cloud SaaS distribution via unpkg/jsdelivr. `/cdn/widget.js` for on-premise and dev instances.

### Widget: Guided Wizard Flow (Priority 1)

Adaptive wizard with branching logic based on issue type.

- [x] Qualification step: issue type selector (bug, question, suggestion, other)
- [x] Adaptive follow-up question per type (e.g. "Is it visible on screen?" for bugs)
- [x] Context-aware capture tools (only show relevant options per issue type)
- [x] Contact step (name, email -- pre-filled from host app identity)
- [x] Suggestion type: text + optional video

### Widget: Camera Picture-in-Picture (Priority 1)

Loom-style webcam bubble composited on screen recording via Canvas API.

- [x] Canvas compositing: draw screen + camera bubble in requestAnimationFrame loop
- [~] Draggable/resizable camera bubble (circle, corner presets, 2 sizes -- no free-form drag)
- [x] Single output stream from canvas -> MediaRecorder -> one WebM file
- [x] Camera-only recording mode (no screen share)
- [x] Camera preview before recording starts

### Widget: Automatic Technical Context (Priority 1)

Silent capture of debug data from script load (before widget opens).

- [x] Console error/warning capture from script load (not from widget open)
- [x] Network error capture (4xx/5xx) with URL, status, timing from script load
- [x] Browser metadata enrichment (URL, browser, OS, resolution)
- [x] Attach context as structured JSON to ticket (context_metadata JSONField)
- [x] Agent-side display: collapsible "Technical Context" panel with console errors, network errors

### Widget: User Identity from Host App (Priority 1)

Allow host applications to pass authenticated user info at widget init.

- [x] `Showdesk.init({ user: { id, name, email } })` programmatic API
- [x] `data-user-*` attributes on script tag (alternative)
- [x] Pre-fill contact fields from identity (skip contact step if complete)
- [x] Backend: link tickets to known external user ID for tracking (`external_user_id` field)
- [x] Backend: endpoint to fetch previous tickets by external user ID (`widget_tickets` action + `external_user_id` filter)

### Widget: MPA Recording Persistence (Priority 2)

On traditional multi-page sites, page navigation destroys the JS context and any ongoing recording. Popup-based recording solves this.

- [x] `data-navigation-mode` config attribute (`spa` default, `mpa` for multi-page)
- [x] Popup-based recording: `window.open()` with blob URL (same-origin for BroadcastChannel)
- [x] BroadcastChannel protocol for popup ↔ widget communication
- [x] Re-attachment on navigation: widget probes for existing popup on each page load
- [x] Self-upload: popup uploads recording autonomously via XHR (works even off-site)
- [x] Duration guard: popup notifies user every 5 minutes of ongoing recording
- [x] Popup FAB controller: lightweight stop + timer on the main page FAB
- [x] Graceful fallback: if popup is blocked, falls back to in-page recording (SPA mode)
- [x] Stop from main widget closes popup and triggers upload
- [ ] Audio recording MPA mode (mic-only popup variant)

### Widget: Ticket History in Widget (Priority 2)

When user identity is known, show previous tickets and agent replies directly in widget.

- [ ] On widget open: check for open/recent tickets with pending agent replies
- [ ] Notification badge on widget FAB when unread replies exist
- [ ] Ticket list view in widget (user's own tickets)
- [ ] Ticket detail view in widget (messages thread, read-only)
- [ ] Mark replies as read when viewed in widget

### Widget: Screenshot + Annotation (Priority 2)

Alternative to video for simple visual issues, Marker.io-style.

- [ ] Screenshot capture (html2canvas or native browser API)
- [ ] Annotation overlay: arrows, rectangles, text, freehand draw
- [ ] Blur/redact tool for sensitive data
- [ ] Multiple screenshots per ticket

### Widget: Multi-attachments (Priority 2)

- [ ] Multiple screenshots + videos in a single ticket
- [ ] Attachment gallery with add/remove before submit

### Widget: Session Replay (Priority 3)

Lightweight replay of user interactions leading up to the bug report.

- [ ] Capture DOM events (clicks, scrolls, navigation) from script load
- [ ] Configurable buffer (last N seconds / last N events)
- [ ] Replay viewer in agent dashboard (event timeline, not video)
- [ ] Privacy: auto-mask sensitive input fields

### Widget: Video Timeline Markers (Priority 3)

- [ ] User can add markers during recording to flag key moments
- [ ] Markers stored as timestamps with optional label
- [ ] Agent-side player: clickable markers to jump to moments

---

## Phase 3 -- Admin Console

### Agent Groups & Management

- [ ] P1: Agent groups -- create named groups of agents (e.g. "Support L1", "Billing", "Technical")
- [ ] P1: Group managers -- one or more agents designated as manager of a group (can manage members, view group stats, receive escalations)
- [ ] P1: Assign tickets to groups (in addition to individual agents/teams)
- [ ] P2: Group-based routing rules (auto-assign tickets to groups based on type/tags)
- [ ] P2: Group dashboards (manager view: group workload, SLA compliance, agent activity)

### Notification System

Full brainstorm on notifications: who gets notified, when, and via which channel.

**Recipients:**
- Agents (assigned agent, group members, all agents)
- Group managers
- Ticket requester (end-user who created the ticket)
- Organization admins

**Trigger events:**
- [ ] Ticket created (new ticket submitted via widget, email, or API)
- [ ] Ticket assigned / reassigned (to agent, team, or group)
- [ ] Agent reply (public response added to ticket)
- [ ] Requester reply (end-user responds to ticket)
- [ ] Internal note added
- [ ] Ticket status change (open → in_progress, resolved, closed, reopened)
- [ ] Ticket priority change (especially escalation to urgent)
- [ ] SLA breach warning (approaching SLA deadline)
- [ ] SLA breach (SLA deadline exceeded)
- [ ] Ticket escalated (to manager or higher-tier group)
- [ ] Report generated (scheduled or on-demand analytics report)
- [ ] Agent invited / deactivated
- [ ] CSAT response received
- [ ] Ticket merged
- [ ] Bulk action performed (mass close, mass reassign)

**Channels:**
- [ ] Email (default, always available)
- [ ] In-app (WebSocket real-time notifications, already partially implemented)
- [ ] Webhook (HTTP POST to customer-configured URL, for custom integrations)
- [ ] Slack (native integration: post to channel or DM)
- [ ] Discord (webhook-based integration)
- [ ] Microsoft Teams (webhook or app integration)
- [ ] SMS (via Twilio or similar, for urgent/on-call notifications)
- [ ] Mobile push notifications (future, requires mobile app)

**Configuration:**
- [ ] Per-agent notification preferences (opt-in/out per event type × channel)
- [ ] Per-organization defaults (admin sets baseline, agents can override)
- [ ] Quiet hours / Do Not Disturb schedules
- [ ] Notification frequency control (instant, digest: hourly/daily)
- [ ] Channel-specific templates (customizable email/Slack message format)
- [ ] Escalation chains (if no response in X minutes, notify next level)

### Org Admin (per-organization settings)

- [x] P0: Agent management (invite, deactivate, roles)
- [x] P0: Team management (CRUD, assign agents)
- [x] P0: Widget configuration (colors, position, embed snippet, token regen)
- [ ] P1: Widget integration code examples & generator in Settings > Widget (embed snippets for React/Angular/Vue/vanilla JS + backend HMAC generation examples for Node/Python/PHP/Ruby)
- [ ] P1: Organization branding (logo, primary color, white-label)
- [ ] P1: Custom domain for widget/portal
- [x] P1: Tags & categories management
- [x] P1: Custom priority management (CRUD, custom colors, per-org)
- [ ] P1: Canned responses / macros
- [ ] P2: SLA policy editor
- [ ] P2: Notification preferences (per-agent, webhooks)
- [ ] P2: Audit log
- [ ] P3: Automation rules / triggers
- [ ] P3: Data export (CSV/JSON)
- [ ] P3: GDPR compliance tools

### Platform Admin (SaaS operator panel)

- [x] P0: Organization list (create, suspend, delete)
- [x] P0: Organization detail (usage stats)
- [ ] P1: Usage & quotas dashboard
- [ ] P1: Billing / Plans management
- [ ] P1: Feature flags per tenant
- [ ] P2: Global monitoring dashboard
- [x] P1: Impersonation -- org switcher in sidebar, X-Showdesk-Org header, middleware + get_active_org helper
- [x] P1: Conditional sidebar -- superusers without an organization only see Admin; superusers attached to an org (or impersonating) see both Admin and the standard nav
- [ ] P3: Platform-wide announcements
- [ ] P3: Tenant data migration tools

---

## Phase 4 -- Post-MVP Enhancements

- [ ] Knowledge base: public portal
- [ ] Knowledge base: smart deflection in widget
- [ ] Customer satisfaction (CSAT) surveys
- [ ] Ticket merge
- [ ] Ticket followers / CC
- [ ] Custom fields on tickets
- [ ] Reporting & analytics dashboard
- [ ] Multi-language support (i18n)
- [ ] SSO / SAML / OAuth
- [ ] Webhook integrations (Slack, Discord)

---

## Phase 5 -- AI Layer (Cloud-only, behind feature flags)

- [ ] Whisper transcription (self-hosted or managed API)
- [ ] AI ticket summary generation
- [ ] AI triage / auto-categorization
- [ ] Smart video redaction (PII detection)
- [ ] Sentiment analysis
- [ ] AI-powered search (tickets + KB)
- [ ] AI first-responder in widget (auto-reply based on context + KB)
- [ ] User-provided API keys (bring your own OpenAI/Anthropic)

---

## Summary

| Area | Progress | What's done | What's left |
|------|----------|-------------|-------------|
| Scaffolding | **100%** | All infra, Docker, CI, docs | -- |
| Backend API | **~99%** | Models, views, tasks, seeds, email, WebSocket, rate limiting, Celery Beat, file validation, custom priorities, saved views, stats, S3 fix, external_user_id, context_metadata, issue_type, widget_tickets endpoint, platform admin API, impersonation | Video duration validation |
| Frontend | **~97%** | Auth, tickets CRUD, assignment, status, settings, teams, WebSocket, tags, inline actions, view modes, priorities, video player, file attachments, saved views, stats modal, agent/team filters, inline tag creation, technical context panel, issue type badge, platform admin page, org switcher, fixed embed snippet, widget preview button | Shortcuts, bulk actions, agent video reply, SLA editor |
| Widget | **~98%** | Full form, recording, upload, e2e tests, guided wizard, camera PiP (compositing + camera-only + preview), console/network collectors, user identity (API + data-user-*), adaptive steps, API URL auto-detect, /cdn/widget.js distribution, screenshot capture, recording overlay fix, MPA popup recording | Retry, i18n, accessibility |
| Tests | **~85%** | 122+ tests (pytest + Vitest + Playwright, including wizard flow + identity + context tests) | Video API tests, more frontend tests |
| Widget UX (Phase 2) | **~85%** | P0: widget distribution/API URL (100%). P1: wizard (100%), auto context (100%), user identity (100%), camera PiP (100%). P2: MPA recording persistence (100%). Screenshot capture (basic, no annotation). Bug fixes: recording overlay, captureStream caching. | P2-P3: ticket history, screenshot annotation, multi-attach, session replay, video markers |
| Admin (org) | **~55%** | Agent/team CRUD, widget config, tags, custom priorities | Branding, canned responses, SLA, audit log |
| Admin (platform) | **~40%** | Org list (CRUD, suspend, delete), org detail with stats, impersonation (org switcher + middleware), conditional sidebar | Usage/quotas dashboard, billing, feature flags, monitoring |
| Post-MVP | **0%** | -- | Everything |
| AI | **0%** | Models/flags ready | All implementation |

### Next priorities

1. ~~Widget distribution & API URL~~ -- **Done**
2. ~~Widget bugs (screenshot, recording overlay, captureStream)~~ -- **Done**
3. **Phase 2 P2** : ticket history in widget, screenshot annotation overlay
4. Platform admin console (P1: usage/quotas dashboard, billing, feature flags)
5. Canned responses / macros
6. Keyboard shortcuts + bulk actions

---

*This roadmap is a living document. Last updated: 2026-04-09.*
