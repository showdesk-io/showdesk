# Mailjet Sending Domain Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan, with a review after the batch.

**Goal:** A fourth `SENDING_DOMAIN_PROVIDER`, `mailjet`, registers an organization's domain as a Mailjet sender, shows the records Mailjet asks for, and checks them, so that Showdesk instances sending through Mailjet can send from their customers' domains.

**Why:** For operators who send through Mailjet; `scaleway_tem` stays available.

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

## Confirmed on a real account (2026-11-05)

What Mailjet actually does, which the reference didn't say or said otherwise (values shortened, example domain):

- `POST /v3/REST/sender` `{"Email": "*@acme.com", "EmailType": "transactional"}` → 201, `Data[0]`: `CreatedAt`, `DNSID`, `Email`, `EmailType`, `Filename` (`<token>.txt`), `ID`, `IsDefaultSender`, `Name`, `Status: "Inactive"`. **`DNSID` is a real id even while the sender is inactive** (not `-1`).
- The same `POST` when the account already has a sender for the domain → 400 "There is an already existing inactive sender with the same email. You can use \"validate\" action in order to activate it." (or "…already existing deleted sender…"). Mailjet keeps deleted senders.
- `GET /v3/REST/sender?Email=*@acme.com` lists the non-deleted senders only; with `&ShowDeleted=true`, the deleted ones too. A `Domain` filter doesn't work.
- `GET /v3/REST/sender/{id}` → 200, `Data[0]` with the same fields; a deleted sender still reads, `Status: "Deleted"`.
- `GET /v3/REST/dns/{DNSID}` → 200, `Data[0]`: `Domain`, `DKIMRecordName` (`mailjet._domainkey.acme.com.`), `DKIMRecordValue` (`k=rsa; p=…`), `DKIMStatus`, `SPFRecordValue` (`v=spf1 include:spf.mailjet.com ?all`), `SPFStatus`, `OwnerShipToken`, `OwnerShipTokenRecordName` (`mailjet._<token[:8]>.acme.com.`). Names may end with a dot. Once the sender is deleted: 404 `{"ErrorInfo": "", "ErrorMessage": "Object not found", "StatusCode": 404}`. `GET /v3/REST/dns/{domain name}` is always 404: not supported.
- `POST /v3/REST/dns/{DNSID}/check` → **200**, `Data[0]`: `DKIMErrors` and `SPFErrors` are **lists** (`["no DKIM record"]`), `DKIMRecordCurrentValue`, `SPFRecordsCurrentValues`, `DKIMStatus` / `SPFStatus` `Error` or `OK`.
- `POST /v3/REST/sender/{id}/validate` → **200, not wrapped in `Data`**: `{"ValidationMethod": "", "Errors": {"FileValidationError": "…", "DNSValidationError": "DNS record verification failed as no TXT record for that ownership token was found on the remote server."}, "GlobalError": "Neither the file at your domain root nor the DNS TXT record have been found to validate this sender."}`. On success, presumably `Errors` empty and `GlobalError` `""`, the sender then reading `Active`. Mailjet says (its 400 above) that `validate` activates an existing inactive or deleted sender; to confirm for a deleted one: not observed yet.
- `DELETE /v3/REST/sender/{id}` → 204, and 204 again on a sender already deleted.
- The ownership token equals `Filename` without `.txt`; its record is `mailjet._<first 8 characters of the token>.<domain>`.
- Mailjet's documented limit: at most 100 senders (active and inactive, deleted ones not counted) per account.

So the adapter now (superseding M3, M5 and M6 below): reads the DNS entry by `DNSID` only; on that 400, reuses the existing sender (found with `ShowDeleted=true`, a non-deleted one first) only when it is `Inactive` or `Deleted`, an `Active` one being `AlreadyRegisteredError` (someone's in use: the operator's own, or one set up by hand); its records are read from `/dns/{DNSID}`, or, when that 404s, the ownership TXT derived from `Filename` and the SPF record (`merge`), DKIM coming with the first check after reactivation. A 400 whose message mentions a limit or maximum is the account's sender limit: logged as an error, admins told to contact their administrator; any other 400 stays an error. `check` validates an inactive **or deleted** sender (FAILED only when the sender reads 404); after a `validate` answering 2xx, the sender read again decides: active, DKIM and SPF are checked; otherwise `DNSValidationError` (else `GlobalError`, never the file text) is shown, and a deleted sender left deleted with no error is logged as an error ("Mailjet didn't reactivate deleted sender …") and shown as "Mailjet didn't reactivate this domain's previous sender; contact your Showdesk administrator.". 200 and 201 are both accepted; error fields as a list are joined with "; ".

## Choices beyond the design

| # | Choice | Why |
|---|---|---|
| M1 | Credentials are the existing `MAILJET_API_KEY` / `MAILJET_SECRET_KEY` (Anymail's); one new setting `MAILJET_API_URL` (default `https://api.mailjet.com`). | The domains must be in the account that sends: the same keys. |
| M2 | The ref is the sender `ID` (digits only, checked before any URL). | Mailjet addresses a sender by its numeric id; `DELETE` takes it. |
| M3 | The DNS entry is found by `DNSID` when the sender has one, else by `GET /v3/REST/dns/{domain}`, else by scanning `GET /v3/REST/dns` for `Domain` (paged, bounded). An entry read whose `Domain` isn't the domain counts as not found. | A new sender is inactive, so `DNSID` is `-1` until validated, yet its records are needed to validate it. |
| M4 | Records shown: Mailjet's ownership TXT (`OwnerShipTokenRecordName` = `OwnerShipToken`), SPF TXT on the domain (`SPFRecordValue`, `merge`), DKIM TXT (`DKIMRecordName` = `DKIMRecordValue`). Names fully qualified. | What Mailjet checks; Showdesk's own `_showdesk` TXT is still added first by the services. |
| M5 | `check`: read the sender; `Deleted` → FAILED; `Inactive` → ask Mailjet to validate it (its errors kept); then `POST /dns/{id}/check`. VERIFIED only when the sender is `Active` and DKIM and SPF are `OK`; otherwise PENDING with Mailjet's error texts (trimmed, never containing credentials). HTTP or network errors → `SendingProviderError` (UNKNOWN). | Mailjet only sends from an active sender, and DKIM/SPF are what DMARC alignment needs. |
| M6 | `register` on a domain Mailjet already has: a 400 whose message says it exists → `AlreadyRegisteredError` (answered 409 like TEM's). | The services already distinguish a pending removal from a conflict. |
| M7 | `remove`: read the sender first; missing (404) or `Deleted` counts as removed, without a `DELETE`. Otherwise `DELETE /v3/REST/sender/{id}`; a 404, or a 400 after which the sender reads `Deleted`, counts as removed. | Idempotent removals. |

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
