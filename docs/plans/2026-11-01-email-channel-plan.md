# Email Channel (PR 2) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task by task, with a review after each batch.

**Goal:** Every email sent to an organization's support address opens or continues a ticket, agent replies reach the requester by a repliable email or in the widget, and a requester can read their whole conversation from a signed link or, after proving their email, in the widget.

**Architecture:** A new `apps.email_channel` app holds mailboxes, the stored inbound emails and a pipeline run by Celery: recipient, filters, threading, content, write. Outbound stays on the existing SMTP through `send_branded_email`, with stored Message-IDs and a tokenised `Reply-To`. Identity goes through `apps.contacts.services`, the only place that writes a contact's email.

**Tech Stack:** Django 6.1, DRF, Celery, Channels, django-anymail (Postal), React 19, the vanilla TS widget.

**Authoritative documents:** `docs/plans/2026-10-29-email-channel-design.md` (§ numbers below refer to it unless stated), `docs/plans/2026-10-29-contacts-design.md` §3 and §8.

**Branch:** `feat/email-channel` from `develop`, PR to `develop`.

---

## Choices this plan makes beyond the design

The code showed these. Each one is pinned by a test in the task named.

| # | Choice | Why | Task |
|---|---|---|---|
| 1 | Mount only the configured provider's webhook. `/anymail/postal/inbound/` needs `ANYMAIL_POSTAL_WEBHOOK_KEY`; the rest of `anymail.urls` is only mounted when `ANYMAIL_WEBHOOK_SECRET` is set. | Without a secret, Anymail's basic-auth check only warns: `include("anymail.urls")` would let anyone post a forged email to `/anymail/sendgrid/inbound/`, bypassing Postal's signature. | 2 |
| 2 | Our own `PostalInboundView`, subclassing Anymail's. | Anymail decodes the raw message as UTF-8, so one 8-bit Latin-1 mail is a 500, and `request.body` refuses anything over `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB), far below `INBOUND_EMAIL_MAX_SIZE_MB`. | 2 |
| 3 | `TicketMessage.external_sender` (display name and address of the mail's `From`). | `sender_name` comes from a widget session. A third party's reply on a thread must show who wrote it. Anonymization clears it. | 1, 9 |
| 4 | The raw `.eml` never gets a URL. Agents open it through an authenticated endpoint. | The default storage builds URLs, and a mail holds personal data. | 3, 16 |
| 5 | Anonymization deletes the contact's `InboundEmail` rows and raw files, those of its tickets and those sent from its address, and clears `external_id` and `external_sender` on its messages. | Otherwise the raw mail keeps everything the anonymization removes. | 9 |
| 6 | The conversation token also carries a hash of the address the mail went to (16 hex characters of an HMAC-SHA256 of the lowercased address, keyed by `SECRET_KEY` with its own salt), never the address in clear. A link opens its conversation, and verifies the contact, only while the contact's current email has that hash. | An agent can change a contact's email, for instance to correct a typo: an old link must neither prove the new one nor keep the old address's holder in the conversation. Keyed, so a list of addresses can't be hashed to find the one a link names. | 6, 11 |
| 7 | The link never makes a ticket's `sender_verified` true: neither opening it nor posting through it. | Both prove who holds the mailbox now, not who wrote the ticket: someone can file a ticket under another's address, and that person's protest on the page would verify the forger's first message. | 11 |
| 8 | `OTPCode.purpose` (`login`, `widget_email`), with separate throttles. | Without it, a widget visitor spends the attempts of someone's login code, cancels it by asking for a new one, and uses up their hourly OTP quota. | 14 |
| 9 | `WidgetSession.email_proof_source` (`signed`, `code`). The logout rule (Contacts §3 rule 8) only applies to `signed`. | A host page that never signs can't sign on resume: a code proof would be lost at the next page load. Contacts §8 announced this. | 14 |
| 10 | Agents' own addresses never become contacts on inbound mail, as on API tickets. | Contacts §5: "an agent, admin or superuser never becomes a Contact". | 8 |
| 11 | Reuniting history on proof (Contacts §8) moves tickets, sessions and notes from the email-only contact to the identified one, fills the blanks, keeps an unsubscription, then deletes the email-only row. | The email has to move for the proof to hold, and an emptied row would hold nothing. Only on a proof, and only from an email-only contact. | 13 |

### Decisions taken (Dimitri, 2026-11-03)

**A. The widget's code banner (§6.2).** The design shows "You have N email conversations", and only when such tickets exist. Since the widget's email is declared by the page, anyone could type an address and learn whether it's a customer and how many conversations they have. **Decided:** the same neutral banner for every unproven email ("Have earlier conversations by email? Get a code"), always a 202, and a mail is only sent when there's something to see.

**B. Unsubscribed contacts.** Contacts §5 says a reply on the contact's own ticket is essential. The email design §5.2 suppresses replies except on tickets opened by email. **Decided:** follow the email design, and correct Contacts §5: an unsubscribed contact gets no email for a widget ticket and finds the reply in the widget.

---

## Working rules

Environment: disposable `postgres:17-alpine` on 25432 and `redis:8-alpine` on 26379, never another project's containers. If the Docker engine stops answering, don't restart it: use a disposable Homebrew `postgresql@16` and Redis on those ports and say so.

```bash
export DJANGO_SETTINGS_MODULE=config.settings.development
export DATABASE_URL=postgres://showdesk:showdesk@localhost:25432/showdesk
export REDIS_URL=redis://localhost:26379/0
export CELERY_BROKER_URL=redis://localhost:26379/1
export CELERY_RESULT_BACKEND=redis://localhost:26379/2
```

Parallel agents each get their own database and Redis indexes.

| Scope | Command, from the repo root |
|---|---|
| Backend | `cd backend && python -m pytest -q` |
| Lint | `ruff check backend/ && ruff format --check backend/` |
| Migrations | `cd backend && python manage.py makemigrations --check --dry-run` |
| Frontend | `cd frontend && npm run lint && npm test && npm run build` (Node 26) |
| Widget | `cd widget && npm test && npm run build` |

- TDD: failing test, watch it fail, minimal code, watch it pass, commit. Every task ends with a Conventional Commit.
- Few distinct test cases, no large parametrized tables.
- English in code, comments and product strings. Nothing about Showdesk Cloud in this repo.
- A mail's `From` is a declaration and opens nothing. Only `user_hash`, `email_hash`, `company_hash`, a code and a signed link are proofs.
- Every new setting goes in `.env.example` with a safe default and in `docker-compose.prod.yml`.
- Reviewers leave no shell running.

---

## Batch 1: Foundations

### Task 1: Models and migrations

**Files:**
- Create: `backend/apps/email_channel/{__init__,apps,models,admin}.py`, `backend/apps/email_channel/migrations/0001_initial.py`
- Modify: `backend/config/settings/base.py` (`INSTALLED_APPS`), `backend/apps/tickets/models.py`
- Create: `backend/apps/tickets/migrations/00XX_email_channel_fields.py`, `00XY_backfill_message_channel.py`
- Modify: `backend/tests/factories.py` (`MailboxFactory`, `InboundEmailFactory`)
- Test: `backend/tests/email_channel/test_models.py`, `backend/tests/tickets/test_models.py`

**Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_mailbox_local_part_is_generated_from_the_slug_and_is_not_guessable():
    org = OrganizationFactory(slug="acme")
    first, second = Mailbox.objects.create(organization=org, name="Support"), Mailbox.objects.create(organization=org, name="Billing")
    assert re.fullmatch(r"acme-[a-z0-9]{10}", first.local_part)
    assert first.local_part != second.local_part

@pytest.mark.django_db
def test_mailbox_default_team_must_belong_to_the_organization():
    mailbox = MailboxFactory.build(organization=OrganizationFactory(), default_team=TeamFactory())
    with pytest.raises(ValidationError):
        mailbox.full_clean(exclude=["organization", "default_team"])

@pytest.mark.django_db
def test_same_message_id_is_unique_per_mailbox_and_without_one():
    mailbox = MailboxFactory()
    InboundEmailFactory(mailbox=mailbox, message_id="<a@x>")
    InboundEmailFactory(mailbox=MailboxFactory(), message_id="<a@x>")
    with pytest.raises(IntegrityError), transaction.atomic():
        InboundEmailFactory(mailbox=mailbox, message_id="<a@x>")
    InboundEmailFactory(mailbox=None, message_id="<a@x>")
    with pytest.raises(IntegrityError), transaction.atomic():
        InboundEmailFactory(mailbox=None, message_id="<a@x>")

@pytest.mark.django_db
def test_backfill_sets_the_channel_from_the_sender_type(migrator): ...
    # user -> widget, agent -> agent, system -> system
```

**Step 2: Run them, expect import errors.** `cd backend && python -m pytest -q tests/email_channel/test_models.py`

**Step 3: Implement**

```python
# backend/apps/email_channel/models.py
def _generate_local_part(slug: str) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return f"{slug[:40]}-{''.join(secrets.choice(alphabet) for _ in range(10))}"


def _raw_path(instance: "InboundEmail", filename: str) -> str:
    return f"inbound-emails/{uuid.uuid4().hex}.eml"


class Mailbox(TimestampedModel):
    """An address of an organization, receiving its forwarded support mail."""

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="mailboxes")
    name = models.CharField(max_length=100)
    local_part = models.CharField(max_length=64, unique=True, editable=False)
    public_address = models.EmailField(blank=True)
    default_team = models.ForeignKey("organizations.Team", on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    forwarding_confirmation = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["public_address"],
                condition=~models.Q(public_address=""),
                name="unique_mailbox_public_address",
            ),
        ]

    def clean(self) -> None: ...  # default_team in the organization; public_address lowercased
    def save(self, *args, **kwargs) -> None: ...  # generates local_part once, lowercases public_address

    @property
    def inbound_address(self) -> str:
        return f"{self.local_part}@{settings.INBOUND_EMAIL_DOMAIN}"

    def regenerate_address(self) -> None: ...


class InboundEmail(TimestampedModel):
    """One received email: a log, what a replay reads, and what makes delivery idempotent."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        IGNORED = "ignored", "Ignored"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    mailbox = models.ForeignKey(Mailbox, on_delete=models.CASCADE, null=True, blank=True, related_name="inbound_emails")
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound_emails")
    message = models.ForeignKey("tickets.TicketMessage", on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound_emails")
    message_id = models.CharField(max_length=255)
    sender = models.EmailField(blank=True, db_index=True)
    recipients = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=998, blank=True)
    raw = models.FileField(upload_to=_raw_path, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    reason = models.CharField(max_length=50, blank=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(fields=["message_id", "mailbox"], name="unique_inbound_per_mailbox"),
            models.UniqueConstraint(fields=["message_id"], condition=models.Q(mailbox__isnull=True), name="unique_inbound_without_mailbox"),
        ]
```

`message_id` is unique-indexed, so it's capped at 255: the handler replaces a longer header by `<{sha256 of it}@hashed.invalid>`, with a test.

```python
# backend/apps/tickets/models.py
# Ticket
mailbox = models.ForeignKey("email_channel.Mailbox", on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")

# TicketMessage
class Channel(models.TextChoices):
    WIDGET = "widget", "Widget"
    EMAIL = "email", "Email"
    AGENT = "agent", "Agent"
    API = "api", "API"
    SYSTEM = "system", "System"

class DeliveryStatus(models.TextChoices):
    NONE = "", "Not emailed"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"

channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.WIDGET)
external_id = models.CharField(max_length=255, blank=True, db_index=True)
external_sender = models.CharField(max_length=320, blank=True)
email_delivery_status = models.CharField(max_length=10, choices=DeliveryStatus.choices, blank=True)
```

`sender_name` returns the display name of `external_sender` for a user message with no session, else the contact's name. Agent replies set `channel=AGENT` in `TicketMessageViewSet.perform_create`. The back-fill runs one `update` per sender type, in `RunPython`, with a no-op reverse.

**Steps 4-5: Run the tests, `makemigrations --check`, commit** `feat(backend): add mailboxes, inbound emails and message channels`

### Task 2: Settings, dependencies and the webhook route

**Files:**
- Modify: `backend/requirements.txt` (`django-anymail[mailjet,postal]`), `backend/config/settings/base.py`, `backend/config/urls.py`, `.env.example`, `docker-compose.prod.yml` (variables and `handle /anymail/*`), `docker/Caddyfile`
- Create: `backend/apps/email_channel/webhooks.py`
- Test: `backend/tests/email_channel/test_webhook_route.py`

**Step 1: Write the failing tests.** An RSA key pair generated in the test signs the body, as Postal does.

```python
def test_a_signed_mail_is_accepted(signed_post, settings): ...          # 200, inbound signal fired
def test_a_forged_signature_is_refused(signed_post): ...                # 400
def test_other_providers_are_not_mounted_without_a_secret(client):      # 404 on /anymail/sendgrid/inbound/
def test_a_latin1_mail_is_accepted(signed_post): ...                    # base64 of 8-bit bytes, 200, subject decoded
def test_a_mail_over_the_default_upload_limit_is_accepted(signed_post): # 5 MB, 200
def test_a_mail_over_the_cap_is_refused_before_reading(signed_post):    # 413
def test_the_route_is_absent_when_the_channel_is_off(client): ...       # 404
```

URLs depend on settings read at import: reload `config.urls` under `override_settings` with `clear_url_caches`, through a fixture.

**Step 2: Watch them fail.**

**Step 3: Implement**

```python
# backend/apps/email_channel/webhooks.py
class PostalInboundView(PostalInboundWebhookView):
    """Anymail's view, for mail that isn't UTF-8 and is over Django's upload limit."""

    def dispatch(self, request, *args, **kwargs):
        limit = int(settings.INBOUND_EMAIL_MAX_SIZE_MB * 1024 * 1024 * 1.4) + 1024 * 1024
        if int(request.META.get("CONTENT_LENGTH") or 0) > limit:
            return HttpResponse(status=413)
        # ``request.body`` enforces DATA_UPLOAD_MAX_MEMORY_SIZE, unless already read.
        request._body = request.read(limit + 1)
        if len(request._body) > limit:
            return HttpResponse(status=413)
        return super().dispatch(request, *args, **kwargs)

    def parse_events(self, request):
        esp_event = json.loads(request.body)
        if "status" in esp_event:
            raise AnymailConfigurationError("This is Postal's *tracking* webhook, not its inbound one.")
        raw = esp_event["message"]
        raw = b64decode(raw) if esp_event.get("base64") is True else raw.encode("utf-8", "surrogateescape")
        message = AnymailInboundMessage.parse_raw_mime_bytes(raw)
        message.envelope_sender = esp_event.get("mail_from")
        message.envelope_recipient = esp_event.get("rcpt_to")
        return [AnymailInboundEvent(event_type=EventType.INBOUND, event_id=esp_event.get("id"), esp_event=esp_event, message=message)]
```

```python
# backend/config/urls.py
if settings.INBOUND_EMAIL_DOMAIN:
    # Without a shared secret, Anymail's views for basic-auth providers accept anything.
    if settings.ANYMAIL.get("POSTAL_WEBHOOK_KEY"):
        urlpatterns.append(path("anymail/postal/inbound/", PostalInboundView.as_view()))
    if settings.ANYMAIL.get("WEBHOOK_SECRET"):
        urlpatterns.append(path("anymail/", include("anymail.urls")))
```

Settings and their defaults are in §8, plus `ANYMAIL_WEBHOOK_SECRET` (empty), which `.env.example` documents as "for providers other than Postal". `SITE_URL`-based links need nothing new.

**Steps 4-5: Run, commit** `feat(backend): receive signed inbound mail webhooks`

### Task 3: Store what arrives, `ingest_eml`

**Files:**
- Create: `backend/apps/email_channel/{recipients,inbound}.py`, `backend/apps/email_channel/signals.py`, `backend/apps/email_channel/tasks.py` (empty pipeline for now), `backend/apps/email_channel/management/commands/ingest_eml.py`
- Create: `backend/tests/email_channel/fixtures/*.eml` (hand-written, addresses on `example.com`/`example.org`)
- Test: `backend/tests/email_channel/test_store.py`, `test_recipients.py`

**Step 1: Write the failing tests**

```python
# test_recipients.py
def test_reply_token_wins_and_gives_the_tickets_mailbox(): ...
def test_forwarded_mail_is_found_by_delivered_to_while_to_stays_public(): ...
def test_public_address_matches_in_to(): ...
def test_an_inactive_mailbox_is_not_a_recipient(): ...
def test_a_forged_token_is_not_a_recipient(): ...

# test_store.py
def test_storing_twice_keeps_one_row_and_runs_once(django_capture_on_commit_callbacks): ...
def test_no_message_id_gets_a_stable_one_from_the_content(): ...
def test_unknown_recipient_is_stored_rejected_with_no_task(): ...
def test_ingest_eml_feeds_the_same_pipeline(tmp_path): ...
def test_the_raw_mail_has_no_url_in_any_serializer(): ...  # added with Task 16
```

**Step 3: Implement**

`recipients.resolve(message) -> Recipient(mailbox, ticket, address)` follows §4.1. With an envelope recipient, it alone is resolved: a `reply+{token}`, or `local_part@INBOUND_EMAIL_DOMAIN` or `public_address` (lowercased) of an active mailbox; anything else is `rejected/unknown_recipient`. Without one (`ingest_eml` without `--recipient`), the headers are searched: `reply+{token}` on any of them first, then `Delivered-To`, `X-Original-To`, `X-Forwarded-To`, `To`, `Cc` in that order. A mailbox or ticket of an inactive organization is `rejected/inactive_organization`. The `InboundEmail` foreign key to the message is `ticket_message` (`message` would clash with the `message_id` column).

`inbound.store(message) -> InboundEmail | None` is the only entry point, used by the signal and `ingest_eml`. In one transaction: resolve the recipient, normalize the Message-ID, `get_or_create` on `(message_id, mailbox)`, save the raw bytes only if created, `transaction.on_commit(process_inbound_email.delay)` unless rejected. It returns None for a duplicate. Any exception reaches the view, so the provider retries.

`ingest_eml <file|->` reads bytes (`parse_raw_mime_bytes`), calls `store`, prints the row's id and status once processed in eager mode, or "queued" otherwise. It accepts `--recipient` for the envelope recipient.

**Steps 4-5: Run, commit** `feat(backend): store inbound mail and add ingest_eml`

---

## Batch 2: The pipeline

### Task 4: Filters

**Files:** Create `backend/apps/email_channel/filters.py`, test `backend/tests/email_channel/test_filters.py`.

`classify(message, mailbox, *, raw) -> Verdict(status, reason) | None`, in the order of §4.2. Tests, one per reason, from fixtures: `gmail_forwarding_confirmation` (sets `Mailbox.forwarding_confirmation`, emails admins through a `forwarding_confirmation` template), `auto_reply` (`Auto-Submitted: auto-replied`, not for `no`), `bulk` (`Precedence`, `List-Id`), `bounce` (`multipart/report`, marks `email_delivery_status=failed` on the message with the referenced Message-ID, and only in that mailbox's organization), `loop` (sender on `INBOUND_EMAIL_DOMAIN`), `spam` (`message.spam_detected`), `rate_limited` (over `INBOUND_EMAIL_RATE_LIMIT_PER_HOUR` for sender and mailbox, counted on `InboundEmail` rows of the last hour).

The confirmation is only recognized when `From` is `forwarding-noreply@google.com` **and** the mail was delivered to the mailbox's own inbound address. Since `From` can be forged, it never does more than show a link and code to that organization's admins, and the settings screen shows it as untrusted text, never as a clickable link outside `https://mail.google.com`/`https://mail-settings.google.com`.

Commit: `feat(backend): filter automatic and unwanted inbound mail`

### Task 5: Content extraction

**Files:** Create `backend/apps/email_channel/content.py`, test `test_content.py` with fixtures for Gmail, Outlook, Apple Mail, Thunderbird in EN and FR, and HTML-only.

```python
def extract_body(message) -> str: ...  # text part, else sanitized HTML as text
def strip_history(text: str) -> str: ...  # our marker, attribution lines, Outlook blocks, trailing > lines: linear, no library
def extract_attachments(message, max_bytes: int) -> tuple[list[Attachment], list[str]]: ...
```

Move `BLOCKED_EXTENSIONS` out of `TicketAttachmentSerializer` to a module constant both use, and don't change its content. Dropped parts are named in a note appended to the message. Tests: a mail with a blocked `.exe` (dropped, noted), one over the cap (dropped, noted), a mail that is only quoted history (body stays non-empty: fall back to the full text), a filename with path separators (basename only). HTML goes to text with an escaping parser: no HTML reaches a message.

Commit: `feat(backend): extract text and attachments from inbound mail`

### Task 6: Tokens

**Files:** Create `backend/apps/email_channel/tokens.py`, test `test_tokens.py`.

```python
_REPLY_SALT = "showdesk.email_channel.reply"
_CONVERSATION_SALT = "showdesk.email_channel.conversation"


def _reply_signature(ticket_hex: str) -> str:
    return salted_hmac(_REPLY_SALT, ticket_hex, algorithm="sha256").hexdigest()[:16]


def reply_address(ticket) -> str:
    return f"reply+{ticket.id.hex}.{_reply_signature(ticket.id.hex)}@{settings.INBOUND_EMAIL_DOMAIN}"


def ticket_id_from_reply_address(address: str) -> uuid.UUID | None:
    """Return the ticket an address names, or None if it isn't one of ours."""
    local, _, domain = address.strip().lower().partition("@")
    if domain != settings.INBOUND_EMAIL_DOMAIN.lower() or not local.startswith("reply+"):
        return None
    ticket_hex, _, signature = local.removeprefix("reply+").partition(".")
    if not constant_time_compare(signature, _reply_signature(ticket_hex)):
        return None
    try:
        return uuid.UUID(hex=ticket_hex)
    except ValueError:
        return None


@dataclass(frozen=True)
class ConversationClaim:
    ticket_id: str
    contact_id: str
    email_hash: str  # email_hash(address): a link is forwarded and logged

    def holds(self, email: str) -> bool: ...  # constant-time compare of hashes


def conversation_token(ticket, contact, email: str) -> str:
    return signing.dumps({"t": str(ticket.id), "c": str(contact.id), "h": email_hash(email)}, salt=_CONVERSATION_SALT, compress=True)


def read_conversation_token(token: str, *, allow_expired: bool = False) -> ConversationClaim | None:
    """Return what a token claims, or None. ``allow_expired`` is for asking for a new link."""
    max_age = None if allow_expired else timedelta(days=settings.CONVERSATION_LINK_MAX_AGE_DAYS)
    try:
        data = signing.loads(token, salt=_CONVERSATION_SALT, max_age=max_age)
    except signing.BadSignature:  # SignatureExpired is a subclass.
        return None
    return ConversationClaim(data["t"], data["c"], data["h"])


def outbound_message_id(message) -> str:
    return f"<{message.id}@{settings.INBOUND_EMAIL_DOMAIN}>"
```

Tests: round trips, a tampered signature, a reply token with another ticket's id, uppercased address (mail servers change case), an expired token refused and readable with `allow_expired`, a reply token refused as a conversation token.

Commit: `feat(backend): sign reply addresses and conversation links`

### Task 7: Threading

**Files:** Create `backend/apps/email_channel/thread_matching.py`, test `test_thread_matching.py`.

`find_ticket(message, recipient, sender, organization) -> Match(ticket, by) | None`, following §4.3, then `apply_reopen_rule`.

Tests, each a separate attack or path:
- `In-Reply-To` on a stored `external_id` of the organization;
- the same header on another organization's message: no match, a new ticket;
- the reply token, with no headers;
- `[SD-12]` from the ticket's contact: match; from anyone else: new ticket;
- `Fwd:`, `Tr:`, `WG:` without matching headers, with `[SD-12]` from the contact: new ticket;
- closed within `INBOUND_EMAIL_REOPEN_DAYS`: reopens, clearing `resolved_at` and `closed_at`, as `bulk_update` does;
- closed for longer: new ticket with `context_metadata["previous_ticket"]`, and that key on the whitelist of `gdpr._kept_metadata` (a UUID string, under its rule);
- on an anonymized contact's ticket: never a match, a new ticket.

Commit: `feat(backend): thread inbound mail onto tickets`

### Task 8: Write, and the task

**Files:** Modify `backend/apps/email_channel/tasks.py`, `inbound.py`; test `test_pipeline.py`.

```python
@shared_task(bind=True, max_retries=5, default_retry_delay=60, retry_backoff=True)
def process_inbound_email(self, inbound_id: str) -> None:
    """Run one stored mail through the pipeline. Safe to run again."""
```

Under `select_for_update` on the row in `pending`/`failed`, parse the raw file, then filters, threading, content, write, in one transaction with the row's final status. Celery and websocket calls run on commit. An exception marks `failed` with the reason `exception` in its own transaction, then retries.

Write, §4.5:
- The sender: `From`'s address, cleaned by the service. If it's an address of a staff member of the organization, no contact (reuse the check of `resolve_contact_for_ticket`, extracted as `is_staff_address`). Otherwise `resolve_contact_for_email(org, email, name=name)`.
- New ticket: `source=EMAIL`, `title` cut to 500, "(no subject)" otherwise, `mailbox`, `assigned_team=mailbox.default_team`, `contact`, `requester_email`, `requester_name`, `reference=org.next_ticket_reference()`, `description=body`.
- `TicketMessage(channel=EMAIL, sender_type=USER, external_id=message_id, external_sender=...)` and its `TicketAttachment`s with `uploaded_by=None`.
- On commit: `notify_new_ticket`, `notify_new_message`, `send_ticket_created_email` for a new ticket, `send_ticket_reply_email` otherwise (its agent branch already handles a message with no author).

Tests: end to end through the signed view with each fixture; a replay gives no second message; an email to a closed ticket; a mail from a staff address has no contact; an anonymized address has no contact; a mail from a third party on a thread keeps the ticket's contact and shows its own sender; a failure then a retry; a ticket from `From: someone` is `sender_verified=False`.

Commit: `feat(backend): turn inbound mail into tickets and messages`

### Task 9: Anonymization, export and retention

**Files:** Modify `backend/apps/contacts/gdpr.py`, `backend/apps/email_channel/tasks.py`, `backend/config/settings/base.py` (beat), `docs/plans/2026-10-29-contacts-design.md` §5 and §8; test `backend/tests/contacts/test_gdpr_email.py`, `backend/tests/email_channel/test_retention.py`.

- `anonymize_contact` deletes `InboundEmail` rows on the scrubbed tickets, or whose `sender` is the contact's address in a mailbox of its organization, with their files after commit (`_delete_files_after_commit`). It clears `external_id` and `external_sender` on the scrubbed messages (an external id can name the sender's domain).
- `_exported_ticket` includes `channel`. The export holds neither raw mails nor `external_id`.
- `purge_inbound_raw` (daily, beat) empties `raw` past `INBOUND_EMAIL_RAW_RETENTION_DAYS`, keeps the row, and doesn't touch `pending` or `failed`.

Tests: the row and file are gone, including an ignored mail from that address; a mail from the same address in another organization stays; a raw mail before and after the retention; a second anonymization changes nothing.

Commit: `feat(backend): cover inbound mail in anonymization and retention`

---

## Batch 3: Outbound

### Task 10: Repliable reply email, presence, when to send

**Files:** Modify `backend/apps/core/email.py` (`headers` parameter), `backend/apps/tickets/tasks.py`, `backend/templates/emails/ticket_reply.{html,txt}`, `backend/apps/notifications/consumers.py`, `backend/apps/tickets/views.py` (`perform_create`), `widget/src/api/websocket.ts` (25 s ping); create `backend/apps/email_channel/{outbound,presence}.py`; test `backend/tests/email_channel/test_outbound.py`, `test_presence.py`.

```python
# presence.py
PRESENCE_TTL_SECONDS = 60

def mark_connected(session_id: str) -> None: cache.set(f"widget_presence:{session_id}", 1, PRESENCE_TTL_SECONDS)
def mark_disconnected(session_id: str) -> None: cache.delete(f"widget_presence:{session_id}")
def is_connected(session_id) -> bool: return session_id is not None and cache.get(f"widget_presence:{session_id}") is not None
```

Consumers call them through `sync_to_async`, on connect, on ping and on disconnect. With two tabs, closing one drops the key until the other's next ping, at most 25 s: an email may go out early in that window. Accepted, and noted in the design.

```python
# outbound.py
def delivery_decision(message) -> Decision:  # NOW, LATER or NEVER, §5.2
    ticket = message.ticket
    if suppressed_by_unsubscribe(ticket): return NEVER          # unsubscribed, and not a ticket they opened by email
    last = ticket.messages.filter(sender_type=USER).order_by("-created_at").first()
    if last is not None and last.channel == EMAIL: return NOW
    if not any(is_connected(s) for s in entitled_session_ids(ticket)): return NOW
    return LATER
```

The requester branch of `send_ticket_reply_email` (`channel=AGENT` or `author` staff):

- `From`: `outbound.from_address(ticket)`, §5.1: the ticket's mailbox, else the organization's first active one, else `DEFAULT_FROM_EMAIL`.
- `Reply-To`: `reply_address(ticket)` when `INBOUND_EMAIL_DOMAIN` is set; none otherwise, as today.
- Headers: `Message-ID` = `outbound_message_id(message)`, `In-Reply-To`, `References` from the ticket's stored chain, kept under 20 ids. The id is derived from the message, so a retry keeps it. Saves `external_id` before sending and `email_delivery_status=sent` after. Failure past retries: `failed`.
- Context: the marker `-- Reply above this line --`, the unread replies, the last three public messages, `conversation_url`. A conversation link is built only if the ticket has a contact; the token carries the hash of the address the mail goes to.
- With `INBOUND_EMAIL_DOMAIN` empty, everything behaves as today apart from the delay. Pinned by a test.

Scheduled send: `send_unread_reply_email.apply_async(args=[message_id], countdown=delay_minutes * 60)`. It runs only if `widget_last_read_at` doesn't cover the message and no later agent reply exists (that one's task sends the group), and groups every unread reply.

`send_ticket_resolved_email` also respects `is_unsubscribed`, and the `Reply-To`.

Tests: a mail captured in `mail.outbox` has each header; threading headers chain; a retry keeps the Message-ID; connected then read: no mail; connected then unread: one mail with both replies; offline: now; email-born ticket with a connected session: now; unsubscribed on a widget ticket: never; unsubscribed on an email ticket: sent; an internal note: never; a pre-login moved ticket keeps today's rule.

Commit: `feat(backend): send repliable replies, in the widget first when connected`

---

## Batch 4: Conversation page

### Task 11: Conversation API

**Files:** Create `backend/apps/email_channel/{conversation_views,serializers}.py`; modify `backend/config/api_urls.py`, `backend/apps/tickets/messages.py` (`create_user_message`, extracted), `backend/apps/core/throttling.py`; test `backend/tests/email_channel/test_conversation_api.py`.

`_resolve(token)`: reads the claim, loads the ticket with its organization and contact, and returns None unless `ticket.contact_id == claim.contact_id`, `claim.holds(contact.email)`, the contact isn't anonymized and no login moved the ticket. Every failure is the same 404. Any expired signature of ours is a 410, whatever the ticket's state, carrying only `{"renewable": bool}`: true up to 180 days, after which the page says to contact support.

| Route | Behaviour |
|---|---|
| `GET /api/v1/conversations/{token}/` | Branding (`name`, `logo`, colour), status, reference, `can_reply`, public messages through a serializer that blanks `sender_name` on the requester's side (the session or a mail's sender may be someone else). Marks the contact verified, under its row lock, with `mark_email_proven(contact_id, claim.holds)`, unless it already is. Sets `widget_last_read_at`, without `updated_at`: the delayed reply mail stands down. |
| `POST …/messages/` | `create_user_message` extracted to `tickets/messages.py`, `channel=WIDGET`, on the ticket's session only if that session is the contact's. It locks the contact, then the ticket, as `anonymize_contact` does, and refuses an anonymized contact (the widget too). Notifies agents and sessions. A resolved or closed ticket follows §4.3's reopen rule; past the window, 409 and `can_reply=false`, the page saying to write by email for a new request. Proves nothing about the ticket's sender. |
| `POST …/attachments/` | `TicketAttachmentSerializer` with the same limits. |
| `POST /api/v1/conversations/renew/` | Body `{token}`, read up to 180 days old. Always 202. Mails a fresh link to `ticket.contact.email` and nothing else, at most once per ticket per hour and three times per contact per day, by cache keys. |

Throttled per IP, with new scopes in `DEFAULT_THROTTLE_RATES`. `AllowAny`, no authentication classes.

`Ticket.sender_verified` is unchanged: the link proves who holds the mailbox now, not who wrote the ticket (choice 7).

Security tests: a tampered token; a token from another salt; a ticket moved to another contact (404); anonymized contact (404); a pre-login moved ticket (404); `email` changed on the contact (404, nothing verified); an expired link (410 and nothing else) and one too old to renew; internal notes absent; no requester-side name or email in the payload; renewal with a body naming another address changes nothing; renewal on a ticket with no contact email sends nothing; the hourly and daily renewal caps; a verified contact keeps its first date; neither opening nor posting makes `sender_verified` true; an agent's email stays out of the payload for agents with a name, as the widget does today; no message lands on an anonymized contact's ticket, from the page or the widget.

Commit: `feat(backend): add the signed conversation API`

### Task 12: Frontend conversation page

**Files:** Create `frontend/src/pages/ConversationPage.tsx`, `frontend/src/api/conversation.ts`, `frontend/src/hooks/useConversation.ts`; modify `frontend/src/App.tsx` (public route `/c/:token`, outside `AuthGuard`); test `frontend/src/pages/__tests__/ConversationPage.test.tsx`.

An unauthenticated fetch, since `apiClient` attaches a JWT and redirects on a 401: a separate `fetch` wrapper, and a test that no `Authorization` header goes out when an agent is logged in on the same browser. Organization logo and colour, thread, reply box, attachments, polling every 15 s only while `document.visibilityState === "visible"`, `<meta name="robots" content="noindex">`. 410 shows "This link has expired" and "Send me a new link"; 404 shows a generic not-found. Message bodies render as text.

Tests: thread rendered; polling stops when hidden; sending; expired, then renewal; the agent's token never sent. Commit: `feat(frontend): add the public conversation page`

---

## Batch 5: Proof and shared history

### Task 13: Reuniting history on proof (Contacts §8)

**Files:** Modify `backend/apps/contacts/services.py`, `docs/plans/2026-10-29-contacts-design.md` §3 and §8; test `backend/tests/contacts/test_reunion.py`.

In `_record_identified_email`, in place of the `_email_taken` branch:

```python
elif not contact.email:
    other = _locked(Contact, organization=org, email=email)
    if other is None:
        _set(contact, changed, email=email, email_verified_at=None)
    elif not other.external_id and not other.is_anonymized:
        _absorb_email_only_contact(contact, other, changed)
```

```python
def _absorb_email_only_contact(contact: Contact, other: Contact, changed: set[str]) -> None:
    """Give a contact that proved an email what an email-only contact holds under it.

    Only on a proof, and only from a contact with no identity of its own. Everything
    moved was written under a merely declared address, so no sender becomes verified:
    those tickets' sessions still aren't this contact's.
    """
    Ticket.objects.filter(contact=other).update(contact=contact)
    WidgetSession.objects.filter(contact=other).update(contact=contact)
    ContactNote.objects.filter(contact=other).update(contact=contact)
    for field in ("name", "phone", "avatar_url", "job_title", "locale", "timezone"):
        if getattr(other, field) and not getattr(contact, field):
            _set(contact, changed, **{field: getattr(other, field)})
    if other.company_id and not contact.company_id:
        _set(contact, changed, company=other.company)
    _set(contact, changed, attributes={**other.attributes, **contact.attributes})
    if other.is_unsubscribed:
        _set(contact, changed, is_unsubscribed=True)
    email = other.email
    other.delete()  # Frees the email in this transaction, before ours takes it.
    _set(contact, changed, email=email, email_verified_at=None)
```

Tickets and sessions lock order: contact, then rows, as the module's docstring states. `_save_changes` follows. The module docstring's "Two contacts are never merged" changes to say this one case.

Tests: tickets, sessions and notes move, the email moves and is marked verified; `sender_verified` stays false on moved tickets; an unsubscription survives; an unproven email moves nothing; a proven email held by an identified contact moves nothing and verifies nothing; an anonymized holder moves nothing; a contact holding another email moves nothing; a session linked to the moved contact opens no history unless it has its own proof; two concurrent proofs (a second connection, as in the anonymization test) leave one contact.

Commit: `feat(backend): reunite an email-only contact's history on proof`

### Task 14: Email code in the widget, shared history

**Files:** Modify `backend/apps/organizations/models.py` (`OTPCode.purpose`, migration), `backend/apps/tickets/models.py` (`WidgetSession.email_proof_source`, migration), `backend/apps/tickets/views.py`, `backend/apps/core/throttling.py`, `backend/apps/notifications/signals.py`, `backend/apps/tickets/session_merge.py` if it copies proof fields; create `backend/apps/tickets/access.py`; add `backend/templates/emails/widget_email_code.{html,txt}`; test `backend/tests/tickets/test_widget_email_proof.py`, `test_widget_shared_history.py`.

```python
# backend/apps/tickets/access.py
def contact_history_opens(session) -> bool:
    """Tell if this session may see every ticket of its contact.

    A signed external id on that contact, or a proof of the address the contact holds.
    A proof stored elsewhere opens nothing here (§6.2).
    """
    contact = session.contact
    if contact is None or contact.is_anonymized:
        return False
    if session.external_user_id:
        return contact.external_id == session.external_user_id
    email = session.email.strip().lower()
    return bool(session.email_verified_at and email and email == contact.email)


def session_tickets(session) -> QuerySet[Ticket]:
    query = Q(widget_session=session)
    if session.external_user_id:
        query |= Q(external_user_id=session.external_user_id)
    if contact_history_opens(session):
        query |= Q(contact_id=session.contact_id)
    return Ticket.objects.filter(query, organization_id=session.organization_id)
```

`widget_conversation`, `widget_message`, `widget_message_attachment`, `widget_mark_read` and `widget_history` go through `session_tickets`. `widget_message_delete` stays on the session's own messages.

New routes (`WidgetCodeThrottle` per IP and per session email, their own scopes):

- `POST tickets/widget_email_code/`: always 202. `OTPCode.generate(email, purpose="widget_email")` and a mail only if the session has an unproven valid email and the contact holding it has tickets outside this session (Decision A).
- `POST tickets/widget_email_verify/` `{code}`: `OTPCode.redeem(email, code, purpose="widget_email")`. On success `email_proof_source=CODE` and `resolve_contact_for_widget_session(session, email_verified=True)`, which also runs Task 13. Answers `{"verified": bool}`, true only if the contact ended up holding the address. A wrong code is the same 400 whatever the cause.

`WidgetSessionSerializer` gains `email_proof_offered`: a non-empty email without a proof, whatever exists behind it.

`_create_or_resume_session`: `lost_proof` only when `stored.email_proof_source != CODE`. `_record_session_resume` and `_update_session` clear `email_proof_source` when they clear `email_verified_at`. Signed proof sets `SIGNED` in `_link_session_contact`.

`notify_new_message` also sends `widget_message` to each session where `contact_history_opens`, on the ticket's contact. `delivery_decision` (Task 10) uses those same sessions.

Security tests, each distinct: an unverified session asks for a contact's ticket by id (404) on each of the four routes; a session verified on another contact's address; a proof in another session opens nothing here; a changed email drops the access; an identified session whose contact holds a merely agent-set email (documented in §6.2, allowed); a login code doesn't verify in the widget, a widget code doesn't log in; asking for a code doesn't cancel a pending login code; the code route answers the same with and without tickets behind the address, and with an unknown address; more than the limit per email; another organization's ticket; code proof survives a resume with no hash; signed proof doesn't (rule 8 unchanged).

Commit: `feat(backend): let a proven widget session see its email conversations`

### Task 15: Widget banner

**Files:** Modify `widget/src/api/chat-api.ts`, `widget/src/types.ts`, `widget/src/state/widget-state.ts`, `widget/src/ui/history/history-view.ts`; test `widget/src/__tests__/email-proof.test.ts`.

A banner above the history when `email_proof_offered`: "Have earlier conversations by email?", "Get a code", six-digit input, resend after 60 s. Success refreshes the history. A wrong code shows one neutral message. An email-born ticket opens and receives replies in the chat view as any other. Styles in `styles.ts`, text set through `textContent`.

Commit: `feat(widget): prove an email by code to see its conversations`

---

## Batch 6: Agents and operators

### Task 16: Mailbox API, inbound log, original mail

**Files:** Create `backend/apps/email_channel/{views,serializers}.py`, modify `backend/config/api_urls.py`, `backend/apps/tickets/serializers.py` (`channel`, `external_sender`, `mailbox`, `email_delivery_status` read-only), `backend/apps/organizations/serializers.py` or the setup response (`inbound_email_enabled`); test `test_mailbox_api.py`.

- `/api/v1/mailboxes/`: agents read, admins write (`IsOrgAdminOrReadOnly`, `HasStrictActiveOrg`, org-scoped). `POST …/{id}/regenerate-address/`. `local_part` read-only, `default_team` validated in the organization, `public_address` unique with a clear 400. The serializer runs the model's `full_clean()`: the check that `public_address` is off `INBOUND_EMAIL_DOMAIN` is in `Mailbox.clean()` only.
- `GET /api/v1/mailboxes/{id}/inbound/`: paginated log filtered to `ignored`, `rejected`, `failed`. Rejected mails have no mailbox, so they stay in the admin only.
- `POST /api/v1/inbound-emails/{id}/replay/` for admins, on a `failed` row.
- `GET /api/v1/tickets/{id}/messages/{mid}/original/`: agents of the organization; streams the raw file as `message/rfc822` with `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`.

Tests: cross-organization denial on each route, agent versus admin, no URL to the raw mail in any payload, replay runs once. Commit: `feat(backend): add the mailbox API and inbound log`

### Task 17: Frontend settings and ticket view

**Files:** Create `frontend/src/components/settings/MailboxesTab.tsx`, `frontend/src/hooks/useMailboxes.ts`; modify `frontend/src/pages/SettingsPage.tsx`, `frontend/src/components/tickets/TicketDetail.tsx`, `frontend/src/types/index.ts`; tests alongside.

- Settings tab "Email", hidden when the channel is off: mailboxes, inbound address with a copy button, public address, default team, active toggle, regenerate with a confirmation, Google Workspace and Microsoft 365 forwarding steps (§7.4, including external forwarding on 365), detected Gmail confirmation code, log of ignored mails.
- Ticket: a channel badge per message, external sender when present, "View original", a "not delivered" hint on `email_delivery_status=failed`.

Commit: `feat(frontend): manage mailboxes and show the email channel on tickets`

### Task 18: Admin, seed and documents

**Files:** `backend/apps/email_channel/admin.py` (replay action, no raw URL), `backend/apps/core/management/commands/seed.py` (a mailbox, only with `INBOUND_EMAIL_DOMAIN` set), `README.md`, `ROADMAP.md`, `docs/plans/2026-10-29-email-channel-design.md` (the choices above, §5.2 presence note, Decision A in §6.2), `docs/plans/2026-10-29-contacts-design.md` (Decision B). Commit: `docs: record the email channel as built`

---

## Batch 7: Validation

### Task 19: Runbook in `business/` (private repo, not this one)

`business/docs/plans/2026-11-01-postal-inbound-runbook.md`, committed in that repo: MX of the inbound domain, a Postal server and route in "HTTP endpoint", encoding "raw message" sent base64, to `https://<host>/anymail/postal/inbound/`, the server's public DKIM key as `ANYMAIL_POSTAL_WEBHOOK_KEY` without its header lines, SPF and DKIM of the inbound domain with the sending service (mail goes out `From` that domain), the check that the sending service keeps our `Message-ID`, the variables for each environment, how to test with a signed curl, and rollback (empty `INBOUND_EMAIL_DOMAIN`). Dimitri installs Postal. No secret values in it.

### Task 20: Whole-system check before the PR

1. Backend, lint, migrations, frontend and widget commands of the table above.
2. Real browser, against a local gunicorn/uvicorn server as in production, a real Celery worker started with `-Q default,video_processing`, and Mailpit:
   - `ingest_eml` a Gmail reply → ticket, realtime in the agent's dashboard, attachment;
   - agent reply → Mailpit: From, Reply-To, Message-ID, In-Reply-To;
   - a reply crafted from that captured mail, through `ingest_eml` → same ticket;
   - the mail's link → page, reply, agent sees it; the expired link and its renewal;
   - widget connected → no mail, unread → one mail after the delay (delay set to 1 minute);
   - widget from another origin: declared email, banner, code from Mailpit, history appears, reply from the widget on an email-born ticket; then an identified session with `email_hash` on an address held by an email-only contact.
3. A final review of the whole branch for correctness and security, from a fresh agent. Its findings are read and settled before opening the PR.
4. Open the PR to `develop`, listing in its body: the migrations, the variables to set (`INBOUND_EMAIL_DOMAIN`, `ANYMAIL_POSTAL_WEBHOOK_KEY`), what stays off without them, `/anymail/*` in Caddy, and the check-list for the development environment.

---

## Variables Dimitri will have to set

| Variable | Value | When |
|---|---|---|
| `INBOUND_EMAIL_DOMAIN` | the inbound domain | to turn the channel on, dev first |
| `ANYMAIL_POSTAL_WEBHOOK_KEY` | Postal's public key | once Postal is installed |

All the others have safe defaults. With `INBOUND_EMAIL_DOMAIN` empty, nothing changes for a self-hoster except the unread-reply delay, and the widget's proof banner stays available.
