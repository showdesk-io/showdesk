# Email Channel (send + receive) — Design Document

> Date: 2026-10-29
> Status: Validated. PR 2 built on `feat/email-channel` (2026-11-03), see §10.
> PR 3 built on `feat/sending-domains` (2026-11-04), see §11.
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

The envelope recipient is what the provider delivered to; the headers are
whatever the sender wrote. So when the provider gives an envelope recipient, it
alone is resolved. The headers are only searched for a mail without one, as fed
to `ingest_eml` without `--recipient`.

1. `reply+{token}@…` → ticket (and its mailbox).
2. Otherwise an active Mailbox matching `local_part@INBOUND_EMAIL_DOMAIN`
   **or** `public_address`: the envelope recipient, or, without one, the first
   match in `Delivered-To`, `X-Original-To`, `X-Forwarded-To`, `To`, `Cc`.
   A forward is delivered to the inbound address while `To` stays
   `support@acme.com`.
3. Nothing found → `rejected` / `unknown_recipient`; a mailbox or ticket of an
   inactive organization → `rejected` / `inactive_organization`. Inbound email
   never creates an Organization or a Mailbox. Such a row keeps the sender,
   subject and reason, never the raw mail, and at most
   `INBOUND_EMAIL_RATE_LIMIT_PER_HOUR` of them are kept per sender (and mailbox)
   and hour, and at most `INBOUND_EMAIL_MAILBOX_RATE_LIMIT_PER_HOUR` overall. A mail rejected without a mailbox doesn't make the same mail,
   delivered to a valid reply address, a duplicate.

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
  emails from the same sender to the same mailbox, or more than
  `INBOUND_EMAIL_MAILBOX_RATE_LIMIT_PER_HOUR` (default 200) to the mailbox from
  anyone. Checked before anything else a mail can make us do, such as mailing
  the admins a forwarding confirmation (at most once per mailbox per 10 minutes).
- **Duplicates**: a Message-ID already on a message of the organization (one
  mail sent to a reply address and to the inbound address arrives twice).

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

The same window applies to the requester's other writes, on every ticket and also
on an instance that receives no mail: a message or file from the widget or the
conversation page reopens a ticket within it, and past it is refused (409, the
widget and the page then offer a new conversation, and show it closed up front
from `can_reply`).

### 4.4 Content

- Every inline `text/plain` part, in order; otherwise convert the HTML to text.
  A part declaring an unknown charset is read as UTF-8, with replacement.
- Strip quoted history, line by line on bounded lines, in linear time (a
  regex library such as `email-reply-parser` is cubic on hostile text): at our
  own marker (`-- Reply above this line --`), at an `On … wrote:` /
  `Le … a écrit :` attribution (also wrapped over two lines), at an Outlook
  header block (three header lines or more, with From/De, Sent/Envoyé/Date and
  To/À or Subject/Objet), then a trailing block of `>` lines. Nothing is taken
  for a signature. Agents can always open the original email.
- Attachments → `TicketAttachment` with the same extension blocklist as widget
  uploads; total size capped by `INBOUND_EMAIL_MAX_SIZE_MB` (default 25), and at
  most 50 files; blocked, oversize and extra parts are dropped and named in a note
  appended to the message. A file keeps its base name only.
- HTML is reduced to its text by a parser (links as `text (url)`, quotes as `>`
  lines): no markup reaches a message, whose body is always shown as text.
- A forward (`Fwd:`, `Fw:`, `TR:`, `WG:` subject) keeps its quoted part: it is the
  request. A mail that is only history keeps its full text.

### 4.5 Write

- Resolve or create the Contact from `From` (declared, unverified email) via
  `apps.contacts.services`, for a new ticket only: a mail on an existing ticket
  keeps its Contact and shows its own sender (`external_sender`), as a colleague
  in copy would. The address of an agent, admin or superuser of the organization
  never becomes a Contact, and an anonymized Contact's address gets none.
- New ticket: `source = email`, title = subject (fallback "(no subject)"),
  `mailbox`, `assigned_team = mailbox.default_team`, `contact`,
  `requester_email`/`requester_name`.
- `TicketMessage(channel=email, sender_type=user, external_id=Message-ID)`,
  then the usual real-time events (agents and widget) and agent notifications.

### 4.6 Errors

Exceptions mark the row `failed` and the task retries with backoff. An admin
replays a `failed` row, from the Django admin (a platform operator, on any
organization's rows, including those without a mailbox) or from the API (an
organization admin, on the rows of their organization's mailboxes only): the row goes back to `pending` before
it's queued, so a replay asked twice runs once. Idempotency relies on
`(message_id, mailbox)`, and the task does nothing unless the row is `pending`
or `failed`, under its row lock: it can be queued twice.

The raw `.eml` doesn't hold what the provider said about it: the row stores the
envelope recipient and sender, and the provider's spam verdict and score (for
Postal, its `X-Postal-Spam: yes` header). Processing rebuilds the recipient and
the verdict from those columns, never from the headers when an envelope was
stored.
The row's `ticket` is the ticket the mail landed on; a reply address's ticket
is found again from the stored envelope.

A mail nested deeper than the parser can go is stored `rejected` /
`unparseable` (known by its content's hash) and the webhook answers 200, so
the provider stops retrying. A stored mail that can't be parsed, or whose raw
file is gone, is `failed` with `unparseable` or `raw_missing`, without retries.
Attachment files are stored before the transaction that writes the ticket (and
takes the organization's row lock for its reference), and deleted if it fails.

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
- The replies' files go as real attachments, up to `REPLY_EMAIL_ATTACHMENTS_MAX_MB`
  (10) in all as sent; the others are
  only named, with a pointer to the conversation link when there is one. A mail
  never carries a storage URL. The agent's app uploads the files to the ticket
  first, then posts the reply naming them (`attachment_ids`): they're linked
  before the reply is announced or mailed.
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

As built: the key holds the socket's channel name, and a socket only deletes its
own, so the late disconnect of a socket a reconnect replaced leaves the new one
present. "Connected" means any widget session that would see the reply: the
ticket's own, and those entitled to it through the Contact's history (§6.2). A
cache outage reads as "not connected", so the reply is emailed at once rather
than lost. Two tabs share one key: see Known limitations.

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
- `token` = `django.core.signing` of `{ticket_id, contact_id, keyed hash of the
  address mailed}` (never the address in clear: a link is forwarded and logged; keyed,
  so a list of addresses can't be hashed to find it) with a dedicated salt and
  `max_age = CONVERSATION_LINK_MAX_AGE_DAYS` (default 30). Every email carries a fresh
  link. A link opens its conversation only while the ticket is still its contact's,
  the contact still holds the address mailed and isn't anonymized, and no login moved
  the ticket: once an agent corrects a contact's address, the previous address's
  holder loses the conversation.
- Expired link → "Send me a new link": the new link goes **only** to the
  ticket contact's email; the requester never chooses the address. At most once per
  ticket per hour and three times per contact per day, and only for a link up to 180
  days old; past that the page says to contact support.
- Opening a valid link proves mailbox ownership → `Contact.email_verified_at`. Neither
  opening it nor posting through it makes the ticket's `sender_verified` true: that
  proves who holds the mailbox now, not who wrote the ticket. The page shows no name or
  address on the requester's side, and opening it counts as reading the replies.
- API, scoped to the token's ticket and throttled:
  `GET /api/v1/conversations/{token}/`, `POST …/messages/`,
  `POST …/attachments/`, `POST /api/v1/conversations/renew/`.
- No real-time in V1: the page polls every 15 s while visible.

### 6.2 Email-born tickets in the widget

- **Signed email** (`email_hash`, delivered with Contacts): the session is
  verified on init.
- **One-time code**: when a session has a declared but unproven email, the widget
  offers "Have earlier conversations by email? Get a code", whatever exists behind
  the address: the email is only declared, so a count would tell anyone whether an
  address is a customer's (Decision A of the implementation plan). The route always
  answers 202, and a code is only mailed when the Contact owning the address in
  `Contact.email` has tickets outside this session that the proof would open.
  Six-digit code via the existing `OTPCode`, with its own purpose (`widget_email`)
  and throttles, so it neither spends nor cancels a login code, and good only in the
  organization and the session that asked for it. A code proof is recorded as such
  (`email_proof_source = code`) and survives an unsigned init, but not one declaring
  another email.
- A proof is about the address it was made for (`WidgetSession.email_verified_for`),
  written only if the session still has that address: a proof racing an email change
  proves nothing.
- From the history, a session writes on its own tickets, on tickets opened by email,
  and on those opened by a session that's entitled too. Others are read-only there:
  a message would reach whoever opened them.
- Proof is stored **per session** (`WidgetSession.email_verified_at`); a
  verification made elsewhere never opens anything in this session.
- Widget history = session tickets ∪ `external_user_id` tickets (unchanged) ∪
  the Contact's tickets **if** the session is email-verified or identified by
  HMAC on that Contact.
- History through an HMAC-identified Contact relies on `Contact.email` being
  proven only (or set by an agent): an identified session's unproven email goes to
  `Contact.declared_email`, so forging somebody's address can never attach their
  email-born tickets to the forger's Contact. `declared_email` is never used to
  match a Contact or to open history. It is only mailed an agent's reply, as the
  last fallback of a ticket with no `requester_email` and a Contact with no `email`
  (Contacts §5): that reply carries no conversation link, which only goes to the
  address the Contact holds. The rule is in the Contacts design, §3.

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
- `manual`: the operator's sending service relays for any domain and signs
  every one with a single DKIM key, published once at
  `<selector>._domainkey.<INBOUND_EMAIL_DOMAIN>`. Showdesk shows the expected
  records built from `SENDING_DOMAIN_SPF_INCLUDE` and
  `SENDING_DOMAIN_DKIM_SELECTOR` (an SPF include, and a DKIM CNAME
  `<selector>._domainkey.<domain>` to the operator's key) and checks them
  itself with `dnspython`: following the CNAME must give the operator's key.
- `scaleway_tem`: Scaleway Transactional Email API (create domain → DKIM
  config + SPF include, trigger check, read status). Settings
  `SCW_TEM_SECRET_KEY`, `SCW_TEM_PROJECT_ID`, `SCW_TEM_REGION` (default
  `fr-par`).

### 7.3 Checks

Celery beat: every 15 min for `pending` domains (up to 72 h, then `failed`),
daily for `verified` ones. A regression switches back to the fallback and
emails org admins.

### 7.4 UI

PR 2 ships the Settings "Email" tab without the sending wizard: mailboxes,
their inbound address with a copy button, public address, default team,
active toggle, address regeneration (confirmed first), the forwarding steps
below, the detected Gmail code and link, and the log of ignored, rejected and
failed mail with a replay for admins. The tab is hidden while
`INBOUND_EMAIL_DOMAIN` is empty.

PR 3 adds to it a "Send from support@acme.com" wizard: (1) domain ownership
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
| `INBOUND_EMAIL_REOPEN_DAYS` | 7 | 2 | Reopen window for resolved/closed tickets, for mail and for widget and conversation page writes alike (§4.3). |
| `REPLY_EMAIL_ATTACHMENTS_MAX_MB` | 10 | 2 | Files a reply mail attaches in all, counted as sent (base64); the others are named (§5.1). |
| `INBOUND_EMAIL_MAX_SIZE_MB` | 25 | 2 | Attachment size cap. |
| `INBOUND_EMAIL_RATE_LIMIT_PER_HOUR` | 20 | 2 | Per sender and mailbox; also bounds the rejected rows kept per sender (§4.1). |
| `INBOUND_EMAIL_MAILBOX_RATE_LIMIT_PER_HOUR` | 200 | 2 | Per mailbox, all senders; also bounds the rejected rows kept overall (§4.1). |
| `INBOUND_EMAIL_RAW_RETENTION_DAYS` | 30 | 2 | Raw `.eml` retention, purged daily; the row stays, and pending or failed mail keeps its file. |
| `INBOUND_EMAIL_LOG_RETENTION_DAYS` | 90 | 2 | Log of received mails (rows), purged daily; pending or failed ones stay. |
| `WIDGET_UNREAD_EMAIL_DELAY_MINUTES` | 5 | 2 | Delay before emailing an unread widget reply. |
| `CONVERSATION_LINK_MAX_AGE_DAYS` | 30 | 2 | Conversation link lifetime. |
| `SENDING_DOMAIN_PROVIDER` | `none` | 3 | `none`, `manual`, `scaleway_tem`. |
| `SENDING_DOMAIN_SPF_INCLUDE`, `SENDING_DOMAIN_DKIM_SELECTOR` | empty | 3 | `manual` adapter: the SPF include customers add, and the selector of the operator's DKIM key, published at `<selector>._domainkey.<INBOUND_EMAIL_DOMAIN>`, which customers point to with a CNAME. |
| `SCW_TEM_SECRET_KEY`, `SCW_TEM_PROJECT_ID`, `SCW_TEM_REGION` | empty / `fr-par` | 3 | `scaleway_tem` adapter. |

Operators must publish SPF/DKIM for `INBOUND_EMAIL_DOMAIN` with their sending
service, since fallback mail is sent from that domain, and point its MX to the
inbound provider.

### Known limitations

- A mail's `From` is forgeable. Anyone can send mail under a real customer's
  address and use up that address's quota (`INBOUND_EMAIL_RATE_LIMIT_PER_HOUR`
  per mailbox): the customer's own mail is then ignored, as `rate_limited`, for
  the rest of the hour. A forger changing the `From` at each mail is bounded by
  `INBOUND_EMAIL_MAILBOX_RATE_LIMIT_PER_HOUR` (200) per mailbox, which then also
  ignores everyone's mail for the hour. Admins see both in the mailbox's log.

- Presence is one key per widget session. With the widget open in two tabs,
  closing one deletes the key until the other's next ping, 25 s at most: an
  agent's reply in that window is emailed at once instead of waiting.

- `Mailbox.public_address` is unique across organizations, and a new or
  changed one needs its domain verified by the mailbox's organization. A
  later verification of that domain by another organization frees it (and
  drops the previous owner's sending setup). Webmail addresses
  (`support.acme@gmail.com`) can't be public addresses: such a mailbox is
  reached through its inbound address, and replies come from it.

- A Scaleway TEM domain revoked by a disable or a transfer is assumed to be
  registrable again under the same name; that is not confirmed until tested
  with a real key. If TEM refused, enabling would answer 409
  `provider_conflict` and an operator would have to clear the name.

- A public address saved while its domain changes hands: the address is
  validated against the domain's owner, then saved, and a verification by
  another organization in between frees the addresses saved before it only.
  The loser keeps the address until it edits it, but can't send from it (its
  row isn't verified); the new owner gets "already used" for it. An operator
  can clear it in the Django admin.

- A webmail provider missing from `PUBLIC_EMAIL_DOMAINS` (in code; the
  `SHOWDESK_PUBLIC_EMAIL_DOMAINS` variable its comment mentions is not read)
  is an ordinary domain: its first user can verify it by admin email, which
  frees the public addresses other organizations had on it. Sending from it
  still needs its DNS (the `_showdesk` TXT), which nobody but the provider
  has. Add such providers to the list.

- Two checks of the same domain (the periodic one and a "Check now") may
  finish out of order, the older result written last. That is rare (checks
  take seconds, "Check now" is rate-limited) and bounded: the next check, at
  most 15 minutes away for a pending domain, writes the current state.

- The widget code task's broker message carries the widget session's id, a bearer
  token for that session, and the address. The code itself never does: the task
  that sends it gets the code's id. Anyone who can read the broker's queue can use
  the session id as the widget would.

- The per-address code throttles (`WIDGET_EMAIL_CODE_EMAIL_RATE`,
  `WIDGET_EMAIL_VERIFY_EMAIL_RATE`) count an address across every organization: a
  visitor asking for codes in one organization's widget uses up what the same
  address can ask for in another's.

- A ticket filed through `widget_submit` has no session, and its external id and
  address come with the public token alone. It shows in the history of the user
  with that external id, read-only: a message there would go to the address it
  names.

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

---

## 10. As built (PR 2)

The implementation plan (`docs/plans/2026-11-01-email-channel-plan.md`) made
these choices beyond this design. Each one is pinned by a test.

| # | Choice | Why |
|---|---|---|
| 1 | Only the configured provider's webhook is mounted: `/anymail/postal/inbound/` needs `ANYMAIL_POSTAL_WEBHOOK_KEY`, the rest of `anymail.urls` needs `ANYMAIL_WEBHOOK_SECRET`. | Without a secret, Anymail's basic-auth check only warns: any other provider's inbound route would take a forged mail. |
| 2 | Our own `PostalInboundView`, subclassing Anymail's. | Anymail decodes the raw message as UTF-8 (an 8-bit Latin-1 mail was a 500) and reads it through `request.body`, capped far below `INBOUND_EMAIL_MAX_SIZE_MB`. |
| 3 | `TicketMessage.external_sender`: the display name and address of the mail's `From`. | A third party's reply on a thread shows who wrote it. Anonymization clears it. |
| 4 | The raw `.eml` never gets a URL, in the API or the Django admin. Agents of the ticket's organization download it from `GET /api/v1/tickets/{id}/messages/{mid}/original/` (`message/rfc822`, attachment, `nosniff`); a purged one is a 404. | The default storage builds URLs, and a mail holds personal data. |
| 5 | Anonymization deletes the contact's `InboundEmail` rows and raw files (its own, its tickets', those sent from its address), the organization's widget codes mailed to its address or its sessions, and clears `external_id` and `external_sender` on its messages. Expired one-time codes, of every purpose, are purged daily. | Otherwise the raw mail keeps everything the anonymization removes. |
| 6 | The conversation token carries a keyed hash of the address it was mailed to (16 hex characters of an HMAC-SHA256 of the lowercased address, with its own salt), never the address. A link opens its conversation, and verifies the contact, only while the contact's email has that hash. | An agent correcting a contact's email must neither let an old link prove the new address nor keep the old address's holder in the conversation. |
| 7 | The conversation link never makes a ticket's `sender_verified` true. | It proves who holds the mailbox now, not who wrote the ticket. |
| 8 | `OTPCode.purpose` (`login`, `widget_email`), with separate throttles. | A widget visitor can't spend, cancel or exhaust someone's login codes. |
| 9 | `WidgetSession.email_proof_source` (`signed`, `code`); the logout rule (Contacts §3 rule 8) only applies to `signed`. | A host page that never signs would lose a code proof at the next page load. |
| 10 | Agents' own addresses never become contacts on inbound mail. | Contacts §5: an agent, admin or superuser never becomes a Contact. |
| 11 | Reuniting history on proof (Contacts §8) moves tickets, sessions and notes from the email-only contact to the identified one, fills the blanks, keeps an unsubscription, then deletes the email-only row. | The email has to move for the proof to hold. |

Decisions taken on 2026-11-03:

- **A. The widget's code banner** is the same neutral one for every unproven
  email, the route always answers 202, and a code is only mailed when there's
  something to see (§6.2).
- **B. Unsubscribed contacts** get no email for a widget ticket and find the
  reply in the widget; tickets they opened by email still get replies (§5.2,
  and Contacts §5 corrected accordingly).

What agents and admins have:

- `/api/v1/mailboxes/`: agents read, admins create and edit (the serializer runs
  `Mailbox.full_clean()`, so the inbound-domain and team checks apply; a public
  address already taken is a 400 on that field). Mailboxes are deactivated,
  never deleted, since their log would go with them. The Gmail confirmation is
  only sent to admins. `POST …/{id}/regenerate-address/` (admins).
- `GET /api/v1/mailboxes/{id}/inbound/`: the paginated log of the mailbox's
  `ignored`, `rejected` and `failed` mail. Mail no mailbox was found for stays in
  the Django admin.
- `POST /api/v1/inbound-emails/{id}/replay/` (admins, `failed` rows of their
  organization only; 409 otherwise), and the same replay as a Django admin action.
- The organization payload carries `inbound_email_enabled` and
  `inbound_email_domain`, which show or hide the Settings "Email" tab.
- On a ticket: a channel badge per message, the mail's sender, "View original"
  (downloaded through the authenticated API client), and "Not delivered by email"
  when a reply bounced. The Gmail confirmation link is only linked when it's an
  https link to `mail.google.com` or `mail-settings.google.com`, checked again in
  the browser.
- `manage.py seed` adds a "Support" mailbox to the demo organization when
  `INBOUND_EMAIL_DOMAIN` is set.

Writes from the widget follow the reopen window of §4.3, on every ticket, as the
conversation page's do: `widget_conversation` returns `can_reply`, and a write past
the window is a 409.

Without `INBOUND_EMAIL_DOMAIN` (an instance that receives no mail):

- The widget never offers the email code (`email_proof_offered` is false), and the
  code routes answer as when a proof would open nothing: no conversation came by
  email.
- The conversation link, its page and its API stay available: reply mails still
  carry the link, a useful way back to the conversation on its own.
- The reopen window still applies to widget and conversation page writes.

---

## 11. As built (PR 3)

The implementation plan (`docs/plans/2026-11-04-sending-domains-plan.md`) made
these choices beyond this design. Each one is pinned by a test.

| # | Choice | Why |
|---|---|---|
| 1 | `is_sending` is a third purpose of a domain row (at least one of branding, routing, sending). `sending_status` (`""`, `pending`, `verified`, `failed`) is the provider's state. Turning sending off removes the registration and resets the status to `""`, keeping the purpose. | A domain proven only to send from it needs a row; the purpose is the admin's intent, the status the provider's. |
| 2 | `sending_requested_at`: when the current pending cycle started. | The 72 h window of §7.3 needs a start no other date gives. |
| 3 | A new or changed public address needs its domain verified by the mailbox's organization; an unchanged legacy one is left alone. | Reserving `support@bigcorp.com` now needs `bigcorp.com`'s proof. |
| 4 | When an organization's ownership of a domain is verified (DNS or admin email), inside that transaction, other organizations' mailboxes lose their public address on it and their rows of it lose their sending state. A data migration freed the addresses already squatted. | A squatter or a previous owner must not keep the address, nor send from it. |
| 5 | A registration a row lets go of (turned off, replaced, lost with the domain, deleted with the row or its organization, made but never stored) becomes a `SendingRemoval` in the transaction that clears the row's ref, kept until the provider that made it confirms. Its task retries 8 times with a growing delay; an hourly sweep queues again any not tried for 3 h. While one exists for a domain (one left to another provider aside: choice 15), enabling sending on it is a 409 `removal_pending`. `manual` has nothing to remove and records none. | A removal outlives its row and must not race the new owner's registration of the same name. Nothing stays stuck; retries show in the Django admin (read-only). |
| 6 | `manual` asks for an SPF include and a DKIM **CNAME** `<selector>._domainkey.<domain>` → `<selector>._domainkey.<INBOUND_EMAIL_DOMAIN>`, and checks that the key found through it is the operator's. | Showdesk can't know a per-domain key it didn't create; one key the operator publishes is checkable, and any self-hosted signer can use it for every domain. |
| 7 | A check that can't conclude (DNS timeout, provider HTTP error, operator key missing) changes nothing; a verified row stays due for the next periodic check. | A resolver hiccup must not flip every domain to the fallback and mail every admin. |
| 8 | Transitions: pending → verified; verified → pending on records gone (a new 72 h window); a provider FAILED result (TEM `locked`, `revoked`) → failed from pending or verified; 72 h of pending → failed. Each mails the organization's active admins once (`sending_domain_status`). `failed` rows are only checked by "Check now", and set up again by enabling, which replaces the registration. | Records removed by mistake heal when restored; a failure doesn't heal, so waiting would only delay the admins. |
| 9 | "Check now" at most once per 30 s per domain. | Each call hits DNS or the provider's API. |
| 10 | The From is decided at send time, never stored: `sendable_address(mailbox)` for the reply, unread-reply, conversation-link and resolved mails. Reply-To and threading are unchanged. | A transfer or a regression takes effect on the next mail. |
| 11 | TEM records are shown with fully qualified names, in the order SPF, DKIM, DMARC, never TEM's MX. SPF records (TEM's and `manual`'s) and TEM's DMARC carry `merge: true`: the wizard says to add the value to an existing record rather than publish a second. | TEM's MX is a blackhole for send-only domains, and ours receive the support mail. Two SPF or DMARC records make receivers ignore both. |
| 12 | A public webmail domain is never verified, for any purpose, and a webmail row verified before that rule never counts as ownership: no sending, no public address, no freeing of others' addresses. | Nobody owns `gmail.com`. |
| 13 | The organization payload carries `sending_domains_enabled` (provider not `none`); a mailbox carries `sends_from_public_address`. | The wizard is hidden without a provider; the mailbox card says which From is used now. |
| 14 | Sending needs the organization's own `_showdesk.<domain>` TXT (`showdesk-verification=<token>`), whatever the provider, at every check: it is the first record to publish, refreshed first in the stored records at every check (a row verified by admin email gets a token on enabling, even if already set up, its ownership untouched), and a check without it is pending (a regression on a verified domain), one that can't read it inconclusive. | `manual`'s records are the same for every organization, so the real owner publishing them for itself would verify a squatter's row too; an admin's mailbox proves an address, not control of the DNS; and TEM's re-registration of a revoked name is unconfirmed. |
| 15 | A row remembers the provider it was registered with (`sending_provider`); only one of the configured provider is sendable. Changing `SENDING_DOMAIN_PROVIDER` makes every domain set up under the previous one fall back: the next check resets it (no mail) and its admins set it up again. Until then the domain is shown as not set up. Its registration is recorded for removal by the provider that made it, unless that one has nothing to remove (`manual`), and waits until that provider is configured again (the sweep logs a warning for it every 3 h); it doesn't block setting the domain up again under the configured provider. | The published records were the previous provider's; the new one never checked them. The old registration is held at the old provider, so it can't clash with the new one. |
| 16 | A domain is validated more strictly on create: at least two labels of 1-63 `[a-z0-9-]` with no hyphen at either end, a non-numeric last label, 200 characters at most. | Room for `<selector>._domainkey.<domain>` within DNS's 253 characters, and no IP address taken for a domain. |
| 17 | A public webmail domain is refused on create for every purpose (branding, routing, sending), by DNS or admin email alike. | Nobody owns `gmail.com`, whatever the row is for. |
| 18 | An admin-email verification of a domain the organization already has adds the asked purposes to the row and keeps the others, and leaves its sending state alone. | Verifying again must not drop a purpose, nor stop sending. |
| 19 | A DNS win clears the token of the other organizations' rows of the domain (the previous owner's and any pending one): their admins regenerate a token to claim it again. | The previous owner's TXT, left published, would otherwise win the domain straight back. |

What admins have:

- `POST /api/v1/organization-domains/{id}/sending/`: registers the domain and
  checks it once; 200 with the row, 400 `not_owned` (ownership not verified)
  or `public_domain`, 409 `removal_pending`, `provider_conflict` (the
  provider already holds the name with no removal of ours: logged as an
  error) or `in_progress` (a setup of the domain is running), 502
  `provider_error`.
- `POST …/sending/check/`: 200 with the row, 400 `not_owned` or
  `not_registered`, 429 `too_soon`. `DELETE …/sending/`: stop sending, 200
  with the row (409 `in_progress` while a setup of the domain runs).
- Refusals are `{detail, code}`.
- All three are 404 while `SENDING_DOMAIN_PROVIDER=none`, and 403 for agents.
  A domain can be created with `is_sending` (DNS or admin email) only while a
  provider is configured; the sending state is read-only and the provider's
  ref is never exposed.
- Settings → Email: each mailbox card says "Replies are sent from" its public
  or inbound address, and admins get a "Send from your domain" wizard:
  (1) address and ownership (DNS TXT or the admin's own email), saving the
  address once its domain is verified; (2) the records to publish, the
  domain's own `_showdesk` TXT first ("The first record proves your
  organization controls the domain."), with copy buttons and merge notes; (3) status, last check and error, "Check now",
  "Stop sending from this domain". Settings → General shows the "Sending"
  purpose and status on the domain while a provider is configured.
- `manage.py seed` marks the demo mailbox's domain for sending, unregistered,
  when `INBOUND_EMAIL_DOMAIN` is set.

What operators set (§8):

- `SENDING_DOMAIN_PROVIDER`: `none` (default, feature hidden), `manual` or
  `scaleway_tem`. A misconfigured provider is logged, and admins only see
  that sending from their domain is unavailable; so are a provider's own
  error messages (admins see "The sending service answered 503."). Changing
  it makes every domain set up under the previous one fall back, to be set
  up again (choice 15).
- `manual`: `SENDING_DOMAIN_SPF_INCLUDE` and `SENDING_DOMAIN_DKIM_SELECTOR`,
  with `INBOUND_EMAIL_DOMAIN`. The operator publishes the DKIM key at
  `<selector>._domainkey.<INBOUND_EMAIL_DOMAIN>` and has the sending service
  relay for, and sign with that key, every customer domain.
- `scaleway_tem`: `SCW_TEM_SECRET_KEY` (a key restricted to Transactional
  Email), `SCW_TEM_PROJECT_ID` (the project the domains are registered in),
  `SCW_TEM_REGION` (`fr-par`).
- Celery beat runs `check-sending-domains` every 15 min and
  `requeue-sending-removals` hourly, on the `default` queue.
