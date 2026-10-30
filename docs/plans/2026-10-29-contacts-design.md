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
  declared_email      EmailField, blank          (lowercased, not unique) unproven
                                                 email of an identified session
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

A widget session's email, name, traits and company are supplied by page
JavaScript, so a malicious but legitimately identified user can forge them. Only
three values are signed by the host app: `user_hash` (the external user id) and
the optional `email_hash` and `company_hash`. The rules below make sure forged
data never grants access to anything and never alters somebody else's record.

Signatures use `HMAC-SHA256(widget_secret, …)` over a prefixed message, so that
a hash for one kind of value can't be replayed as another:

| Hash | Signed message |
|---|---|
| `user_hash` | `external_user_id` |
| `email_hash` | `"email:" + lowercase(email)` |
| `company_hash` | `"company:" + company.id + ":" + company.name + ":" + lowercase(company.domain)`, with `domain` empty if absent |

`company_hash` covers the name and domain so a member can't replay it with a forged
name or domain. It doesn't cover `company.traits`. External user ids starting with
`email:` or `company:` are refused (400), so a `user_hash` can never double as another
hash.

An invalid or missing `email_hash` / `company_hash` is ignored, not rejected: the
value is simply treated as unsigned, and existing integrations are unaffected.

1. **Identified widget session** (valid `user_hash`): the Contact is found or
   created on `(organization, external_id)`. No automatic merge, ever.
   - **Unproven email**: `Contact.email` never receives it. It is stored in
     `declared_email`, only on that session's own Contact, and the latest value
     wins. An email equal to the one the Contact already holds is no separate
     claim and clears `declared_email`. Agents see it with an "unverified" badge,
     and it is included in API search.
   - **Proven email**: a Contact with a blank `email` takes it if no other Contact
     owns it. A new external id attaches to the email-only Contact owning it
     (`external_id` blank). A Contact holding another email keeps it, and a proven
     email that is owned elsewhere stays with its owner: in both cases the session
     proved nothing about this Contact, nothing is marked verified and
     `declared_email` is left as it is. Otherwise `declared_email` is cleared if it
     equals the proven email.
2. **Proof of an email**: a valid `email_hash` (`data-user-email-hash` /
   `user.emailHash`), or a later proof of ownership (see the email channel design).
   When the Contact ends up holding that email, the session and the Contact are
   marked verified (`WidgetSession.email_verified_at`, `Contact.email_verified_at`).
   Filling `email` always sets a fresh `email_verified_at`, so a stale date never
   survives; a Contact that already held the email keeps its first date.
3. **Anonymous widget session, inbound email**: attach to the Contact owning that
   address in `Contact.email`, or create an email-only Contact (first come,
   unverified). The agent UI shows an "unverified" badge. This grants no access,
   and a proof later attaches to that Contact. `declared_email` is never looked
   up, so an address merely declared by an identified user never leads to their
   Contact. On a Contact that already exists, an unproven anonymous session writes
   nothing at all: no seen dates, no `updated_at`, no company; it only links the
   session. A proven one updates the name (if blank), traits and seen dates.
4. **Company**, only from an identified session:
   - **Unsigned** (no valid `company_hash`): an existing Company is never modified,
     only linked, and a Contact that already has a Company is never moved, nor does
     its payload create anything. A new Company takes `name` and `traits`. It takes
     `domain` only if the session's email is proven, its domain equals `domain`, it
     isn't a public webmail domain (`PUBLIC_EMAIL_DOMAINS`) and no other Company owns
     it.
   - **Signed** (valid `company_hash`): upsert of `name` and `domain` on
     `(organization, external_id)`, and the Contact may be moved. `domain` still never
     takes another Company's domain. `traits` aren't signed, so they apply to a Company
     this payload creates and never to an existing one.
   - **Auto-link on `Company.domain`**, for a Contact without a Company when the
     email domain is not a public webmail: on an identified Contact only from a
     proven email (`email_verified_at` set); on an anonymous session only when it
     creates the Contact (agents see it as unverified). An inbound email fills a
     missing Company from the domain of the email the Contact already holds, except
     on an identified Contact whose email is unproven.
5. **Traits**: `user.traits` / `company.traits` are upserted into `attributes`
   for keys defined in the matching `*AttributeDef`; unknown keys are dropped
   and logged. `user.traits` apply to an HMAC-identified session or a proven anonymous
   one; `company.traits` follow rule 4.
6. **Concurrency**: the Contact's row is locked (`SELECT … FOR NO KEY UPDATE`)
   before anything is changed, and `is_anonymized` is checked under that lock, so a
   concurrent anonymization is never undone. Saves write only the fields that really
   changed, and nothing at all when nothing did. An anonymized Contact is never
   written to again. The anonymization locks the same row. A retry after a unique
   conflict relies on the READ COMMITTED isolation level.
7. **No Contact**: whenever the service resolves no Contact (no usable identity, or
   an anonymized one), a Contact previously linked to the session is unlinked.

Widget history visibility is unchanged by this PR (session tickets +
`external_user_id` tickets). Cross-channel history is defined in the email
channel design, and relies on `Contact.email` being proven (or set by an agent) on
any Contact with an `external_id`.

Because `widget_submit` and inbound email resolve a Contact from a merely declared
address, a forged ticket can be linked to a verified Contact. Agents therefore see
a per-ticket `sender_verified` flag (§5) in addition to the Contact's own badge.

All identity logic lives in one service module (`apps/contacts/services.py`,
e.g. `resolve_contact_for_widget_session()`, `resolve_contact_for_email()`) so
the widget and the email pipeline share it.

---

## 4. Data migration

Per organization:

1. One Contact per distinct non-empty `external_user_id` (tickets + widget
   sessions); name from the most recent session, and its email in `declared_email`,
   not `email` (rule 1: nothing there is proven).
2. One Contact per remaining distinct `requester_email` / `WidgetSession.email`
   (lowercased).
3. Link `Ticket.contact` and `WidgetSession.contact`.

Emails are not marked verified by the migration. The migration is idempotent
and batched.

---

## 5. API

All endpoints are agent-authenticated and scoped to the agent's organization.

- `GET/POST /api/v1/contacts/`, `GET/PATCH/DELETE /api/v1/contacts/{id}/`
  (search on name/email/declared_email, filters: company, enum/bool attributes,
  last seen; `declared_email` is read-only; NULL `last_seen_at` always sorts last).
- `GET/POST /api/v1/contacts/{id}/notes/`.
- `GET /api/v1/contacts/{id}/tickets/`.
- `POST /api/v1/contacts/{id}/export/` — Celery task, emails a ZIP (JSON + CSV:
  profile, attributes, tickets, messages, attachment metadata).
- `POST /api/v1/contacts/{id}/anonymize/` — admin only, irreversible: email →
  `anonymized-{uuid}@example.invalid`, name → "Anonymized contact", phone and
  external_id and declared_email cleared, attributes emptied, the contact's message bodies
  replaced by a placeholder, ticket `context_metadata` reduced to a whitelist,
  `is_anonymized = True`.
- `GET/POST /api/v1/companies/`, `GET/PATCH/DELETE /api/v1/companies/{id}/`,
  `GET /api/v1/companies/{id}/contacts/`, `GET /api/v1/companies/{id}/tickets/`.
- `/api/v1/contact-attributes/`, `/api/v1/company-attributes/` — CRUD of
  definitions (admin), archive instead of delete.

Widget init (`POST` session endpoint) accepts the extended payload
(`traits`, `company`, `email_hash`, `company_hash`), and checks the types and lengths
of the identity fields before touching the session.

Tickets expose a read-only `sender_verified`: whether this ticket's sender proved
being its Contact (session email verified or HMAC-identified on that Contact, or the
conversation link once the email channel adds it). It's null when there's no outside
sender to verify: an agent-created ticket (source `agent` or `api`, or no session and no
inbound sender).

`Contact.is_unsubscribed` blocks every non-essential email to the contact
(enforced by the email channel).

---

## 6. Frontend

- Sidebar entry **Contacts** (tabs: Contacts | Companies).
- Contacts list: avatar, name, email (+ unverified badge), declared email (always
  with the unverified badge), company, last seen,
  open tickets; search, simple filters, pagination 25/50/100.
- Contact detail: profile + editable attributes (left), timeline of tickets and
  notes with "Add note" (centre), summary (right). Admin actions: export,
  anonymize (confirm modal).
- Companies list and detail (profile, people, aggregated tickets).
- Ticket detail: the requester card becomes a Contact + Company card with links,
  and an "unverified sender" hint when `sender_verified` is false.
- Settings → Contact attributes, Company attributes.

---

## 7. Testing

- Model constraints, services (each identity rule, including the
  "declared email never merges" and "email owned by another contact" cases),
  migration on a fixture dataset, every endpoint including cross-organization
  access denial, export and anonymization contents, widget init with
  traits/company/email_hash/company_hash (valid and forged), concurrent
  anonymization against a second database connection.
- Frontend: Vitest for list/detail pages and the ticket sidebar card;
  `npm run lint` (0 warnings), `npm test`, `npm run build`.
- Widget: `email_hash` passed through from `data-user-email-hash` and `init()`,
  `company_hash` from `init()`.
