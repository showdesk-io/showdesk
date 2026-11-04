# Sending Domains (PR 3) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task by task, with a review after each batch.

**Goal:** An organization's reply mails go out `From: support@acme.com` once it has proven it owns `acme.com` and the domain is set up for sending; until then, and whenever that stops being true, they go out from the mailbox's inbound address as today.

**Architecture:** `OrganizationDomain` (organizations app) gains the sending state. A `SendingDomainProvider` adapter (`none`, `manual`, `scaleway_tem`) lives in `apps.email_channel.sending`, with the services that register, check and remove a domain, the policy `sendable_address()` used by `outbound.from_address`, and the Celery tasks. Ownership stays the existing proof (DNS TXT or admin email); a public address now needs it too. The Settings → Email tab gets a three-step wizard per mailbox.

**Tech Stack:** Django 6.1, DRF, Celery beat, dnspython, `requests` (TEM HTTP API), React 19 + TanStack Query, Vitest.

**Authoritative documents:** `docs/plans/2026-10-29-email-channel-design.md` (§ numbers below refer to it), §7 above all, §5.1, §8, §10 and Known limitations.

**Branch:** `feat/sending-domains` from `develop`, PR to `develop`.

---

## What the code says today

- `OrganizationDomain` (`apps/organizations/models.py`): `domain`, purposes `is_branding` / `is_email_routing` (a CHECK constraint wants at least one), `status` pending|verified|failed, at most one `verified` row per domain globally. Verified stays verified until another organization wins the DNS challenge (`services.apply_dns_verification_success`, which flips the loser to `failed` and mails its admins). `try_admin_email_autoverify` refuses a domain verified elsewhere. The pending poller (`recheck_dns_pending_domains`, every 15 min) promotes rows.
- `/api/v1/organization-domains/` (`OrganizationDomainViewSet`): admin writes, `verify`, `regenerate-token`, destroy. The frontend's `DomainsList.tsx` (Settings → General) drives it.
- `Mailbox.public_address`: free text, unique across organizations (partial unique index), used for display, for header recipient matching (`recipients.py`) and loop detection (`filters._is_loop`). Nothing ties it to a domain the organization owns: the "public_address squatting" Known limitation.
- `outbound.from_address(ticket)`: `"{name}" <{local_part}@{INBOUND_EMAIL_DOMAIN}>` from the ticket's mailbox or the organization's first active one. Used by the reply mail, the unread-reply mail (`apps/tickets/tasks.py`) and the conversation link mail (`apps/email_channel/tasks.py`).
- Scaleway TEM API (from Scaleway's generated Python SDK, `scaleway/tem/v1alpha1`): `POST /transactional-email/v1alpha1/regions/{region}/domains` `{project_id, domain_name, autoconfig}`; `GET …/domains/{id}` → `{id, name, status, last_error, records: {spf, dkim, mx, dmarc: {name, value}}}`; `POST …/domains/{id}/check`; `POST …/domains/{id}/revoke`. Statuses: `unknown`, `checked`, `unchecked`, `invalid`, `locked`, `revoked`, `pending`, `autoconfiguring`. Auth header `X-Auth-Token`.

---

## Choices this plan makes beyond the design

Each one is pinned by a test in the task named.

| # | Choice | Why | Task |
|---|---|---|---|
| 1 | `is_sending` is a third purpose of a domain row (the CHECK constraint becomes "at least one of three"). `sending_status` says where the provider stands: `""` (not registered), `pending`, `verified`, `failed`. Turning sending off deregisters and resets `sending_status` to `""`, keeping the purpose. | A domain proven only to send from it needs a row; the purpose is the admin's intent, the status is the provider's state. | 1 |
| 2 | One more field, `sending_requested_at`: when the current pending cycle started. | §7.3's 72 h window needs a start that neither `created_at` nor the ownership dates give. | 1 |
| 3 | A public address may only be set (or changed) to an address on a domain the organization has **verified**. An unchanged legacy value is left alone. | The squatting limitation: reserving `support@bigcorp.com` now needs `bigcorp.com`'s proof. It rules out public webmail addresses (`support.acme@gmail.com`), which could never be sent from anyway; the inbound address keeps working for them. | 5 |
| 4 | When an organization's ownership of a domain is verified (DNS or admin email), other organizations' mailboxes lose a public address on that domain, and a previous owner's sending registration is removed. | A legacy squatter or a previous owner must not keep the address, and §7.1 removes the registration on transfer. | 5 |
| 5 | A registration a row lets go of (turned off, replaced, lost with the domain, deleted with the row or its organization, made but never stored, or found on the row when storing a new one) becomes a `SendingRemoval(domain, ref, provider, created_at, attempts, last_attempt_at, last_error)` in the transaction that clears the row's `sending_provider_ref`. `provider` is the one configured when recorded (blank if `none`: the next one configured removes it); only that provider runs the removal, any other leaves it waiting (logged), as `none` does. A provider whose registrations exist nowhere but on our row (`removal_needed` false: `manual`) records none. The record goes once the provider confirmed. While one exists for a domain (with the configured provider or blank: choice 16), enabling sending on it (any organization) is a 409 `removal_pending`, as is the provider answering that it already knows the name (TEM's 409); that answer with no record of ours is a 409 `provider_conflict` ("This domain is already registered with the sending service. Contact your Showdesk administrator."), logged as an error. Its task retries up to 8 times with a growing delay, stamping `last_attempt_at` on each try; an hourly sweep queues again every record not tried for 3 h (or never tried and created 3 h ago), whatever its attempts, logging an error from 8 attempts on. A broker down when queueing is only logged: the request succeeds and the sweep catches up. | A removal outlives its row; its retries can be seen (admin, read-only list); one guard covers every case. The new owner's registration of the same name must not race the removal of the old one (TEM refuses a name already in the project, and a late removal would delete the new one). Nothing stays stuck: the sweep doesn't depend on a task's state. | 4, 5 |
| 6 | The `manual` adapter asks for an SPF include (`include:{SENDING_DOMAIN_SPF_INCLUDE}`) and a DKIM **CNAME** `{selector}._domainkey.{domain}` → `{selector}._domainkey.{INBOUND_EMAIL_DOMAIN}`, and checks that the TXT found through it is the operator's key. | Showdesk can't know a per-domain DKIM key it didn't create. A CNAME to one key the operator publishes once is checkable, and is what a self-hosted signer (OpenDKIM, Postal with a shared key, Haraka) can do for every customer domain. | 2 |
| 7 | A check that can't conclude (DNS timeout, provider HTTP error) changes nothing. `dns_verification.lookup_txt()` returns `None` on such errors, unlike `query_txt_records()`. | A resolver hiccup must not flip every verified domain to the fallback and mail every admin. | 2, 3, 7 |
| 8 | A provider PENDING result on a verified row (a regression) puts it back to `pending` with a new 72 h window, and mails the admins once. A provider FAILED result sends the row to `failed`, from `pending` or from `verified`. 72 h of `pending` → `failed`, mailed once; `failed` rows are only checked by "Check now", and set up again by enabling (which replaces the registration). Reaching `verified` is mailed too. | Records removed by mistake heal by themselves when restored; a FAILED result doesn't heal (TEM's `locked` and `revoked` are final), so waiting would only delay the admins. The admins know about each change. One template, `sending_domain_status`. | 7 |
| 9 | "Check now" is limited to once per 30 s per domain (cache lock). | Each call hits DNS or the provider's API. | 4 |
| 10 | The From is decided at send time (`sendable_address(mailbox)`), never stored. It covers the four mails using `from_address`: reply, unread reply, conversation link, resolved. | A transfer or a regression takes effect on the next mail, without a migration of anything. | 6 |
| 11 | TEM record names are normalised to fully qualified names; records are stored as `[{type, name, value}]` in the order SPF, DKIM, DMARC. TEM's MX is never shown. SPF records (TEM's and `manual`'s) and TEM's DMARC carry `"merge": true`: a domain has at most one of each, so if one exists the value is merged into it rather than published as a second record. | The wizard shows exactly what to publish. TEM's MX points to a blackhole meant for send-only domains; ours host the support address and receive mail, so publishing it would lose that mail. Two SPF or two DMARC records make receivers ignore both. | 3 |
| 12 | `requests` is added to `requirements.txt` explicitly (already installed through Anymail). | A direct import must not depend on a transitive pin. | 3 |
| 13 | The organization payload carries `sending_domains_enabled` (provider ≠ `none`); a mailbox carries `sends_from_public_address`. | The wizard is hidden with `none`; the card says which From is used now. | 6 |
| 14 | A public webmail domain (`is_public_email_domain`) is never verified, for any purpose: refused on create (DNS and admin email). A webmail row verified before the rule never counts as ownership: `enable_sending` refuses it (400 `public_domain`), `on_ownership_verified` and the squatting migration ignore it, a public address can't be set on it, and it is never sendable. Its status is left as it is. | Nobody owns `gmail.com`: verifying it would let one organization free everybody's addresses on it, or send as it. | 5 |
| 15 | Sending needs the row's own ownership TXT, `_showdesk.<domain>` = `showdesk-verification=<token>`, under every provider and at every check (checked by the services, not by each provider). `enable_sending` gives a row without a token (verified by admin email) one, also when its sending is already pending or verified, leaving its ownership status and method alone; the stored records start with that TXT, refreshed first at every check (an older `_showdesk` TXT dropped), whether or not the provider returns records. The check combines it with the provider's result: a provider FAILED or UNKNOWN stands; a TXT lookup that can't conclude is UNKNOWN; a missing TXT is PENDING ("The _showdesk TXT record proving your organization controls this domain is missing."), so a verified row regresses. | `manual`'s records (SPF include, DKIM CNAME) are the same for every organization: published by the domain's real owner for its own account, they would also verify a squatter's row. An admin-email verification proves a mailbox on the domain, not control of its DNS. And TEM's re-registration of a revoked name is unconfirmed (Known limitations): the per-organization token doesn't depend on it. | review |
| 16 | `OrganizationDomain.sending_provider`: the provider a registration was made with, set with the ref and cleared with it. Only a row of the configured provider (or blank: older than the field) is sendable. A row registered with another one is reset by the periodic check, "Check now" or enabling (status `""`, records, error, dates), without mail; its registration becomes a `SendingRemoval` with that provider, unless that provider has nothing to remove (`manual`, `none`): it waits until that provider is configured again, the hourly sweep queueing it every 3 h and its task logging a warning each time. Such a removal doesn't block setting the domain up again: only one with the configured provider (or blank) is `removal_pending`, before registering and on the provider's "already registered" answer. The domain payload shows such a row as not set up (`sending_status` `""`, no records) until it is reset. Sendable means `sending_provider` equal to the configured one, exactly. | The records the admins published were the previous provider's: sending from them under the new one would be unchecked. The admins set the domain up again; the old registration is the old provider's to remove, held there, so it can't clash with a registration at the new one. | review |
| 17 | A DNS win clears the `verification_token` of every other organization's row of the domain (the previous owner's, now `failed`, and any pending one): their admins regenerate a token to claim it again; until then, verify on such a row is `still_pending`. | A TXT left published by the previous owner would otherwise win the domain straight back at its next verify, or at the pending poller's next run. | review |

---

## Working rules

Environment: disposable `showdesk-test-pg` (`postgres:17-alpine`, port 25432, user/password/db `showdesk`) and `showdesk-test-redis` (`redis:8-alpine`, port 26379); never another container. If the Docker engine stops answering, don't restart it: use a disposable Homebrew Postgres and Redis on those ports and say so.

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

- TDD: failing test, watch it fail, minimal code, watch it pass, commit. Every task ends with a Conventional Commit (`feat(backend): …`, `feat(frontend): …`).
- Few distinct test cases, no large parametrized tables.
- Only the HTTP boundary (TEM: `requests.request` in `scaleway_tem.py`) and the DNS boundary (`dns_verification.lookup_txt`) are mocked. Exception: the service tests (`test_sending_services.py`) put a fake provider at `get_provider`, being about what the services store; the HTTP and DNS boundaries are tested in the provider tests, and the API tests go through `manual` with the DNS boundary patched.
- English in code, comments and product strings. Nothing about Showdesk Cloud in this repo.
- Every new setting goes in `.env.example` with a safe default and in `docker-compose.prod.yml`.
- Celery tasks stay on the `default` queue (production consumes `default` and `video_processing` only).
- Reviewers leave no shell running and review a detached copy if an implementer is still committing.

---

## Batch 1: Model and providers

### Task 1: Sending fields on `OrganizationDomain`

**Files:**
- Modify: `backend/apps/organizations/models.py` (`OrganizationDomain`)
- Create: `backend/apps/organizations/migrations/00XX_organizationdomain_sending.py`
- Modify: `backend/apps/organizations/serializers.py` (`OrganizationDomainSerializer`), `backend/apps/organizations/admin.py`
- Test: `backend/tests/organizations/test_organization_domains.py`

**Step 1: Failing tests**

```python
def test_sending_alone_is_a_purpose(self, organization) -> None:
    row = OrganizationDomain.objects.create(organization=organization, domain="acme.com", is_sending=True)
    assert row.sending_status == ""

def test_create_for_sending_is_refused_without_a_provider(admin_client, settings):
    settings.SENDING_DOMAIN_PROVIDER = "none"
    response = admin_client.post(URL, {"domain": "acme.com", "is_sending": True})
    assert response.status_code == 400 and "is_sending" in response.json()

def test_sending_state_is_read_only(admin_client, settings, organization):
    # PATCH sending_status / sending_dns_records / sending_provider_ref → ignored
```

**Step 2: Run** `cd backend && python -m pytest -q tests/organizations/test_organization_domains.py` → FAIL (unknown field).

**Step 3: Implement**

```python
class SendingStatus(models.TextChoices):
    NONE = "", "Not set up"
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    FAILED = "failed", "Failed"

is_sending = models.BooleanField(default=False)
sending_status = models.CharField(max_length=20, choices=SendingStatus.choices, default="", blank=True, db_index=True)
sending_provider_ref = models.CharField(max_length=255, blank=True)
sending_dns_records = models.JSONField(default=list, blank=True)  # [{type, name, value}]
sending_requested_at = models.DateTimeField(null=True, blank=True)
sending_last_checked_at = models.DateTimeField(null=True, blank=True)
sending_last_error = models.CharField(max_length=500, blank=True)
```

CHECK constraint `domain_has_at_least_one_purpose` → `Q(is_branding=True) | Q(is_email_routing=True) | Q(is_sending=True)` (drop and re-add in the migration). Serializer: add `is_sending` (writable on create only; refused unless `settings.SENDING_DOMAIN_PROVIDER != "none"`), the sending fields read-only except `sending_provider_ref`, which is never exposed. `validate()` accepts any of the three purposes. `services.try_admin_email_autoverify` and `start_dns_challenge` take `is_sending` too, and the view passes it. Admin: list `is_sending`, `sending_status`.

`SENDING_DOMAIN_PROVIDER` is introduced here in `base.py` (`config("SENDING_DOMAIN_PROVIDER", default="none").strip().lower()`), documented in Task 2.

**Step 4: Run, PASS; migrations check.** **Step 5: Commit** `feat(backend): sending state on organization domains`.

### Task 2: Provider interface, `none` and `manual`

**Files:**
- Create: `backend/apps/email_channel/sending/__init__.py`, `providers.py`, `manual.py`
- Modify: `backend/apps/organizations/dns_verification.py` (`lookup_txt`)
- Modify: `backend/config/settings/base.py`, `.env.example`, `docker-compose.prod.yml`
- Test: `backend/tests/email_channel/test_sending_providers.py`

**Step 1: Failing tests** (patch `apps.organizations.dns_verification.lookup_txt`)

```python
def test_manual_register_asks_for_an_spf_include_and_a_dkim_cname(settings):
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    settings.SENDING_DOMAIN_SPF_INCLUDE = "spf.mail.example.net"
    settings.SENDING_DOMAIN_DKIM_SELECTOR = "showdesk"
    registered = get_provider().register("acme.com")
    assert registered.ref == "acme.com"
    assert registered.records == [
        {"type": "TXT", "name": "acme.com", "value": "v=spf1 include:spf.mail.example.net ~all"},
        {"type": "CNAME", "name": "showdesk._domainkey.acme.com", "value": f"showdesk._domainkey.{INBOUND_DOMAIN}"},
    ]

def test_manual_check_is_verified_when_both_records_are_published(): ...
    # lookup_txt: acme.com → ["v=spf1 include:_spf.google.com include:spf.mail.example.net ~all"],
    # both DKIM names → ["v=DKIM1; k=rsa; p=MIIB…"] → DomainCheck(VERIFIED, "")

def test_manual_check_names_what_is_missing(): ...
    # SPF without the include → PENDING, error mentions SPF; DKIM TXT differs from the operator's → PENDING, mentions DKIM

def test_manual_check_that_cannot_resolve_is_unknown(): ...
    # lookup_txt returns None → CheckStatus.UNKNOWN

def test_none_provider_refuses_to_register(): ...  # raises SendingProviderError
def test_manual_without_settings_is_misconfigured(): ...  # ImproperlyConfigured on get_provider()
```

**Step 2: Run, FAIL.**

**Step 3: Implement**

```python
# providers.py
class CheckStatus(enum.StrEnum):
    VERIFIED = "verified"
    PENDING = "pending"   # Not there yet, or no longer.
    FAILED = "failed"     # The provider gave up on it (TEM locked / revoked).
    UNKNOWN = "unknown"   # Couldn't tell: change nothing.

@dataclass(frozen=True)
class RegisteredDomain:
    ref: str
    records: list[dict[str, str]]

@dataclass(frozen=True)
class DomainCheck:
    status: CheckStatus
    error: str = ""
    records: list[dict[str, str]] | None = None  # When the provider gives newer ones.

class SendingProviderError(Exception): ...
class SendingDomainProvider(Protocol):
    def register(self, domain: str) -> RegisteredDomain: ...
    def check(self, ref: str) -> DomainCheck: ...
    def remove(self, ref: str) -> None: ...

def sending_enabled() -> bool: return settings.SENDING_DOMAIN_PROVIDER != "none"
def get_provider() -> SendingDomainProvider: ...  # "none" | "manual" | "scaleway_tem", else ImproperlyConfigured
```

`dns_verification.lookup_txt(name) -> list[str] | None`: `[]` on NXDOMAIN/NoAnswer, `None` on timeout/NoNameservers/other DNS errors; `query_txt_records` becomes `lookup_txt(name) or []`.

`ManualProvider.check(ref)`: SPF ok iff a TXT on the domain starts with `v=spf1` and has the token `include:{SPF_INCLUDE}`; DKIM ok iff the TXT at `{selector}._domainkey.{domain}` equals the TXT at `{selector}._domainkey.{INBOUND_EMAIL_DOMAIN}` and contains `p=`. Any `None` → UNKNOWN. `remove()` does nothing. `register()` needs `INBOUND_EMAIL_DOMAIN`.

Settings and docs:

```
SENDING_DOMAIN_PROVIDER=none          # none | manual | scaleway_tem
SENDING_DOMAIN_SPF_INCLUDE=           # manual: the include of your sending service, e.g. spf.mail.example.net
SENDING_DOMAIN_DKIM_SELECTOR=         # manual: publish your DKIM key at <selector>._domainkey.<INBOUND_EMAIL_DOMAIN>,
                                      # and have your sending service sign every customer domain with it
SCW_TEM_SECRET_KEY=
SCW_TEM_PROJECT_ID=
SCW_TEM_REGION=fr-par
```

**Step 4: PASS.** **Step 5: Commit** `feat(backend): sending domain providers, none and manual`.

### Task 3: `scaleway_tem` adapter

**Files:**
- Create: `backend/apps/email_channel/sending/scaleway_tem.py`
- Modify: `backend/requirements.txt` (`requests>=2.32,<3.0`)
- Test: `backend/tests/email_channel/test_sending_providers.py`

**Step 1: Failing tests** (patch `apps.email_channel.sending.scaleway_tem.requests.request` with a fake returning canned JSON; assert method, URL, `X-Auth-Token`, body)

```python
def test_tem_register_creates_the_domain_and_returns_its_records(): ...
    # POST /transactional-email/v1alpha1/regions/fr-par/domains {"project_id", "domain_name": "acme.com", "autoconfig": False}
    # response records {"spf": {"name": "", "value": "v=spf1 include:_spf.tem.scaleway.com -all"},
    #                   "dkim": {"name": "<project>._domainkey", "value": "v=DKIM1; …"}, "mx": …, "dmarc": …}
    # → ref == id; names fully qualified; order spf, dkim, dmarc; no MX; merge on spf and dmarc
def test_tem_check_maps_statuses(): ...
    # GET … gives the status (POST …/check only triggers the next check): checked → VERIFIED; unchecked/pending/autoconfiguring/invalid → PENDING with last_error; locked/revoked → FAILED
def test_tem_http_errors_raise_a_provider_error(): ...
    # 5xx / timeout on check → SendingProviderError (the caller reads UNKNOWN); 409 on register → SendingProviderError("already registered…")
def test_tem_remove_revokes(): ...  # POST …/revoke; 404 and 409 count as removed
```

**Step 3: Implement** a small `_call(method, path, json=None)` with a 10 s timeout, `raise_for_status` mapped to `SendingProviderError` (message without the secret). `ImproperlyConfigured` without key or project.

**Step 5: Commit** `feat(backend): Scaleway TEM sending domain provider`.

**Batch 1 review** (superpowers:code-reviewer): model/migration, adapters, settings documentation, no secret in logs or errors.

---

## Batch 2: Services, API, From

### Task 4: Enable, check, disable

**Files:**
- Create: `backend/apps/email_channel/sending/services.py`
- Modify: `backend/apps/organizations/views.py` (`OrganizationDomainViewSet` actions)
- Test: `backend/tests/email_channel/test_sending_services.py`, `backend/tests/email_channel/test_sending_api.py`

Services (all take the row; DB writes under `select_for_update`, provider calls outside transactions):

- `enable_sending(row)`: requires `sending_enabled()`, a domain that isn't public webmail (400 `public_domain`), `row.status == verified`, `sending_status in ("", "failed")`, and no `SendingRemoval` of the same domain (409 `removal_pending`, also when the provider says it already knows the name). A failed registration of the row itself is removed first (recorded, tried at once; 502 if the provider fails, the removal going on in the background). Registers, then stores `is_sending=True`, `sending_status=pending`, ref, records, `sending_requested_at=now`, clears the error, and runs one `check_sending(row)`. A registration made but not stored (the row deleted or no longer owned meanwhile: 400 `not_owned`; any error while storing) is recorded for removal. A cache lock per domain name (300 s, released when done) stops a double click from registering twice. On `SendingProviderError`: nothing stored, 502 with its message.
- `check_sending(row) -> CheckStatus`: calls the provider, applies the transition (Task 7 adds the mails), sets `sending_last_checked_at`, `sending_last_error`, newer records if any. UNKNOWN changes nothing but `sending_last_checked_at`. A row no longer verified in ownership is never checked (and never sends).
- `disable_sending(row)`: resets `sending_status=""`, ref, records, error, recording the removal in the same transaction, then tries the removal at once; if the provider fails, `remove_sending_registration` is queued.
- Removals (choice 5): `SendingRemoval` model and its read-only admin, `remove_sending_registration(removal_id)` (deletes the record on success; on `SendingProviderError` counts the try and retries with a growing delay, giving up at 8 with an error log), `requeue_sending_removals` (hourly beat, default queue: records not tried for 3 h, whatever their attempts). A data migration records the refs held by rows not set up for sending.

API (admins; agents get 403):

```
POST   /api/v1/organization-domains/{id}/sending/         → 200 row (pending or verified) | 400 not_owned | 409 removal_pending | 502 provider_error
POST   /api/v1/organization-domains/{id}/sending/check/   → 200 row | 429 too_soon | 400 not_registered
DELETE /api/v1/organization-domains/{id}/sending/         → 200 row
```

All three are 404 while `SENDING_DOMAIN_PROVIDER=none`.

Tests: enable on a pending ownership is 400; enable stores the records and checks once; enable while a removal of the domain is recorded, or the provider already knows the name, is 409; a registration not stored is recorded for removal; a failed removal is recorded, counted and retried, given up at 8, swept hourly, and waits without a provider; check twice within 30 s is 429; disable resets; agent 403; cross-org 404.

**Commit** `feat(backend): set up sending from a verified domain`.

### Task 5: Public addresses need a verified domain; verification frees them

**Files:**
- Modify: `backend/apps/email_channel/serializers.py` (`MailboxSerializer.validate`)
- Modify: `backend/apps/organizations/services.py` (`try_admin_email_autoverify`, `apply_dns_verification_success`), `backend/apps/organizations/views.py` (`destroy`)
- Modify: `backend/apps/email_channel/sending/services.py` (`on_ownership_verified`), `backend/apps/email_channel/signals.py` (`pre_delete` of `OrganizationDomain`)
- Create: `backend/apps/email_channel/migrations/0005_free_squatted_public_addresses.py`
- Test: `backend/tests/email_channel/test_mailbox_api.py`, `backend/tests/email_channel/test_sending_services.py`

Rules:

- `MailboxSerializer.validate`: a new or changed non-empty `public_address` needs an `OrganizationDomain` of the mailbox's organization with that exact domain and `status=verified`; else 400 on `public_address`: "Verify {domain} for your organization first." Unchanged values pass.
- `on_ownership_verified(row)`, called by both verification paths inside their transaction once the row is saved verified (both lock every row of the domain), so the freeing and the verification commit together: unless the row, re-read, is no longer verified or the domain is public webmail, mailboxes of other organizations with a public address `@{domain}` get `public_address=""`; every other row of that domain gets `is_sending` unchanged, `sending_status=""` and, if it holds a ref, a recorded removal, queued on commit.
- Deleting a row with a ref (destroy, or its organization's deletion) records its removal: a `pre_delete` receiver connected by the email channel's AppConfig.
- A data migration clears the public addresses already set on a domain another organization has verified.

Tests: setting a public address on an unverified domain is 400, on a verified one 200, an unchanged legacy one passes; org B winning the DNS challenge clears org A's mailbox address and resets A's sending state, recording the removal, without a commit callback and leaving the winner's own sending state alone; a stale call for a row no longer verified does nothing; admin-email verification frees a squatter's address; a webmail domain is refused by the admin-email service, the create API and `enable_sending`; the migration's function frees squatted addresses.

**Commit** `fix(backend): tie public addresses to a verified domain`.

### Task 6: From the public address when it is sendable

**Files:**
- Modify: `backend/apps/email_channel/sending/services.py` (`sendable_address`), `backend/apps/email_channel/outbound.py` (`from_address`)
- Modify: `backend/apps/email_channel/serializers.py` (`sends_from_public_address`), `backend/apps/organizations/serializers.py` (`sending_domains_enabled`)
- Test: `backend/tests/email_channel/test_outbound.py`, `test_mailbox_api.py`, `backend/tests/organizations/test_api.py`

```python
def sendable_address(mailbox) -> str | None:
    """The mailbox's public address, if mail may go out from it (§7.1)."""
    if not (sending_enabled() and mailbox.public_address):
        return None
    domain = mailbox.public_address.rpartition("@")[2]
    ok = OrganizationDomain.objects.filter(
        organization_id=mailbox.organization_id, domain=domain,
        status=OrganizationDomain.Status.VERIFIED,
        sending_status=OrganizationDomain.SendingStatus.VERIFIED,
    ).exists()
    return mailbox.public_address if ok else None
```

`from_address` uses `sendable_address(mailbox) or mailbox.inbound_address`. Tests: verified + verified → public address in From (end to end through `send_ticket_reply_email`, checking `mail.outbox[0].from_email`, Reply-To unchanged); pending sending → inbound address; ownership lost (row `failed`) → inbound; provider `none` → inbound even with a verified row.

**Commit** `feat(backend): send replies from a verified public address`.

**Batch 2 review.**

---

## Batch 3: Periodic checks

### Task 7: Beat task, admin mails

**Files:**
- Modify: `backend/apps/email_channel/tasks.py`, `backend/apps/email_channel/sending/services.py`
- Create: `backend/templates/emails/sending_domain_status.{html,txt}`
- Modify: `backend/config/settings/base.py` (`CELERY_BEAT_SCHEDULE["check-sending-domains"]`, every 15 min)
- Test: `backend/tests/email_channel/test_sending_tasks.py`

- `check_sending_domains()`: rows with ownership `verified` and either `sending_status=pending`, or `verified` and `sending_last_checked_at` older than 24 h (or null). Each in its own try/except. Nothing while the provider is `none`.
- Transitions in `check_sending` (already decided by `next_sending_status`; this task adds the mails and the 72 h limit): pending→verified (mail "verified"); verified→pending on a PENDING result (`sending_requested_at=now`, a new 72 h window, mail "regressed"); a FAILED result → failed from pending or verified (mail "failed"); pending past 72 h since `sending_requested_at` → failed (mail "failed"). Mails to active admins through `send_branded_email(fail_silently=True)`, one per transition.
- The removal task and its sweep are already there (Batch 2, choice 5).

Tests: pending → verified mails once and From switches; verified with records gone → pending + one mail, From falls back; verified with a FAILED result → failed + one mail; 72 h → failed; UNKNOWN changes nothing; verified rows checked at most daily.

**Commit** `feat(backend): check sending domains periodically`.

**Batch 3 review.**

---

## Batch 4: Frontend

### Task 8: Types, API, hooks

**Files:**
- Modify: `frontend/src/types/index.ts` (`OrganizationDomain` sending fields, `SendingRecord`, `Mailbox.sends_from_public_address`, `Organization.sending_domains_enabled`)
- Modify: `frontend/src/api/organizationDomains.ts` (`enableSending`, `checkSending`, `disableSending`)
- Create: `frontend/src/hooks/useOrganizationDomains.ts` (query + mutations invalidating `organization-domains` and `mailboxes`)
- Test: `frontend/src/api/__tests__/organizationDomains.test.ts`

**Commit** `feat(frontend): sending domain API`.

### Task 9: The wizard in the Email tab

**Files:**
- Create: `frontend/src/components/settings/SendingDomainWizard.tsx`
- Modify: `frontend/src/components/settings/MailboxesTab.tsx` (card: "Sends from" line, "Send from your domain" button for admins when `sending_domains_enabled`), `frontend/src/components/settings/DomainsList.tsx` ("Sending" purpose badge and status)
- Test: `frontend/src/components/settings/__tests__/SendingDomainWizard.test.tsx`, `MailboxesTab.test.tsx`

Wizard, opened on a mailbox:

1. **Address and ownership.** Address prefilled with the public address. Its domain's row: verified → done; pending → TXT record name/value with copy buttons, "Check now" (`verify`), "New token"; none → "Verify with DNS" (create, `dns_txt`, `is_sending`) and "Verify with my email" when the admin's own address is on that domain. Once verified and the address differs from the mailbox's, save it (`PATCH` mailbox).
2. **DNS records.** "Get the records" (`POST …/sending/`), then a table type / name / value with copy buttons, and a note: "Already have an SPF record? Add the include to it rather than a second record."
3. **Status.** Badge pending / verified / failed, last check, last error, "Check now", "Stop sending from this domain" (confirmed).

The card shows "Replies are sent from {public_address}" or "Replies are sent from {inbound_address}". The mailbox form shows the 400 message of Task 5 under the field.

Tests: each step renders from a mocked domain state; step 1 → 2 on verification; copy buttons; hidden without `sending_domains_enabled` or for agents.

**Commit** `feat(frontend): send-from-your-domain wizard`.

### Task 10: Seed, docs

- `manage.py seed`: the demo domain row of the demo mailbox's domain gets `is_sending=True` (no registration).
- Design doc: §11 "As built (PR 3)" with the choices above, remove the squatting Known limitation (replaced by: "A public address needs its domain verified; verification by another organization frees it."), §8 table unchanged except the manual DKIM CNAME.
- `.env.example`, `docker-compose.prod.yml` checked against `base.py`.

**Commit** `docs: sending domains as built`.

**Batch 4 review**, then **final review of the whole branch**.

---

## Validation

1. Local: backend, lint, migrations, frontend all green.
2. Real browser (Playwright on a local stack with `SENDING_DOMAIN_PROVIDER=manual` and the DNS boundary patched, or a real domain we control): wizard steps 1 → 3, errors shown, card's "sends from".
3. PR to `develop`, CI green, merge, deploy dev.
4. Dev (`manual`): add the non-secret variables to the dev `env` secret (`SENDING_DOMAIN_PROVIDER=manual`, `SENDING_DOMAIN_SPF_INCLUDE`, `SENDING_DOMAIN_DKIM_SELECTOR`), redeploy, then:
   - setting a public address on an unverified domain is refused;
   - ownership by DNS TXT on a domain whose DNS we can edit, records shown, check → pending;
   - forcing the row's sending status in the shell → reply mail in Mailpit `From: support@…`, Reply-To and threading unchanged; back to pending → inbound address;
   - `check_sending_domains` run by hand: regression mail in Mailpit;
   - transfer: a second org verifies the domain → first org's address freed, its From falls back.
5. TEM: needs `SCW_TEM_SECRET_KEY` and `SCW_TEM_PROJECT_ID` from Dimitri (a key restricted to Transactional Email on the target project); until then it's covered by HTTP-boundary tests only. Confirm a revoked domain name can be registered again (disable then enable, and a transfer).
