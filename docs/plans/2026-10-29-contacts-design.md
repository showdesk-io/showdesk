# Contacts & Companies — Design Document

> Date: 2026-10-29
> Status: Validated
> Phase: 3.5 (Channels & Integrations) — prerequisite of the email channel
> Research input: `docs/brainstorm/contacts-companies-management.md`
> Follow-up: `docs/plans/2026-10-29-email-channel-design.md`

---

## Goal

Give every end-user a single, org-scoped **Contact** record (and optionally a
**Company**), so that a conversation can start in the widget, continue by
email and come back to the widget while agents always see one person with one
history.

This document covers the **P0 scope** of the research note (§10). P1 items
(CSV import/export, manual merge, audit log, saved views for contacts,
server-side `identify` API, logo auto-fetch) are out of scope.

Delivered as one branch / PR: `feat/contacts` → `develop`.

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| Organization | The Showdesk tenant (unchanged). |
| Contact | The end-user who talks to an Organization's support. |
| Company | The business a Contact belongs to (a customer of the Organization). |
| Agent | An Organization member handling tickets (`User.role = agent/admin`, unchanged). |

`User.role = end_user` is left untouched; `Ticket.requester` keeps its meaning
(tickets opened on behalf of a user account).

---

## 2. Data model

New app: `apps.contacts`.

```
Contact
  organization        FK Organization (related_name="contacts")
  company             FK Company, null
  email               EmailField, blank          (lowercased)
  email_verified_at   DateTimeField, null        proof of mailbox ownership
  external_id         CharField(255), blank      host-app user id (widget HMAC)
  phone               CharField(30), blank
  name, avatar_url, job_title, locale, timezone
  first_seen_at, last_seen_at, last_contacted_at
  is_unsubscribed     bool
  is_anonymized       bool (one-way)
  attributes          JSONField (validated against ContactAttributeDef)
  constraints: partial unique (organization, email) where email != ""
               partial unique (organization, external_id) where external_id != ""

Company
  organization, external_id, name, domain (lowercased), logo_url, industry,
  size, website, plan, mrr_cents, health_score, signed_up_at, churned_at,
  attributes
  constraints: partial unique (organization, external_id), (organization, domain)

ContactAttributeDef / CompanyAttributeDef   (abstract CustomAttributeDef)
  organization, key (slug, immutable), label, type
  (string|number|boolean|date|enum|url), description, options (enum),
  is_required, is_archived, position
  unique (organization, key); max 50 per entity per organization

ContactNote
  contact, author (FK User), body

Ticket.contact          FK Contact, null, related_name="tickets"
WidgetSession.contact   FK Contact, null, related_name="sessions"
```

`Ticket.requester_email` / `requester_name` / `external_user_id` stay for
backward compatibility and keep being written.

---

## 3. Identity rules

The widget email is supplied by page JavaScript and is **not** covered by the
current `user_hash` (which signs only the external user id). A malicious but
legitimately identified user could therefore declare someone else's email.
The rules below make sure a *declared* email never grants access to anything.

1. **Identified widget session** (valid `user_hash`): `update_or_create` the
   Contact on `(organization, external_id)`. The supplied email is written on
   the Contact **only if no other Contact of the organization owns it**. No
   automatic merge.
2. **Signed email** (new, optional): the host app may pass
   `data-user-email-hash` / `user.email_hash` =
   `HMAC-SHA256(widget_secret, lowercase(email))`. When valid, the session and
   the Contact are marked email-verified (`WidgetSession.email_verified_at`,
   `Contact.email_verified_at`). Existing integrations are unaffected.
3. **Declared email** (anonymous widget session, inbound email later): attach
   to the Contact owning that email or create one. The agent UI shows an
   "unverified" badge. Grants no extra visibility to the end-user.
4. **Company**: from the widget `company` payload of an identified session
   (`update_or_create` on `(organization, external_id)`), else best-effort
   auto-link on `Company.domain` when the email domain is not a public webmail
   (reuse `PUBLIC_EMAIL_DOMAINS`).
5. **Traits**: `user.traits` / `company.traits` are upserted into `attributes`
   for keys defined in the matching `*AttributeDef`; unknown keys are dropped
   and logged.

Widget history visibility is unchanged by this PR (session tickets +
`external_user_id` tickets). Cross-channel history is defined in the email
channel design.

All identity logic lives in one service module (`apps/contacts/services.py`,
e.g. `resolve_contact_for_widget_session()`, `resolve_contact_for_email()`) so
the widget and the email pipeline share it.

---

## 4. Data migration

Per organization:

1. One Contact per distinct non-empty `external_user_id` (tickets + widget
   sessions); name/email from the most recent session.
2. One Contact per remaining distinct `requester_email` / `WidgetSession.email`
   (lowercased).
3. Link `Ticket.contact` and `WidgetSession.contact`.

Emails are not marked verified by the migration. The migration is idempotent
and batched.

---

## 5. API

All endpoints are agent-authenticated and scoped to the agent's organization.

- `GET/POST /api/v1/contacts/`, `GET/PATCH/DELETE /api/v1/contacts/{id}/`
  (search on name/email, filters: company, enum/bool attributes, last seen).
- `GET/POST /api/v1/contacts/{id}/notes/`.
- `GET /api/v1/contacts/{id}/tickets/`.
- `POST /api/v1/contacts/{id}/export/` — Celery task, emails a ZIP (JSON + CSV:
  profile, attributes, tickets, messages, attachment metadata).
- `POST /api/v1/contacts/{id}/anonymize/` — admin only, irreversible: email →
  `anonymized-{uuid}@example.invalid`, name → "Anonymized contact", phone and
  external_id cleared, attributes emptied, the contact's message bodies
  replaced by a placeholder, ticket `context_metadata` reduced to a whitelist,
  `is_anonymized = True`.
- `GET/POST /api/v1/companies/`, `GET/PATCH/DELETE /api/v1/companies/{id}/`,
  `GET /api/v1/companies/{id}/contacts/`, `GET /api/v1/companies/{id}/tickets/`.
- `/api/v1/contact-attributes/`, `/api/v1/company-attributes/` — CRUD of
  definitions (admin), archive instead of delete.

Widget init (`POST` session endpoint) accepts the extended payload
(`traits`, `company`, `email_hash`).

`Contact.is_unsubscribed` blocks every non-essential email to the contact
(enforced by the email channel).

---

## 6. Frontend

- Sidebar entry **Contacts** (tabs: Contacts | Companies).
- Contacts list: avatar, name, email (+ unverified badge), company, last seen,
  open tickets; search, simple filters, pagination 25/50/100.
- Contact detail: profile + editable attributes (left), timeline of tickets and
  notes with "Add note" (centre), summary (right). Admin actions: export,
  anonymize (confirm modal).
- Companies list and detail (profile, people, aggregated tickets).
- Ticket detail: the requester card becomes a Contact + Company card with links.
- Settings → Contact attributes, Company attributes.

---

## 7. Testing

- Model constraints, services (each identity rule, including the
  "declared email never merges" and "email owned by another contact" cases),
  migration on a fixture dataset, every endpoint including cross-organization
  access denial, export and anonymization contents, widget init with
  traits/company/email_hash (valid and forged).
- Frontend: Vitest for list/detail pages and the ticket sidebar card;
  `npm run lint` (0 warnings), `npm test`, `npm run build`.
- Widget: `email_hash` passed through from `data-user-email-hash` and `init()`.
