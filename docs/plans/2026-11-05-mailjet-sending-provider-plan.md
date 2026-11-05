# Mailjet Sending Domain Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan, with a review after the batch.

**Goal:** A fourth `SENDING_DOMAIN_PROVIDER`, `mailjet`, registers an organization's domain as a Mailjet sender, shows the records Mailjet asks for, and checks them, so that Showdesk instances sending through Mailjet can send from their customers' domains.

**Why:** decided on 2026-11-05 (Dimitri): Showdesk Cloud moves its outbound mail to Mailjet rather than configuring Scaleway TEM's API. `scaleway_tem` stays available.

**Architecture:** one module `backend/apps/email_channel/sending/mailjet.py`, same shape as `scaleway_tem.py` (`register`, `check`, `remove`, `removal_needed = True`), registered in `providers.provider_class`. Everything else (ownership TXT, transitions, removals, beat, wizard) is provider-agnostic and unchanged.

**Tech Stack:** `requests`, HTTP basic auth, Mailjet Email API v3 (`/v3/REST/sender`, `/v3/REST/dns`).

**Authoritative documents:** `docs/plans/2026-11-04-sending-domains-plan.md` (choices, working rules: binding), design `docs/plans/2026-10-29-email-channel-design.md` §7 and §11.

**Branch:** `feat/mailjet-sending-provider` from `develop`, PR to `develop`.

---

## What Mailjet's API says (dev.mailjet.com OpenAPI reference, 2026-11-05)

- Auth: HTTP basic, public API key / private API key. Host `https://api.mailjet.com` (US accounts: `https://api.us.mailjet.com`).
- `POST /v3/REST/sender` `{"Email": "*@acme.com", "EmailType": "transactional"}` → 201, `Data[0]`: `ID`, `DNSID`, `Status` (`Inactive` | `Active` | `Deleted`), `Filename`. `DNSID` is `-1` while the sender is inactive. A sender must be registered **and validated** (Active) before mail can go out from it.
- `GET /v3/REST/sender/{id}` → the same fields.
- `POST /v3/REST/sender/{id}/validate` → 201, `Data[0]`: `ValidationMethod`, `Errors`, `GlobalError`. A domain sender is validated by an ownership token found in the DNS (or a file on the website root).
- `GET /v3/REST/dns/{dns_id}` → `ID`, `Domain`, `DKIMRecordName`, `DKIMRecordValue`, `DKIMStatus` (`OK` | `Error` | `Not checked`), `SPFRecordValue`, `SPFStatus` (`OK` | `Error` | `Not checked` | `Not found`), `OwnerShipToken`, `OwnerShipTokenRecordName`. `GET /v3/REST/dns` lists them (no domain filter).
- `POST /v3/REST/dns/{dns_id}/check` → 201, `Data[0]`: `DKIMStatus`, `SPFStatus` (`OK` | `Error`), `DKIMErrors`, `SPFErrors`.
- `DELETE /v3/REST/sender/{id}` → 204.
- Undocumented, so handled defensively and confirmed on a real account: the literal record values (read from the API, never hard-coded), the answer to a duplicate sender, re-adding a deleted domain, and whether `/dns/{domain}` accepts a domain name.

## Choices beyond the design

| # | Choice | Why |
|---|---|---|
| M1 | Credentials are the existing `MAILJET_API_KEY` / `MAILJET_SECRET_KEY` (Anymail's); one new setting `MAILJET_API_URL` (default `https://api.mailjet.com`). | The domains must be in the account that sends: the same keys. |
| M2 | The ref is the sender `ID` (digits only, checked before any URL). | Mailjet addresses a sender by its numeric id; `DELETE` takes it. |
| M3 | The DNS entry is found by `DNSID` when the sender has one, else by `GET /v3/REST/dns/{domain}`, else by scanning `GET /v3/REST/dns` for `Domain` (paged, bounded). | A new sender is inactive, so `DNSID` is `-1` until validated, yet its records are needed to validate it. |
| M4 | Records shown: Mailjet's ownership TXT (`OwnerShipTokenRecordName` = `OwnerShipToken`), SPF TXT on the domain (`SPFRecordValue`, `merge`), DKIM TXT (`DKIMRecordName` = `DKIMRecordValue`). Names fully qualified. | What Mailjet checks; Showdesk's own `_showdesk` TXT is still added first by the services. |
| M5 | `check`: read the sender; `Deleted` → FAILED; `Inactive` → ask Mailjet to validate it (its errors kept); then `POST /dns/{id}/check`. VERIFIED only when the sender is `Active` and DKIM and SPF are `OK`; otherwise PENDING with Mailjet's error texts (trimmed, never containing credentials). HTTP or network errors → `SendingProviderError` (UNKNOWN). | Mailjet only sends from an active sender, and DKIM/SPF are what DMARC alignment needs. |
| M6 | `register` on a domain Mailjet already has: a 400 whose message says it exists → `AlreadyRegisteredError` (answered 409 like TEM's). | The services already distinguish a pending removal from a conflict. |
| M7 | `remove`: `DELETE /v3/REST/sender/{id}`; 404 counts as removed. | Idempotent removals. |

## Task 1: `mailjet` provider

**Files:**
- Create: `backend/apps/email_channel/sending/mailjet.py`
- Modify: `backend/apps/email_channel/sending/providers.py` (`provider_class`, docstring, error message), `backend/config/settings/base.py` (`MAILJET_API_URL`), `.env.example`, `docker-compose.prod.yml`
- Test: `backend/tests/email_channel/test_sending_providers.py` (patch `requests.request` as imported in `mailjet.py`, as for TEM)

**Steps (TDD):**
1. Failing tests, few and distinct:
   - register: POST sender body and basic auth; inactive sender (`DNSID: -1`) → records found through `/dns/{domain}`; then through the list scan when that 404s; records in order ownership, SPF (`merge`), DKIM, fully qualified; ref = sender ID.
   - register on an existing domain → `AlreadyRegisteredError`; 5xx → `SendingProviderError`; credentials never in messages.
   - check: inactive sender → validate called, PENDING with its error; active + DKIM/SPF OK → VERIFIED; active + DKIM Error → PENDING with the DKIM error; Deleted → FAILED; network error → `SendingProviderError`; non-numeric ref refused before any call.
   - remove: DELETE; 404 tolerated.
   - `get_provider()` with `mailjet` and no keys → `ImproperlyConfigured`.
2. Run, watch them fail. 3. Implement. 4. Run the whole suite, ruff, migrations check. 5. Commit `feat(backend): Mailjet sending domain provider`.

## Task 2: docs

- `.env.example`: `SENDING_DOMAIN_PROVIDER` lists `mailjet`; a paragraph: with `mailjet`, outbound mail must go through the same Mailjet account (`EMAIL_BACKEND=anymail.backends.mailjet.EmailBackend` and the same keys), and `INBOUND_EMAIL_DOMAIN` must be a validated Mailjet sender domain too (fallback mail is sent from it). `MAILJET_API_URL` documented.
- `docker-compose.prod.yml`: `MAILJET_API_URL`.
- Design §7.2 (adapter list), §8 (variables), §11 (a row for `mailjet`), Known limitations (Mailjet behaviour confirmed only with a real account).
- Commit `docs: Mailjet sending domain provider`.

**Batch review** (superpowers:code-reviewer), fixes, PR, CI, merge, dev deploy. Real validation needs a Mailjet account's keys on the dev (Dimitri).
