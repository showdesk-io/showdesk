# Showdesk Roadmap

> Last updated: 2026-05-02

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
- [~] **WebSocket fails on dev.showdesk.io** -- WSS connection to `/ws/tickets/` fails when accessed via Cloudflare proxy. **Root cause: Cloudflare tunnel configuration** -- the frontend code correctly derives WSS URL from `window.location` and Caddy handles WebSocket upgrades natively. Fix requires enabling WebSocket support in Cloudflare Zero Trust tunnel config (not a code issue). **Mitigated in-app**: ticket detail has 10 s polling fallback (`refetchInterval` on `useTicket`). Note: `VITE_WS_BASE_URL` env var is defined but unused (can be cleaned up).
- [x] **Widget: screen capture fails** -- screenshot button was disabled ("Coming soon"). Implemented full screenshot capture via getDisplayMedia single-frame, with overlay hiding, thumbnail previews, and backend widget attachment upload endpoint. Also fixed PipCompositor captureStream caching and added video track validation.
- [x] **Widget: modal overlay blocks recording** -- when recording starts, the overlay and modal are now hidden and the FAB is replaced by a compact recording bar (dot + timer + PiP controls + stop) at the FAB position. User can interact freely with the page. On stop, the modal reappears with the recording preview.
- [x] **Agent dashboard: no real-time updates** -- WebSocket `refetchQueries()` fix applied. Added 10s polling fallback on ticket detail view (`refetchInterval: 10_000` in `useTicket` hook) so updates work even when WebSocket connection fails (e.g. behind Cloudflare proxy).
- [x] **Widget: session leakage between users on the same browser** -- when a logged-in user A logged out and user B logged in via the in-app widget (dogfooding), the widget resumed user A's `session_id` from `localStorage` and showed A's conversations to B. Fixed by (1) a new `Showdesk.reset()` public API that clears the stored session id (`widget/src/widget.ts`); (2) `useInternalWidget` keying the identity query by `accessToken` and calling `reset()` on cleanup; (3) backend `widget_session` dropping the supplied `session_id` when its `external_user_id` mismatches the HMAC-identified user (`backend/apps/tickets/views.py`). 4 pytest cases in `backend/tests/tickets/test_widget_session.py`.

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

### Widget: Messaging Refactor (Priority 0 -- 2026-04)

Major UX pivot from the multi-step wizard to a WhatsApp-style messaging interface. The wizard (qualification → capture → contact → send) was replaced with a persistent chat where users compose messages freely, attach media, and read agent replies in real time. Implementation: `widget/src/ui/chat/`, `widget/src/ui/history/`, `widget/src/session/session-manager.ts`, `WidgetSession` model + migration `0007_widget_session_and_messaging`.

- [x] Anonymous session system (`WidgetSession`, UUID in localStorage, `X-Widget-Session` header, session-scoped ticket access)
- [x] Session linked to `external_user_id` when HMAC identity is provided
- [x] Bottom tabs: Chat / History (News / Ideas reserved for later)
- [x] Ticket created on first message sent (no empty tickets on widget open)
- [x] Real-time agent replies via Django Channels WebSocket (widget ↔ backend)
- [x] Message bubbles with inline image/video/audio/screenshot rendering
- [x] Audio messages: tap-to-record / tap-to-stop, sent as individual messages
- [x] Attachment menu (screen recording, camera, screenshot, file upload, audio)
- [x] Message deletion by user with undo toast, synced to agent dashboard
- [x] Contact nudge: gentle prompt for anonymous users after first send (non-blocking)
- [x] Agent-side chat-style ticket detail: message thread, inline media, lightbox, inline title/description edit
- [x] Internal notes filtered out of widget broadcasts
- [ ] News tab (product updates / changelog surfaced in widget)
- [ ] Ideas tab (feature voting / roadmap feedback)
- [ ] AI topic-change detection to suggest starting a new conversation

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
- [x] Audio recording MPA mode (mic-only popup variant)

### Widget: Ticket History in Widget (Priority 2)

Previous tickets and agent replies are visible directly in the widget via the History tab (session-scoped for anonymous users, external-user-scoped for HMAC-identified users).

- [x] Ticket list view in widget (History tab, user's own tickets)
- [x] Ticket detail view in widget (messages thread with inline media)
- [x] On widget open: session resume fetches conversations + unread counts (`WidgetSessionSerializer.unread_count`)
- [x] Notification badge on widget FAB when unread replies exist (`updateBadge()` in `widget/src/ui/button.ts`, live-updated over WebSocket)
- [x] Mark replies as read when viewed in widget (`widget_mark_read` endpoint + `Ticket.widget_last_read_at`, called on resume / history click / live message)

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

## Phase 2.5 -- Self-Service Signup & Onboarding

Today, organizations can only be created by a platform admin. To unblock acquisition,
prospects must sign up, create their org, and invite their team without operator
intervention. Reuses existing OTP auth -- no password introduced. Target: startups /
small structures, so we keep it simple: **one email = one org**, no multi-tenancy
per user.

**Domain auto-join (simplified, no DNS verification):** the first admin's email
domain is recorded on the org (unless it's a public webmail like gmail.com,
hotmail.com, etc.). Subsequent signups from the same domain create a *join request*
that an admin must approve, instead of spawning a duplicate org. Users from
non-matching domains can still join, but only through explicit invitation.

### Backend

- [x] P0: Public signup endpoint -- restructured into a 4-step OTP-first flow
      under `/api/v1/auth/signup/`: `request-otp/`, `verify-otp/`, `create-org/`,
      `request-join/`, `state/`. The OTP gate guarantees the email is verified
      before an org is created or a join request is filed. Quota is counted per
      IP+email but only on success (201/202) so typo iterations don't lock the
      user out. See `apps/organizations/signup_views.py`.
- [x] P0: Slug availability endpoint `GET /api/v1/auth/check-slug/?slug=foo`
      (with reserved-words list).
- [x] P0: Domain lookup endpoint `GET /api/v1/auth/check-domain/?email=alice@acme.com`
      -- now reads from `OrganizationDomain` (status=verified, is_email_routing=True),
      not the legacy scalar.
- [x] P0: Email-uniqueness guard -- `/auth/signup/request-otp/` refuses
      `END_USER` accounts and inactive users; `/users/invite/` returns 409
      `code=email_taken` instead of 500/IntegrityError.
- [x] P0: Public-webmail blocklist (`PUBLIC_EMAIL_DOMAINS`, ~61 entries:
      gmail, outlook, yahoo, free.fr, etc.). The original
      `Organization.email_domain` scalar has since been replaced by the
      richer `OrganizationDomain` model -- see "Organizations: Verified
      Domains" below.
- [x] P0: `OrgJoinRequest` model + admin-only `approve` / `reject` actions
      (`apps/organizations/models.py`, `views.py`). Approval can attach a
      pre-existing lonely user to the target org (created during the OTP
      gate) instead of duplicating it.
- [x] P0: Onboarding state on Organization -- `onboarding_completed_at`
      (nullable datetime) and `onboarding_step` (PositiveSmallIntegerField).
- [x] P0: Welcome email on signup + join-request-submitted / approved /
      rejected emails (templates in `backend/templates/emails/`).

### Frontend

- [x] P0: `/signup` public page -- five internal steps (`email`, `otp`,
      `wizard`, `join_confirm`, `join_done`); domain-match preview triggers
      the "Request to join {OrgName}" branch; live slug check; auto-resume
      via `/auth/signup/state/`. See `frontend/src/pages/SignupPage.tsx`.
- [x] P0: Login page CTA "Create an account"; AuthGuard now redirects an
      authenticated user without an org to `/signup` so the wizard can
      finish.
- [x] P0: Post-signup onboarding wizard (`/onboarding`) -- 3 steps (widget
      config, invite teammates, copy embed snippet + demo link), resumable
      via `Organization.onboarding_step`. `OnboardingPage.tsx`.
- [x] P0: Team page -- "Pending join requests" panel for admins
      (approve/reject buttons). Lives on `/team` (the existing Team page),
      not on a Settings tab. `TeamPage.tsx`.
- [x] P1: Empty-state nudge on dashboard until `onboarding_completed_at`
      is set, linking to `/onboarding`.
- [x] P1: Widget install detection in onboarding step 3 --
      `Organization.widget_first_seen_at` (migration 0011) is stamped by
      `_get_widget_org()` on the first widget request. The wizard polls
      the org every 3 s while still null and flips the embed step from a
      "Waiting for first ping..." pulse to a green "Widget detected" badge.
      Skip link to the dashboard remains available. Tests:
      `backend/tests/tickets/test_widget_first_seen_at.py` (4 cases).

### Tests

- [x] P0: pytest -- 27+ cases in `backend/tests/organizations/test_signup.py`
      covering both paths, slug rules, domain match, public-webmail
      exclusion, join request lifecycle, multi-org scoping, quota counted
      only on success.
- [x] P0: pytest -- slug + domain check endpoints.
- [x] P0: pytest -- join request approve/reject (creates user / sends
      emails / role).
- [x] P0: pytest -- invitation endpoint returns 409 (not 500) when email
      exists, case-insensitive.
- [ ] P0: Vitest -- signup form UI tests: still missing
      (`SignupPage.tsx`, `OnboardingPage.tsx`). Only `authStore.test.ts`
      exists in `frontend/src/store/__tests__/`.

### Open questions

- Plan/billing: **deferred** -- trial-by-default, no plan picker at signup;
  billing belongs to Phase 3.
- Captcha / disposable-email blocklist: deferred until abuse is observed.
- Join-request expiration (auto-reject after N days): deferred to v1.1.

---

## Phase 2.6 -- Organizations: Verified Domains

A small but load-bearing system that replaces the two legacy scalar fields
`Organization.domain` (free-text branding) and `Organization.email_domain`
(implicit signup auto-route signal) with a single, verified-state-aware
`OrganizationDomain` model. Multiple domains per org, both branding and
email-routing roles, two verification paths (DNS TXT, admin-email
auto-verify), and explicit ownership transfer when a competing org wins
a DNS challenge.

### Backend

- [x] `OrganizationDomain` model with status (pending/verified/failed),
      method (dns_txt/admin_email), token, verified_at, last_check_at,
      `is_branding`, `is_email_routing`. Constraints: unique(org, domain),
      partial unique on `domain` where status='verified' (one verified
      claim per domain globally), check constraint requiring at least one
      role. `apps/organizations/models.py:358-465`.
- [x] Migrations: `0008` create model, `0009` backfill from legacy
      scalars, `0010` drop `Organization.domain` and `.email_domain`.
- [x] Service layer (`apps/organizations/services.py`):
      `try_admin_email_autoverify`, `start_dns_challenge`,
      `perform_dns_check`, `apply_dns_verification_success`
      (atomically transfers ownership, flips loser to failed, emails admins).
- [x] DNS lookups: `apps/organizations/dns_verification.py` (thin
      dnspython wrapper, returns `[]` on errors).
- [x] Periodic recheck: Celery Beat task
      `recheck_dns_pending_domains` every 15 minutes, bounded by a 7-day
      window per pending row.
- [x] CRUD endpoints: `/api/v1/organization-domains/` with `verify` and
      `regenerate-token` actions (admin-only writes).
- [x] Signup integration: `SignupCreateOrgView` calls
      `try_admin_email_autoverify` for the founder's domain (best-effort).
- [x] `OrganizationDomain`-aware lookups in `_resolve_next_step`,
      `CheckDomainView`, and the request-join branch.
- [x] `domain_verified` and `domain_ownership_transferred` email templates.

### Frontend

- [x] Settings > Organization -- new Domains section
      (`frontend/src/components/settings/DomainsList.tsx`): add via DNS or
      admin-email, toggle is_branding / is_email_routing flags, "Check now"
      for pending DNS rows, copy TXT record, regenerate stale tokens,
      delete. Legacy backfilled rows get a "Verify via DNS" shortcut.
- [x] Signup wizard `email_domain` field is editable: defaults to founder's
      verified email domain (auto-verified), or accept a custom domain
      (creates a pending DNS challenge instead). Status shown via the new
      `email_domain_status` field on the create-org response.
- [x] `Organization` / `PlatformOrganization` TypeScript types lose
      `domain` and `email_domain` (single source of truth is now the
      Domains list).

---

## Phase 3 -- Admin Console

### Email Design & Branding (Priority 1)

Goal: a consistent, branded, HTML-rich rendering with a plain-text fallback, shared across all transactional emails. **Mostly done in commits `478b130` and `0a75184`.**

- [x] Shared base email template (`backend/templates/emails/base.html`) with header logo, body slot, brand-colored footer, inline CSS, dark-mode-friendly.
- [x] Per-email Django templates (`*.html` + `*.txt`) for: new ticket, agent reply, ticket assigned, ticket resolved, OTP login, agent invitation, signup welcome, join request submitted/approved/rejected, **domain verified, domain ownership transferred** (13 templates total).
- [x] `send_branded_email()` helper in `apps/core/email.py` -- renders HTML + text, sets `EmailMultiAlternatives`, embeds the logo via CID (multipart/related) so the image renders inline without an external fetch.
- [~] All `send_mail()` call sites refactored to use the helper -- 18 of 19 done; the lone holdout is `apps/core/management/commands/sendtestemail.py` (intentional, dev-only command using stock `send_mail`).
- [x] CTA buttons (`backend/templates/emails/_button.html`) rendered as bulletproof table-based HTML with inline styles + bgcolor fallback.
- [x] Per-org branding hook: `_brand_for(org)` reads `Organization.logo` (ImageField) and primary color, with graceful fallback to `BRAND_*` defaults. Per-org logos are also embedded as CID.
- [x] Email preview tool -- shipped as a `preview_email` management
      command (`python manage.py preview_email --list` /
      `preview_email <template> --to <addr> [--org <slug>]`). Renders
      every branded template with sample data through `send_branded_email`
      (so output matches production exactly: CTA buttons, From: header,
      per-org overrides). Lands in Mailpit in dev. Implemented as a
      command rather than a custom admin URL because nothing else is
      wired into the Django admin yet, and command output is friendlier
      for designers iterating in CI / scripted snapshots.
- [x] Tests: snapshot-style coverage in `backend/tests/core/test_email.py`
      (12 cases now: HTML alternative + plain-text body, From: header
      branding, primary_color overrides, ticket-reply linebreaks +
      autolink + attachment list). Plus `test_preview_email_command.py`
      parametrised over every sample template (16 cases).
- [x] Ticket reply email: message body rendered as HTML --
      `{{ message_body|urlize|linebreaksbr }}` so newlines become `<br>`
      and bare URLs become clickable; attachments rendered as a bordered
      list with name + clickable link + filesizeformat-formatted size,
      pluralised header. Plain-text fallback also lists attachments.

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
- [~] P1: Organization branding -- Settings > Branding tab. Scoped lean
      for startups, no full white-label.
      - [x] Backend: `Organization.primary_color` (hex, distinct from
        `widget_color`) + `email_from_name`. Migration 0012. Both exposed
        on `OrganizationSerializer`. `_format_from_email()` in
        `apps/core/email.py` rewrites the From: header as
        `"<email_from_name> <address>"` when set, else falls back to
        `BRAND_NAME`. `_brand_for(org)` already routes per-org logo +
        primary color through every branded template.
      - [x] Settings UI: Branding tab with 3 admin-only fields -- logo
        upload (multipart PATCH on `/organizations/{id}/`) + preview +
        remove, primary-color picker (color input + hex text), "From
        name" input. Toast feedback + dirty/discard handling.
      - [x] Tests: 3 new pytest cases verify `email_from_name` lands in
        the From: header, falls back to the brand name when blank, and
        that `primary_color` overrides reach the rendered HTML body.
      - [ ] Agent UI: inject `--color-primary` from `org.primary_color`
        as a CSS custom property at AppLayout mount; sidebar shows
        `org.logo` (or initials fallback). Deferred -- the Tailwind
        palette is static, so this needs a dedicated runtime-CSS pass.
      - Out of scope (separate items): full white-label / removing Showdesk
        mention, custom CSS, per-user theming, custom email domain.
- [ ] P1: Custom domain for widget/portal
- [x] P1: Tags & categories management
- [x] P1: Custom priority management (CRUD, custom colors, per-org)
- [x] P1: Canned responses / macros (CRUD in Settings, slash-trigger picker in reply composer, `{{variable}}` substitution, personal/shared scope, usage counter)
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
- [x] P1: In-app dogfooding -- `showdesk-internal` org auto-provisioned via migration `0006_showdesk_internal_org`, `/api/v1/widget/identity-hash/` endpoint returns the internal token + HMAC identity, widget mounted in `AppLayout` via `useInternalWidget` so staff file tickets from the UI they are using
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

### Developer Experience / Tech Debt

- [ ] Migrate backend dependencies from `requirements.txt` to `pyproject.toml` (PEP 621). Pick a tool (`uv`, Poetry, or `pip-tools`), generate a lockfile for reproducible builds, separate prod / dev / test dependency groups, update `backend/Dockerfile` to install from the new manifest, and adapt CI. Goal: deterministic builds + cleaner dev/prod split (e.g. `watchdog` only in dev).
- [ ] **Unify brand config across runtimes** (single source of truth). The Django side already centralises the brand under `BRAND_*` env-overridable settings (commit `c6705c1`), but the front and the widget still duplicate the primary colour: `tailwind.config.js` defines the full `primary.50…950` scale, `widget/src/ui/styles.ts` has its own `DEFAULT_PRIMARY`, and `Organization.widget_color` defaults to `#6366F1` in the model. Changing the primary colour still requires editing 3+ files. Pick a shared source -- likely `brand.json` at repo root, consumed by Tailwind via `require()`, by the widget via TS import, and by Django via `json.load()` at startup. Migrate all runtimes, drop the duplicated constants, document the new workflow. Pairs with the per-org branding work in Phase 3.

---

## Phase 5 -- AI Layer (Cloud-only, behind feature flags)

- [ ] Whisper transcription (self-hosted or managed API)
- [ ] AI ticket summary generation
- [ ] AI-generated ticket title & description from conversation context (auto-suggest when AI API is configured)
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
| Backend API | **~99%** | Models, views, tasks, seeds, WebSocket, rate limiting, Celery Beat, file validation, custom priorities, saved views, stats, S3 fix, external_user_id, context_metadata, issue_type, widget_tickets, platform admin, impersonation, WidgetSession + messaging, message-delete notify, internal-org provisioning + identity-hash, **OTP-first 4-step signup, OrgJoinRequest, OrganizationDomain (DNS + admin-email verification, ownership transfer, periodic recheck), branded HTML emails (CID logo)** | Video duration validation, ticket-reply email body as HTML |
| Frontend | **~97%** | Auth, tickets CRUD, assignment, status, settings, teams, WebSocket, tags, inline actions, view modes, priorities, video player, attachments, saved views, stats modal, filters, inline tag creation, technical context panel, issue type badge, platform admin, org switcher, fixed embed snippet, widget preview button, chat-style ticket detail, in-app widget dogfooding, **/signup page (5 internal steps + auto-resume), /onboarding wizard (3 steps, resumable), Settings > Domains, dashboard onboarding nudge** | Shortcuts, bulk actions, agent video reply, SLA editor, Branding tab |
| Widget | **~99%** | Full messaging UI (chat + history tabs, session system, audio messages, message deletion with undo, attachment menu), recording (screen + camera PiP + screenshot), upload, e2e tests, console/network collectors, user identity (API + data-user-*), API URL auto-detect, /cdn/widget.js distribution, MPA popup recording incl. audio, contact nudge, FAB unread badge + mark-as-read, **`Showdesk.reset()` for clean user-switch (fixes session leakage between users on the same browser)** | Retry, i18n, accessibility |
| Tests | **~88%** | 155+ pytest tests (incl. 27 signup cases, identity-hash, branded emails, OrganizationDomain, widget session resume) + 15 Vitest + 19 Playwright | Vitest for SignupPage / OnboardingPage, widget messaging tests, video API tests |
| Widget UX (Phase 2) | **~92%** | P0: distribution/API URL + messaging refactor (100%). P1: wizard, auto context, user identity, camera PiP (100%). P2: MPA recording persistence incl. audio, ticket history (100%). Screenshot capture (basic, no annotation). | Screenshot annotation, multi-attach, session replay, video markers, News/Ideas tabs |
| Signup & Onboarding (Phase 2.5) | **~95%** | All P0 backend (OTP-first signup, slug/domain check, 409 guard, OrgJoinRequest, onboarding state) + frontend (/signup, /onboarding wizard, join-requests panel on Team page, dashboard nudge) + 27+ pytest cases | Widget install detection in onboarding step 3 (`widget_first_seen_at`), Vitest for the signup/onboarding UI |
| Verified Domains (Phase 2.6) | **100%** | OrganizationDomain model + migrations 0008-0010 (backfill + drop legacy scalars), DNS TXT + admin-email verification, ownership transfer, Celery recheck task, full CRUD + verify/regenerate-token actions, Settings UI, signup wizard integration, transfer email | -- |
| Email branding (Phase 3) | **~85%** | Shared base template, 13 transactional templates (HTML + txt), `send_branded_email()` helper, CID inline logo, per-org logo + colour, bulletproof CTA buttons, snapshot tests, 18/19 call sites refactored | Email preview in Django admin, ticket reply body as HTML, refactor `sendtestemail` command (low priority) |
| Admin (org) | **~65%** | Agent/team CRUD, widget config, tags, custom priorities, canned responses (templates + slash picker + variables), Domains section | Branding tab (primary_color + email_from_name + per-org logo upload UI), SLA editor (backend model exists, no UI), audit log |
| Admin (platform) | **~45%** | Org list (CRUD, suspend, delete), org detail with stats, impersonation (org switcher + middleware), conditional sidebar, in-app dogfooding (internal org + identity-hash) | Usage/quotas dashboard, billing, feature flags, monitoring |
| Post-MVP | **0%** | -- | Everything |
| AI | **0%** | Models/flags ready | All implementation (auto-categorization, topic-change detection, title/description generation) |

### Next priorities

1. ~~Widget distribution & API URL~~ -- **Done**
2. ~~Widget messaging refactor + FAB unread badge~~ -- **Done**
3. ~~Phase 2.5 P0 (signup, onboarding, join requests)~~ -- **Done**
4. ~~Phase 2.6 verified domains~~ -- **Done**
5. ~~Branded HTML emails (P1)~~ -- **Mostly done** (Django-admin preview + ticket-reply HTML body still TODO)
6. ~~Widget session leakage fix (in-app dogfooding)~~ -- **Done**
7. **Phase 2.5 leftover P1**: widget install detection in onboarding step 3 (`Organization.widget_first_seen_at` + poll on the wizard).
8. **Phase 3 Org Admin -- Branding tab** (logo upload + primary_color + email_from_name; the per-org plumbing already exists, only the UI is missing).
9. **Phase 2 P2 remaining**: screenshot annotation overlay, multi-attachments.
10. **AI layer kickoff**: ticket auto-categorization, AI title/description generation (Phase 5, behind feature flag).
11. Platform admin console (P1: usage/quotas dashboard, billing, feature flags).
12. Keyboard shortcuts + bulk actions on the ticket list.
13. Frontend Vitest coverage of signup / onboarding flows.

### Strategic backlog -- 2026-04-30 brainstorm

`docs/brainstorm/` contains 7 research syntheses (commit `1594782`) on
topics that may shape post-MVP direction. Each note has competitor
analysis, 2025-2026 sourcing, and a recommended architecture; use them
as input the next time we plan a major Phase 4+ initiative.

- `multi-channel-communication.md` -- email / WhatsApp / Insta / Slack inbound
- `agent-create-ticket.md` -- agent-side ticket creation flow
- `contacts-companies-management.md` -- CRM-light layer
- `help-desk-portal.md` -- per-org KB + status page + custom domain
- `video-library-loom-like.md` -- Loom-style record + transcode + CDN
- `phone-support-webrtc.md` -- WebRTC phone via LiveKit
- `mcp-server.md` -- MCP server exposing tickets/KB to AI agents

---

*This roadmap is a living document. Last updated: 2026-05-02.*
