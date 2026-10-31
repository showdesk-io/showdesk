# Email Channel (send + receive) — Design Document

> Date: 2026-10-29
> Status: Validated
> Phase: 3.5 (Channels & Integrations)
> Research input: `docs/brainstorm/multi-channel-communication.md` (§1, §6)
> Depends on: `docs/plans/2026-10-29-contacts-design.md`

---

## Goal

Turn Showdesk into a real email helpdesk while keeping a single conversation
across channels:

- an Organization publishes its own support address (e.g. `support@acme.com`,
  hosted on Google Workspace, Microsoft 365 or anything else) and every email
  sent to it opens or continues a ticket;
- a conversation can start in the widget, continue by email and come back to
  the widget — agents see one thread, end-users see their whole history;
- agent replies reach the end-user in the widget when they are there, by a
  repliable email otherwise, with a link to a full-page conversation view;
- replies can be sent **from** the Organization's own domain once it is
  verified.

Everything is optional and off by default for self-hosters; no proprietary
service is required.

---

## 1. Scope and delivery

| PR | Branch | Content |
|---|---|---|
| 1 | `feat/contacts` | Contacts & Companies (separate design). |
| 2 | `feat/email-channel` | Mailboxes, inbound pipeline, threading, repliable outbound mail, presence-aware notifications, conversation page, email proof in the widget. |
| 3 | `feat/sending-domains` | Sending from the Organization's domain (`SendingDomainProvider` adapter, DNS wizard, periodic checks). |

Each PR targets `develop` and is validated on the development environment
before the next one starts.

Out of scope: IMAP polling, Gmail/Microsoft OAuth mailbox connection, renaming
`Ticket` to `Conversation`, WhatsApp/Slack, CSV import, contact merge.

---

## 2. Key decisions

| Topic | Decision | Why |
|---|---|---|
| Integration with the customer's domain | **Forwarding**: the customer forwards `support@acme.com` to a Showdesk inbound address. No change to their MX. | Industry standard (Zendesk, Freshdesk, Help Scout); works with Google Workspace and Microsoft 365. OAuth mailbox access needs Google restricted-scope verification and yearly security assessment. |
| Inbound transport | **django-anymail inbound webhooks**, Postal as the reference provider. | Anymail is already a dependency, verifies provider signatures and normalises every provider to one message object; Postal is open source and self-hostable. Mailgun, Postmark, SES, Mailjet, SendGrid… work by configuration only. |
| Inbound address | `{slug}-{random}@{INBOUND_EMAIL_DOMAIN}`, stored, regenerable. | Readable, not guessable, survives slug changes. |
| Addresses per org | N `Mailbox` rows, each with an optional default team. | `support@` and `billing@` without a later migration. |
| Data model | Keep `Ticket → TicketMessage`; add `channel` and `external_id` to messages, `mailbox` to tickets. | Enough for mixed-channel threads; no churn on API, dashboard and widget. A larger refactor is reconsidered when a third channel is designed. |
| Threading | `In-Reply-To`/`References` → tokenised `Reply-To` → `[SD-123]` subject (only from the ticket's contact) → new ticket. | Robust to clients that drop headers; subject matching cannot be abused by third parties. |
| Notifications | Widget if the end-user is connected, email otherwise (and email if still unread after a delay). | No duplicates while chatting; nothing gets lost when the tab is closed. |
| Conversation page | Signed link, valid 30 days, renewable by email. | One click from the email; a forwarded link exposes a single ticket. |
| Email → widget history | Requires proof of email ownership: signed email from the host app, or a one-time code. | The widget email is page-supplied and can be forged. |
| Sending domain | Automatic via provider adapter (Scaleway TEM API first), `manual` adapter for self-hosting, fallback to the inbound address. | `From: support@acme.com` without DKIM alignment fails DMARC. |

---

## 3. Data model (PR 2)

New app: `apps.email_channel`.

```
Mailbox
  organization              FK
  name                      "Support"
  local_part                "acme-x7k2m9" (unique) → {local_part}@{INBOUND_EMAIL_DOMAIN}
  public_address            "support@acme.com" (optional; display, From in PR 3)
  default_team              FK Team, null
  is_active                 bool
  forwarding_confirmation   JSON {url, code, detected_at} (Gmail confirmation mail)

InboundEmail                one row per received email (log, replay, idempotency)
  mailbox, ticket, message  FKs, null
  message_id                Message-ID header
  sender, recipients, subject
  raw                       FileField (.eml, S3), purged after retention
  status                    pending | processed | ignored | rejected | failed
  reason                    machine-readable reason (auto_reply, bounce, loop, spam,
                            rate_limited, unknown_recipient, forwarding_confirmation…)
  received_at, processed_at
  unique (message_id, mailbox)

Ticket          + mailbox               FK Mailbox, null
TicketMessage   + channel               widget | email | agent | api | system (default widget)
                + external_id           Message-ID (in/out), indexed
                + email_delivery_status "" | sent | failed
```

`Ticket.source` keeps the origin channel. Existing messages are back-filled
(`channel = widget` for user messages, `agent` for agent messages, `system`
for system messages).

Identifiers:

- **Outbound Message-ID**: `<{message_uuid}@{INBOUND_EMAIL_DOMAIN}>`.
- **Reply address**: `reply+{token}@{INBOUND_EMAIL_DOMAIN}` where
  `token = {short_ticket_id}.{truncated HMAC}` with a key derived from
  `SECRET_KEY` and a dedicated salt — verifiable without a lookup, unforgeable.

---

## 4. Inbound pipeline (PR 2)

```
provider ──signed POST──▶ /anymail/<esp>/inbound/   (Anymail verifies signature)
                              │ anymail `inbound` signal
                              ▼
                     handler: store InboundEmail + raw .eml, return 200
                              │ Celery
                              ▼
            process_inbound_email: recipient → filters → threading → content → write
```

The webhook handler does no parsing beyond what is needed for idempotency so
the provider gets a fast response. `manage.py ingest_eml <file|->` feeds the
same pipeline (testing, self-hosters, replaying).

### 4.1 Recipient resolution

1. `reply+{token}@…` → ticket (and its mailbox).
2. Otherwise search, in order, the envelope recipient (when the provider
   exposes it), `Delivered-To`, `X-Original-To`, `X-Forwarded-To`, `To`, `Cc`
   for an active Mailbox matching `local_part@INBOUND_EMAIL_DOMAIN` **or**
   `public_address`. This covers forwarding, where `To` stays
   `support@acme.com`.
3. Nothing found → `rejected` / `unknown_recipient`. Inbound email never
   creates an Organization or a Mailbox.

### 4.2 Filters (status `ignored`, reason recorded)

- **Gmail forwarding confirmation** (from `forwarding-noreply@google.com`):
  extract link and code into `Mailbox.forwarding_confirmation`, notify org
  admins; no ticket.
- **Auto-replies**: `Auto-Submitted` other than `no`, `Precedence:
  bulk|junk|list`, `X-Autoreply`, `X-Autorespond`, `List-Id`.
- **Bounces**: `multipart/report` DSN, `mailer-daemon@`, `postmaster@`. When
  the bounce references one of our Message-IDs, set
  `email_delivery_status = failed` on that message.
- **Loops**: sender on `INBOUND_EMAIL_DOMAIN`, already-known Message-ID.
- **Spam**: provider verdict/score when available (`spam_detected`).
- **Rate limit**: more than `INBOUND_EMAIL_RATE_LIMIT_PER_HOUR` (default 20)
  emails from the same sender to the same mailbox.

Ignored and rejected emails are listed in the Mailbox settings.

### 4.3 Threading

1. `In-Reply-To` / `References` matching a stored `TicketMessage.external_id`
   of the same organization.
2. Reply token.
3. `[SD-123]` in the subject, **only** if the sender is the ticket's contact.
4. Otherwise a new ticket. A `Fwd:` / `Tr:` / `WG:` subject without matching
   headers always creates a new ticket.

If the matched ticket is resolved/closed: reopen it when the last activity is
within `INBOUND_EMAIL_REOPEN_DAYS` (default 7); otherwise create a new ticket
whose `context_metadata` references the previous one.

### 4.4 Content

- Prefer `text/plain`; otherwise convert sanitized HTML to text.
- Strip quoted history: first at our own marker
  (`-- Reply above this line --`), then heuristically (`On … wrote:`,
  `Le … a écrit :`, `>` blocks, Outlook separators) using
  `email-reply-parser`. Agents can always open the original email.
- Attachments → `TicketAttachment` with the same extension blocklist as widget
  uploads; total size capped by `INBOUND_EMAIL_MAX_SIZE_MB` (default 25);
  oversize parts are dropped and noted in the message.

### 4.5 Write

- Resolve or create the Contact from `From` (declared, unverified email) via
  `apps.contacts.services`.
- New ticket: `source = email`, title = subject (fallback "(no subject)"),
  `mailbox`, `assigned_team = mailbox.default_team`, `contact`,
  `requester_email`/`requester_name`.
- `TicketMessage(channel=email, sender_type=user, external_id=Message-ID)`,
  then the usual real-time events (agents and widget) and agent notifications.

### 4.6 Errors

Exceptions mark the row `failed` and the task retries with backoff; an admin
action replays any `InboundEmail`. Idempotency relies on
`(message_id, mailbox)`.

---

## 5. Outbound mail and notifications (PR 2)

### 5.1 Reply email to the requester

Built on the existing `send_ticket_reply_email` task and `ticket_reply`
template:

- `From`: `"{email_from_name or org name}" <{local_part}@{INBOUND_EMAIL_DOMAIN}>`
  (PR 3: `public_address` when its domain is verified for sending).
- `Reply-To`: tokenised reply address.
- `Message-ID` stored in `external_id`; `In-Reply-To`/`References` built from
  the ticket's `external_id` chain so mail clients thread correctly.
- Subject `Re: [SD-123] {title}`.
- Body: reply marker, the new (unread) replies, the last three messages as
  context, a "View conversation" button (signed link, §6).
- Tickets without a mailbox fall back to the organization's first active
  mailbox, else to `DEFAULT_FROM_EMAIL` (current behaviour) with the
  `Reply-To` as soon as `INBOUND_EMAIL_DOMAIN` is set.

### 5.2 When to email

For a public agent reply:

1. Requester's last message came by email → email now.
2. Else, widget session not connected → email now.
3. Else → widget only, plus an email scheduled after
   `WIDGET_UNREAD_EMAIL_DELAY_MINUTES` (default 5) that is skipped if
   `Ticket.widget_last_read_at` covers the reply. The scheduled email groups
   every unread reply.

Presence: `WidgetConsumer` sets `widget_presence:{session_id}` in Redis with a
60 s TTL, refreshed by a 25 s client ping, deleted on disconnect.

`Contact.is_unsubscribed` suppresses notification emails, except on tickets
the contact opened by email (the channel they chose).

Agent notifications ("the requester replied") are unchanged apart from
showing the channel.

---

## 6. Conversation page and email proof (PR 2)

### 6.1 Full-page conversation

- Public frontend route `/c/:token`, branded with the organization's logo and
  colour, no account needed: full public thread (no internal notes), reply
  box, attachments. Messages posted there use `channel = widget`.
- `token` = `django.core.signing` of `{ticket_id, contact_id}` with a dedicated
  salt and `max_age = CONVERSATION_LINK_MAX_AGE_DAYS` (default 30). Every email
  carries a fresh link.
- Expired link → "Send me a new link": the new link goes **only** to the
  ticket contact's email; the requester never chooses the address.
- Opening a valid link proves mailbox ownership → `Contact.email_verified_at`.
- API, scoped to the token's ticket and throttled:
  `GET /api/v1/conversations/{token}/`, `POST …/messages/`,
  `POST …/attachments/`, `POST /api/v1/conversations/renew/`.
- No real-time in V1: the page polls every 15 s while visible.

### 6.2 Email-born tickets in the widget

- **Signed email** (`email_hash`, delivered with Contacts): the session is
  verified on init.
- **One-time code**: when a session has a declared but unproven email and the
  Contact owning it in `Contact.email` has tickets outside this session, the
  widget offers
  "You have N email conversations — get a code to see them". Six-digit code
  via the existing `OTPCode` (expiry, attempt limit, throttling).
- Proof is stored **per session** (`WidgetSession.email_verified_at`); a
  verification made elsewhere never opens anything in this session.
- Widget history = session tickets ∪ `external_user_id` tickets (unchanged) ∪
  the Contact's tickets **if** the session is email-verified or identified by
  HMAC on that Contact.
- History through an HMAC-identified Contact relies on `Contact.email` being
  proven only (or set by an agent): an identified session's unproven email goes to
  `Contact.declared_email`, so forging somebody's address can never attach their
  email-born tickets to the forger's Contact. `declared_email` is never used to
  match a Contact, to send mail or to open history. The rule is in the Contacts
  design, §3.

---

## 7. Sending domains (PR 3)

### 7.1 Model

`OrganizationDomain` already proves domain ownership (DNS TXT or admin email)
and guarantees one verified owner per domain. It gains:

```
is_sending               bool
sending_status           "" | pending | verified | failed
sending_provider_ref     provider-side id
sending_dns_records      JSON [{type, name, value}] to publish
sending_last_checked_at, sending_last_error
```

Rules:

- A domain is registered with the provider only after ownership is verified.
- `From = Mailbox.public_address` iff its domain row is ownership-verified
  **and** `sending_status = verified`; otherwise the inbound-address fallback.
- On ownership transfer to another organization, the previous registration is
  removed and the previous owner falls back automatically.

### 7.2 Provider adapter

```python
class SendingDomainProvider(Protocol):
    def register(self, domain: str) -> RegisteredDomain: ...  # ref + dns records
    def check(self, ref: str) -> DomainCheck: ...             # status + error
    def remove(self, ref: str) -> None: ...
```

Selected by `SENDING_DOMAIN_PROVIDER`:

- `none` (default): feature hidden, always fallback.
- `manual`: the operator registers domains with their sending service;
  Showdesk shows the expected records built from `SENDING_DOMAIN_SPF_INCLUDE`
  and `SENDING_DOMAIN_DKIM_SELECTOR` and checks them itself with `dnspython`.
- `scaleway_tem`: Scaleway Transactional Email API (create domain → DKIM
  config + SPF include, trigger check, read status). Settings
  `SCW_TEM_SECRET_KEY`, `SCW_TEM_PROJECT_ID`, `SCW_TEM_REGION` (default
  `fr-par`).

### 7.3 Checks

Celery beat: every 15 min for `pending` domains (up to 72 h, then `failed`),
daily for `verified` ones. A regression switches back to the fallback and
emails org admins.

### 7.4 UI

Mailbox settings, "Send from support@acme.com" wizard: (1) domain ownership
(existing flow), (2) DNS records with copy buttons, (3) status and "Check now".
The same screen documents forwarding for Google Workspace / Gmail (including
the detected confirmation link/code) and Microsoft 365 (external forwarding is
blocked by default by the outbound anti-spam policy and must be allowed).

---

## 8. Configuration

All new variables are documented in `.env.example` with safe defaults.

| Variable | Default | PR | Purpose |
|---|---|---|---|
| `INBOUND_EMAIL_DOMAIN` | empty (channel disabled) | 2 | Domain receiving inbound mail and reply tokens. |
| `ANYMAIL_POSTAL_WEBHOOK_KEY` | empty | 2 | Postal public key (signature check). Other providers use their Anymail setting. |
| `INBOUND_EMAIL_REOPEN_DAYS` | 7 | 2 | Reopen window for resolved/closed tickets. |
| `INBOUND_EMAIL_MAX_SIZE_MB` | 25 | 2 | Attachment size cap. |
| `INBOUND_EMAIL_RATE_LIMIT_PER_HOUR` | 20 | 2 | Per sender and mailbox. |
| `INBOUND_EMAIL_RAW_RETENTION_DAYS` | 30 | 2 | Raw `.eml` retention. |
| `WIDGET_UNREAD_EMAIL_DELAY_MINUTES` | 5 | 2 | Delay before emailing an unread widget reply. |
| `CONVERSATION_LINK_MAX_AGE_DAYS` | 30 | 2 | Conversation link lifetime. |
| `SENDING_DOMAIN_PROVIDER` | `none` | 3 | `none`, `manual`, `scaleway_tem`. |
| `SENDING_DOMAIN_SPF_INCLUDE`, `SENDING_DOMAIN_DKIM_SELECTOR` | empty | 3 | `manual` adapter. |
| `SCW_TEM_SECRET_KEY`, `SCW_TEM_PROJECT_ID`, `SCW_TEM_REGION` | empty / `fr-par` | 3 | `scaleway_tem` adapter. |

Operators must publish SPF/DKIM for `INBOUND_EMAIL_DOMAIN` with their sending
service, since fallback mail is sent from that domain, and point its MX to the
inbound provider.

---

## 9. Testing and validation

- **Fixture corpus** of real-world `.eml` files: replies from Gmail, Outlook,
  Apple Mail, Thunderbird (EN/FR), Gmail and Microsoft 365 forwards, manual
  `Fwd:`, out-of-office, DSN bounce, Gmail forwarding confirmation, oversize
  and blocked attachments, HTML-only mail. Each pipeline step is tested in
  isolation, then end to end through the Anymail view.
- **Postal signature**: RSA key pair generated in the test; forged signatures
  are rejected.
- **Providers**: only the HTTP boundary (TEM) or DNS resolver (`manual`) is
  mocked.
- **Security**: forged reply token, `[SD-123]` from a third party, expired or
  tampered conversation link, renewal to another address, unverified widget
  session requesting a Contact's tickets, cross-organization access.
- **Frontend / widget**: Vitest for the conversation page, Mailbox settings
  and wizard, widget code banner; lint with zero warnings; production build.
- **Development environment**: outbound mail is captured by Mailpit (headers
  checked there); inbound is exercised with `manage.py ingest_eml` using
  replies crafted from captured mails, until an inbound provider is connected.
