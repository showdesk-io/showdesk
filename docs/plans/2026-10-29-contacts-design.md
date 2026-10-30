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
  organization, key (snake_case, immutable), label, type (immutable)
  (string|number|boolean|date|enum|url), description, options (enum only),
  is_archived, position
  unique (organization, key); max 50 non-archived per entity per organization

ContactNote
  contact, author (FK User), body

Ticket.contact          FK Contact, null, related_name="tickets"
WidgetSession.contact   FK Contact, null, related_name="sessions"
WidgetSession           partial unique (organization, external_user_id)
                        where external_user_id != ""
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
a hash for one kind of value can't be replayed as another (`\n` is a line feed):

| Hash | Signed message |
|---|---|
| `user_hash` | `external_user_id` |
| `email_hash` | `"email:" + lowercase(email)` |
| `company_hash` | `"company\n" + company.id + "\n" + company.name + "\n" + lowercase(company.domain)`, with `domain` empty if absent |

`company_hash` covers the name and domain so a member can't replay it with a forged
name or domain. It doesn't cover `company.traits`. Its fields are separated by newlines,
which can't be confused with their content: an id, name or domain containing one never
verifies. External user ids starting with `email:` or `company\n` are refused (400), and
`verify_user_hash` itself never accepts them, so a `user_hash` can never double as
another hash.

An invalid or missing `email_hash` / `company_hash` is ignored, not rejected, whatever
its shape: the value is simply treated as unsigned, and existing integrations are
unaffected. A wrong or badly shaped `user_hash` is ignored when resuming an anonymous
session and refused (403) when it's the only way to the session asked for (rule 8). Only
a malformed `external_user_id` is a 400.

1. **Identified widget session** (valid `user_hash`): the Contact is found or
   created on `(organization, external_id)`. No automatic merge, ever.
   - **Unproven email**: `Contact.email` never receives it. It is stored in
     `declared_email`, only on that session's own Contact, and the latest value
     wins, so a different email on a resume also replaces `WidgetSession.email`. An
     email equal to the one the Contact already holds is no separate claim and clears
     `declared_email`. Agents see it with an "unverified" badge, and it is included in
     API search.
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
   survives; a Contact that already held the email keeps its first date. On a resume,
   a different signed email replaces `WidgetSession.email` on any session. Whenever
   that email changes `WidgetSession.email_verified_at` is cleared, the proof being
   about the previous one, and set again if the Contact ends up holding the new one.
3. **Anonymous widget session, inbound email**: attach to the Contact owning that
   address in `Contact.email`, or create an email-only Contact (first come,
   unverified). The agent UI shows an "unverified" badge. This grants no access,
   and a proof later attaches to that Contact. `declared_email` is never looked
   up, so an address merely declared by an identified user never leads to their
   Contact. An anonymous session keeps its first email unless a different one is
   signed. On a Contact that already exists, an unproven anonymous session writes
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
8. **Login and logout on a browser**: one session per `(organization,
   external_user_id)`, and only a valid `user_hash` resumes it through the session
   endpoint's `POST`. That's the only thing gated: every other widget endpoint takes the
   session id alone (`X-Widget-Session`), so an id stays a bearer token (see §8). The
   session id the widget stored decides what an init does:
   - **Anonymous, no valid hash**: resumed. An id sent without a valid hash is ignored.
   - **Anonymous with a proven email, no valid hash and no valid `email_hash`
     (logout)**: handled as an identified session's logout below: a new anonymous
     session, the stored one left as it is. The proof stays true of what that session
     wrote, and nothing new is written under it. An integrator signing the email on every
     init keeps its session. A wrong `user_hash` here is refused (403) as on an identified
     session, since nothing else in the request proves anything.
   - **Anonymous, valid hash (login)**: the identified session is found or created,
     and returned for the widget to store instead. In one transaction, within the
     organization, the anonymous session's tickets move to it and to its Contact
     (`widget_session`, `external_user_id`, `contact`), and their messages too, so the
     conversation goes on. Those tickets were written before anyone proved who they
     are: `context_metadata["pre_login_anonymous"]` records it, and `sender_verified`
     stays false on them. `context_metadata["pre_login_session_hash"]` keeps the SHA-256
     hex digest of the anonymous session's id, since agents can read it and the id is a
     bearer token, and the move is logged at info level, with digests and counts only.
     It's idempotent: nothing is left to move on a retry. A message being posted meanwhile
     takes the session its ticket is on, under the ticket's row lock, so it can't stay
     behind. A later `PATCH` of the session's name or email doesn't fill the blank
     requester of a moved ticket: it isn't necessarily this user's. In the same
     transaction the anonymous session is blanked (name, email, user agent,
     `email_verified_at`, Contact), since anonymizing the Contact later wouldn't reach
     it. Once committed, an email-only Contact the move emptied is deleted, unless it holds
     a ticket, a session, a note, an unsubscription, or a phone, avatar, job title, locale,
     timezone or attribute; a failure there is logged and the login goes on.
   - **Identified, valid hash**: find-or-create on the id sent, which is the user's own
     session unless another user logged in since on that browser.
   - **Identified, no hash (logout)**: a new anonymous session, which the widget stores
     instead. Nothing is written to the identified session or its Contact, and the
     response exposes nothing of its history. This includes an id sent without a hash:
     nothing proves it. It only stops the init from resuming that session: the old id
     isn't revoked and keeps working as `X-Widget-Session` for whoever still holds it. A
     session can only become identified through a valid hash, so an integration that
     never signs has none to lose.
   - **Identified, wrong hash**: refused (403), as without a stored session.

   A ticket without a Contact is only linked to the session's Contact when a request
   sets or changes it, so a Contact cleared by an agent stays cleared.

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

Per organization, in one transaction, by `apps/contacts/backfill.py`:

1. **What counts as an external id.** A session's was signed when the session was
   created. A ticket's wasn't, since `widget_submit` takes any value, so it only counts
   if a session of the same organization holds the same one. Otherwise the ticket is
   treated as having none. An id with padding or a reserved prefix (`email:`,
   `company\n`) is no identity anywhere and creates no Contact, and it vouches for
   nothing.
2. **Sessions.** One Contact per usable `external_user_id`, its email in
   `declared_email`, not `email` (rule 1: nothing there is proven). Otherwise one Contact
   per usable `WidgetSession.email` (lowercased). A session with an id it can't have
   claimed an identity: it gets no Contact, and doesn't fall back on its email.
3. **A session with no identity of its own** (anonymous, no usable email) takes the most
   recent usable email of its tickets, and stores it in `WidgetSession.email` with no
   proof. The service identifies an anonymous session by its own email on every resume
   and would otherwise unlink it (rule 7), which would also leave its next tickets
   without a Contact. It never takes an external id from them: only a valid hash gives
   a session one.
4. **Tickets.** A ticket follows its session, whatever its own values. A ticket with no
   session of its organization, or whose session has no identity at all, goes by its
   vouched external id or else its usable email, or stays unlinked. A ticket whose
   session ended without a Contact (anonymized, or an id it can't have) stays without
   one.
5. **New Contacts** take their seen dates from every row linked to them, and their name
   from the most recent session, or else the most recent ticket. Their `declared_email`
   comes from their session, or else their most recent ticket. A ticket whose external
   id isn't vouched for gives neither a name nor a `declared_email`.

Emails are not marked verified. Existing Contacts are only linked to, never written.
It's idempotent, and `manage.py backfill_contacts` can run it again after a deploy.

Its cost is linear in the rows: new Contacts are filled from one ordered read per batch
of Contacts, and `ANALYZE` runs on `tickets_widgetsession` after sessions are linked and
on `tickets_ticket` before the fill (PostgreSQL only).

---

## 5. API

All endpoints are agent-authenticated and scoped to the agent's organization.

- `GET/POST /api/v1/contacts/`, `GET/PATCH/DELETE /api/v1/contacts/{id}/`
  (search on name/email/declared_email/external_id, filters: company, attributes, last
  seen; NULL `last_seen_at` always sorts last). `declared_email` and `external_id` are
  read-only: an `external_id` set here would give the widget user of that id this
  Contact's history. Changing `email` clears `email_verified_at`. Writing to an
  anonymized Contact is a 409. End users are refused on the whole contacts API.
- `GET/POST /api/v1/contacts/{id}/notes/`.
- `GET /api/v1/contacts/{id}/tickets/`.
- `POST /api/v1/contacts/{id}/export/` — admin only, Celery task, emails the requester a
  ZIP attached (never a URL): `contact.json` (profile, attributes, notes), `tickets.json`
  (tickets, public messages, attachment metadata, the contact's recordings with their
  transcription; never internal notes, nor who at the organization wrote what) and
  `tickets.csv` (formula-like cells escaped). Beyond 20 MB nothing is attached, and the
  requester gets an email saying so.
- `POST /api/v1/contacts/{id}/anonymize/` — admin only, irreversible, idempotent: a
  second call scrubs again and keeps the anonymized email, so it repairs what a stale write
  brought back, and changes nothing, dates included, if there's nothing to repair. Ticket
  writes only save the fields they change, which leaves that window to a widget request.
  Contact: email → `anonymized-{uuid}@example.invalid`, name
  → "Anonymized contact", phone, external_id, declared_email, email_verified_at, avatar,
  job title, locale, timezone and company cleared, attributes emptied,
  `last_contacted_at` cleared, `is_anonymized = True`, notes deleted (free text that can
  hold personal data). Sessions: name, email, external_user_id, email_verified_at and user
  agent cleared, unlinked from the Contact. Tickets, being the Contact's and also, in the
  organization, those with no Contact that are on one of its sessions (an agent cleared
  the Contact) or carry its external id (`widget_submit` takes one unsigned, and links
  nothing): title and description replaced (the widget copies the first message there),
  requester name and email set to the anonymized ones, external_user_id, context_url and
  context_user_agent cleared, `context_metadata` reduced to a whitelist (which also removes
  the `pre_login_*` trace), where only strings of 100 characters at most without `@` stay,
  `widget_session` unlinked. On those tickets, the contact's messages (sender type `user`,
  or written by the requester): body replaced by a placeholder, unlinked from their
  session. Files: the contact's attachments and recordings are deleted, rows and files.
  "The contact's" means uploaded with no user (as the widget does, or by an account since
  deleted) or by the ticket's requester. A requester who's an agent or admin of the
  organization filed the ticket for the contact: what they wrote or uploaded stays. Files
  go once the transaction has committed; a failure is logged with the file's path, and
  doesn't fail the request.
- `GET/POST /api/v1/companies/`, `GET/PATCH/DELETE /api/v1/companies/{id}/`,
  `GET /api/v1/companies/{id}/contacts/`, `GET /api/v1/companies/{id}/tickets/`.
  `external_id` is read-only, as on a Contact: it's what signed widget payloads upsert a
  Company on. `domain` is format-checked and unique per organization; editing it doesn't
  relink existing Contacts. DELETE is admin only and leaves the Contacts without a Company.
- `/api/v1/contact-attributes/`, `/api/v1/company-attributes/` — agents read, admins
  create and PATCH definitions; archive instead of delete (DELETE is a 405). `key` and
  `type` can't change. Removing an enum option leaves stored values alone.

Widget init (`POST` session endpoint) accepts the extended payload
(`traits`, `company`, `email_hash`, `company_hash`). Only a malformed `external_user_id`
is a 400. A number as `name` becomes text and a long one is cut; any other unusable
`name`, `email`, `traits`, `company` or `session_id` counts as absent, so a host page
that gets a field wrong doesn't stop the widget.

Tickets expose a read-only `sender_verified`: whether this ticket's sender proved
being its Contact (HMAC-identified on that Contact, session email verified before the
ticket was written, or the conversation link once the email channel adds it, and never
on a ticket written before a login, rule 8). It relates to the Contact, not to the
ticket's `requester_email`. It's null when there's no outside
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

---

## 8. Known limitations

- An identified Contact with a blank `email` can't take a proven email currently
  held by an email-only Contact, since there's no merge. No access is granted. To
  resolve in the email channel PR, where history reunion needs it, by reassigning that
  unverified Contact's tickets on proof, or with the planned manual merge.
- An unsigned payload can link a Contact without a Company to any existing Company by
  id. It's a claim shown to agents and grants no access.
- A login moves the anonymous session's tickets to whoever logs in on that browser. On
  a shared computer, that can be someone other than who wrote them. `sender_verified`
  stays false on them, and agents see the requester details they were written with.
- A login sets the Contact of every ticket it moves, since a ticket without one can't
  tell an agent's clearing from never having had one. That overrides an agent's choice
  on a ticket of an anonymous session. The email-only Contact they leave is deleted when
  nothing is left on it (rule 8). Otherwise it stays as it is, on its own, with its email
  and name: when it still has another ticket, session or note, or data of its own such as
  a phone or an attribute, and when the identified session ended with no Contact to move
  the tickets to.
- A tab still holding the anonymous session after a login, in another window or as a
  recording popup, gets a 404 on the tickets that moved, misses their replies, and a
  new conversation it starts stays with the anonymous session.
- The widget only sends its stored id on `init()`. `Showdesk.reset()` clears it, so a
  login following a reset can't move anything, and `setUser()` doesn't start a new
  session: identity only reaches the backend on the next `init()`. A single-page app that
  logs in without a reload gets no continuity until then. Plan Task 15 closes this one.
- A vouched external id on a ticket only proves that the id exists in the organization,
  not that this ticket's sender holds it: `widget_submit` can still name a real user. The
  back-fill can link such a ticket, and take a name or a `declared_email` from it, on a
  Contact it creates. `sender_verified` stays false on it, as it has no session of that
  Contact.
- Session ids don't expire and don't rotate. A logged-out session's id stays usable as a
  bearer token through `X-Widget-Session`, on its conversations and its history, for
  whoever kept it: only `POST` resume is gated by the hash (rule 8).
- Pages with and without identity on one origin share the stored id, so each switch from
  a signed page to an unsigned one creates a new anonymous session. The same goes for a
  session proven by `email_hash`, and for the email channel's later proof of ownership
  when it adds one, unless that channel gives the widget something to sign with.
- A wrong `user_hash` returns 403 and the widget doesn't start. A host app signing with
  an old secret loses the widget on its identified pages, not only their history.
- Anonymization leaves personal data in places it can't judge: agent replies and internal
  notes on the tickets (free text that may quote the contact), agents' own attachments and
  recordings (a screenshot of the contact's account, say), and the `requester` user of a
  ticket, an account the Contact doesn't own. It also keeps, on the tickets, the OS, browser
  and screen resolution, and the `language`, `timezone` and other whitelisted values of
  `context_metadata`, the names of their tags, the Contact's seen dates, and whatever text
  an agent searched for in a `SavedView`, which can be the contact's name or address.
- A widget request already past its session lookup when an anonymization commits can
  still write what it holds: a new ticket on the anonymized Contact with the old requester
  details, or one more message on a scrubbed ticket. The window is one request, and
  anonymizing again repairs it. A video being processed at that moment can leave its
  thumbnail on the storage.
- A file that the storage failed to delete is only logged: nothing retries it, and its row
  is gone.
- An export holds the metadata of files, not the files. Past 20 MB it isn't sent at all,
  and there's no other way to get it: both need a download with its own access control.
