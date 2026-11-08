# Postal Sending Domain Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan, with a review after the batch.

**Goal:** A fifth `SENDING_DOMAIN_PROVIDER`, `postal`, registers an organization's domain in one server of a self-hosted Postal (v3), shows the records Postal signs and bounces with, and checks them, so that Showdesk instances sending through their own Postal can send from their customers' domains. The instance's own mail can go out through that Postal too (Anymail's Postal backend).

**Why:** For operators who run Postal rather than a hosted service. `manual` already works with Postal, but needs one DKIM key for every customer domain (a "use for any" domain, or a key copied by hand); with `postal`, each domain gets its own key, created by Postal, and Postal signs with it.

**Architecture:** Postal has no API to manage domains (its API only sends and reads messages), so a tiny HTTP service, `deploy/postal-domains/`, runs on the Postal host and manages the domains of one Postal server through Postal's own models (`rails runner` in Postal's web container, a Ruby script on stdin, JSON out). Showdesk's `backend/apps/email_channel/sending/postal.py` (`register`, `check`, `remove`, `removal_needed = True`) calls it, and checks the records in the DNS itself like `manual`. Everything else (ownership TXT, transitions, removals, beat, wizard) is provider-agnostic and unchanged.

**Tech Stack:** Python stdlib (`http.server`, `subprocess`) for the service, Ruby (Postal's Rails 7.1 app) for its script, `requests` and dnspython on Showdesk's side, Anymail's Postal backend.

**Authoritative documents:** `docs/plans/2026-11-04-sending-domains-plan.md` (choices, working rules: binding), design `docs/plans/2026-10-29-email-channel-design.md` §7, §8 and §11.

**Branch:** `feat/postal-sending-provider` from `develop`, PR to `develop`.

---

## What Postal's source says (postalserver/postal, release 3.3.7, and `main` at d96eddb, 2026-11-08)

- `app/models/domain.rb`: a `Domain` belongs to a polymorphic `owner` (an `Organization` or a `Server`: `Server has_many :domains, as: :owner`); `name` must match `/\A[a-z0-9\-.]*\z/` and is unique per owner; `uuid` (`HasUUID`, `random_string :uuid, type: :uuid`) is the id the UI uses (`to_param`); `verification_method` must be `DNS` or `Email`; `verified_at` (`verified?`, scope `verified`); `outgoing`, `incoming` (default true); `before_create :generate_dkim_key` (RSA 1024 in 3.3.7, `dns.dkim_key_size`, default 2048, on `main`); `dkim_identifier_string`, 6 random upper-case letters.
  - `dkim_record_name` = `"#{dns.dkim_identifier}-#{dkim_identifier_string}._domainkey"` (relative to the domain; `dns.dkim_identifier` defaults to `postal`).
  - `dkim_record` = `"v=DKIM1; t=s; h=sha256; p=#{public key, base64, one line};"`.
  - `spf_record` = `"v=spf1 a mx include:#{dns.spf_include} ~all"`.
  - `return_path_domain` = `"#{dns.custom_return_path_prefix}.#{name}"` (prefix default `psrp`), to be a CNAME to `dns.return_path_domain`.
  - `main` adds a pending DKIM key (rotation from the UI): the active key stays `dkim_record`.
- `app/models/concerns/has_dns_checks.rb`: `check_dns(source)` checks SPF (a `v=spf1` TXT at the domain matching `include:\s*<spf_include>`), DKIM (exactly one TXT at `<dkim_record_name>.<name>`, equal to `dkim_record` once a trailing `;` is added), MX, and the return path (one CNAME equal to `dns.return_path_domain`), storing `spf_status`, `dkim_status`, `mx_status`, `return_path_status` (`OK`, `Missing`, `Invalid`) with their `*_error` texts and `dns_checked_at`. `dns_ok?` accepts a `Missing` MX and return path.
- `app/scheduled_tasks/check_all_dns_scheduled_task.rb`: Postal re-checks every hour the domains whose `dns_checked_at` is set, and only those: a domain never checked is never checked by Postal.
- `app/lib/dkim_header.rb`: a message is signed with its domain's key **only when that domain's `dkim_status` is `OK`**; otherwise with Postal's own key, as `dns.return_path_domain` (not aligned with the From: DMARC fails on the customer's domain).
- `app/senders/smtp_sender.rb`: the envelope sender (MAIL FROM) is `<server token>@<return_path_domain of the domain>` only when its `return_path_status` is `OK`, else on `dns.return_path_domain`.
- `app/models/server.rb` `authenticated_domain_for_address`: a From (or Sender, if allowed) is accepted when its domain is a **verified** domain of the server or of the server's organization (the server's first), or else when the server has a verified `use_for_any` domain. `outgoing_message_prototype.rb` (HTTP API) answers `UnauthenticatedFromAddress` otherwise; `smtp_server/client.rb` answers `530 From/Sender name is not valid`. `outgoing` isn't looked at.
- `app/controllers/domains_controller.rb`: the UI creates a domain under `organization.servers.present.find_by_permalink!(…)` (or the organization), and a Postal admin's domain is created already verified (`verification_method = "DNS"`, `verified_at = Time.now`); `destroy` deletes it (`has_many :routes, dependent: :destroy`).
- Servers and organizations are soft-deleted (`HasSoftDestroy`, scope `present`); a server's `permalink` is unique within its organization only (`[a-z0-9-]`).
- `lib/postal/config_schema.rb` `dns.*`: `spf_include` (`spf.postal.example.com`), `return_path_domain` (`rp.postal.example.com`), `custom_return_path_prefix` (`psrp`), `dkim_identifier` (`postal`), `domain_verify_prefix`, `timeout` (5 s); `postal.use_local_ns_for_domain_verification` (default false: Postal asks the domain's own nameservers).
- Postal's image (`Dockerfile`): `WORKDIR /opt/postal/app`, `USER postal`, Rails 7.1.6, `POSTAL_CONFIG_FILE_PATH=/config/postal.yml`. postalserver/install runs it with `docker compose -p postal` (containers `postal-web-1`, `postal-worker-1`, …, host network). `rails runner -` evaluates stdin, the arguments after `-` being `ARGV` (railties 7.1 `runner_command.rb`).
- Anymail's `anymail.backends.postal.EmailBackend` sends with `ANYMAIL["POSTAL_API_URL"]` (required) and `ANYMAIL["POSTAL_API_KEY"]` (an API credential of a server, sent as `X-Server-API-Key`) to `api/v1/send/message`.

## Choices beyond the design

| # | Choice | Why |
|---|---|---|
| P1 | The domains are managed by a separate service on the Postal host (`deploy/postal-domains/`), not by Showdesk talking to Postal's database. It runs `docker exec -i <web container> bundle exec rails runner - <action> <organization> <server> <arg>` with `postal_domains.rb` on stdin, which prints one `SHOWDESK_RESULT <json>` line. One Rails boot per call (a few seconds): calls are rare (setup, a check every 15 min while pending, daily once verified). At most 2 run at once; a third waits up to the timeout, then 503. | Postal's models create the DKIM key, the uuid and the identifier exactly as its UI does, across versions; its MariaDB stays private to the host; no Ruby or Postal code in Showdesk. |
| P2 | The service is bound to one Postal server, `POSTAL_DOMAINS_ORGANIZATION` / `POSTAL_DOMAINS_SERVER` (permalinks, present ones only), and only reads and writes that server's domains. | The domains must belong to the server Showdesk sends with, and nothing else of Postal's must be reachable from Showdesk. |
| P3 | API, all with `Authorization: Bearer <POSTAL_DOMAINS_TOKEN>` (compared with `hmac.compare_digest`; at least 32 characters, or the service refuses to start): `POST /domains {"name"}` → 201 created, 200 existing (idempotent); `GET /domains/{uuid}` → the stored state; `POST /domains/{uuid}/check` → runs Postal's `check_dns(:manual)`, then the state; `DELETE /domains/{uuid}` → 204; an unknown uuid → 404. State: `{"id", "name", "records": [{"kind": "dkim"|"spf"|"return_path", "type", "name", "value"}], "status": {"checked_at", "dkim", "dkim_error", "spf", "spf_error", "return_path", "return_path_error"}}`. Errors are `{"error": code}` (400 `invalid_name`/`invalid_body`, 401, 404 `not_found`, 422 `rejected` with Postal's validation text, 502 `postal_failed`, 503 `busy`). | `check` changes Postal's state, so it is a POST; Showdesk's check must run it (P7). |
| P4 | A domain is created on the server, `outgoing: true`, `incoming: false`, `verification_method: "DNS"`, `verified_at: now`, as Postal's UI does for an admin. | Postal only accepts a From on a verified domain; Showdesk proved the ownership itself (`_showdesk` TXT, checked at every check, §11 choice 14), so Postal's own verification TXT would be one more record for nothing. Showdesk receives the mail elsewhere. |
| P5 | Inputs are checked by the service before any command: the name by Showdesk's own domain rule (labels of 1-63 `[a-z0-9-]`, no hyphen at either end, at least two, a non-numeric last one, 253 characters at most), the uuid by `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`, the permalinks by `^[a-z0-9-]{1,64}$`; a body of at most 4 KB. The command is an argv list (never a shell), with a timeout (`POSTAL_DOMAINS_TIMEOUT`, 45 s), killed on expiry (502). The Ruby script checks them again. Postal's output and errors are logged, never returned but for a validation text. | A domain name ends up as an argument of a command run as Postal: nothing unchecked may reach it. |
| P6 | Records shown, fully qualified, in the order SPF, DKIM, return path: the SPF TXT on the domain `v=spf1 include:<dns.spf_include> ~all` (`merge`, Postal's `a mx` dropped: the customer's own hosts don't send for Showdesk), the domain's DKIM TXT at `<dkim_record_name>.<domain>`, the return-path CNAME `psrp.<domain>` → `dns.return_path_domain` (left out if the prefix is empty). | What Postal checks and signs with, and the CNAME that aligns its envelope sender (SPF) and brings bounces back under the customer's domain. Postal's MX is never shown: the domain receives its mail elsewhere. |
| P7 | `check(ref)`: `POST /domains/{ref}/check` (the service's 404 `{"error": "not_found"}` → FAILED, "The sending service no longer has this domain."; any other 404, a proxy's, is an error: UNKNOWN), then Showdesk's own DNS (`lookup_txt`): the DKIM name must hold exactly one TXT equal to the expected value (whitespace and a trailing `;` ignored), the domain exactly one SPF record including `include:<spf include>` before its `all`. A lookup that can't conclude → UNKNOWN. Then Postal's statuses: `dkim` and `return_path` must be `OK`. Anything missing → PENDING with every reason ("DKIM: …", "SPF: …", "Return path: <Postal's error>"). VERIFIED only when all hold. The records read from the service come back with the check. | Showdesk's own lookup gives the same answers and errors as `manual`; Postal's statuses are what makes it sign with the domain's key and use its return path (and they start its hourly re-check, which needs a first check). Showdesk can't read a CNAME itself (`lookup_txt` only), so the return path is Postal's word. |
| P8 | `register(domain)`: `POST /domains`; 200 and 201 alike; ref = the uuid (checked by the same regex before any URL); records as in P6. A domain the server already has is taken over (idempotent). | A registration made but not stored (§11 choice 5) is retried without a conflict. The server is meant for Showdesk's customer domains only (README): the instance's own domains are refused by the services anyway (`operator_domain`). |
| P9 | `remove(ref)`: `DELETE /domains/{ref}`; 204, or the service's own 404 (`not_found`) → removed; any other 404 is an error and the removal is retried. | Idempotent removals; a misrouted proxy must neither fail every domain nor drop removals. |
| P10 | Settings `POSTAL_DOMAINS_API_URL` (e.g. `https://postal.example.com/showdesk-domains`) and `POSTAL_DOMAINS_API_TOKEN`, empty by default; `get_provider()` with `postal` and either missing → ImproperlyConfigured. Timeout 60 s per call. HTTP or network failures → `SendingProviderError` showing admins the status only; the token is never logged nor shown. | Same shape as `scaleway_tem` and `mailjet`. A Rails boot plus Postal's DNS check stays well under it, and under gunicorn's 120 s for enabling (a register and a check). |
| P11 | The instance's own mail through Postal: `ANYMAIL_POSTAL_API_URL` / `ANYMAIL_POSTAL_API_KEY` fill `ANYMAIL["POSTAL_API_URL"]` / `ANYMAIL["POSTAL_API_KEY"]` only when set; used with `EMAIL_BACKEND=anymail.backends.postal.EmailBackend`. The key is an API credential of the same server. | No behaviour change unless set; Postal only lets a server send from its own (or its organization's) verified domains, so customers' domains and the instance's must be in that server. |
| P12 | The service runs either as a compose service next to Postal (an image from `deploy/postal-domains/Dockerfile`, host network, the Docker socket mounted) or as a systemd unit; it listens on `127.0.0.1:8089` and is reached through the host's reverse proxy (`handle_path /showdesk-domains/* { reverse_proxy 127.0.0.1:8089 }`). | Postal's install already has a Caddy in front of it; the service is never exposed by itself. |

Known limitations, added to the design: the service has the Docker socket (root on the host): it is the operator's to run; a DKIM key rotated in Postal's UI changes the record customers must publish, and their domains go back to pending until they do; Postal's answers were read from its source, not yet observed on a real Postal.

## Working rules

Those of `docs/plans/2026-11-04-sending-domains-plan.md`. Here: only the HTTP boundary (`requests.request` as `postal.py` calls it) and `dns_verification.lookup_txt` are mocked on Showdesk's side; in the service, only `subprocess.run`. The service's tests run with `cd deploy/postal-domains && python -m pytest -q -p no:django`, and its code is linted with ruff like the backend's (CI too).

## Task 1: the domains service

**Files:**
- Create: `deploy/postal-domains/postal_domains.py`, `postal_domains.rb`, `test_postal_domains.py`, `Dockerfile`, `README.md`
- Modify: `.github/workflows/ci.yml` (ruff and tests on `deploy/postal-domains`)

**Steps (TDD):**
1. Failing tests, few and distinct: a request without or with a wrong token → 401 and no command; `POST /domains` with an invalid name → 400 and no command; a valid one → the exact argv (no shell) with the script on stdin, 201 and the state parsed from the `SHOWDESK_RESULT` line among Postal's log lines; an existing one → 200; `DELETE` of an unknown uuid → 404; a non-uuid path → 404 and no command; a timeout → 502.
2. Run, watch them fail. 3. Implement. 4. Run, ruff. 5. Commit `feat(deploy): Postal domains service`.

## Task 2: `postal` provider and Anymail settings

**Files:**
- Create: `backend/apps/email_channel/sending/postal.py`
- Modify: `providers.py` (`provider_class`, docstring, error message), `backend/config/settings/base.py`, `.env.example`, `docker-compose.prod.yml`
- Test: `backend/tests/email_channel/test_sending_providers.py`

**Steps (TDD):**
1. Failing tests: register posts the name with the bearer token, ref = uuid, records SPF (`merge`), DKIM, return path; check VERIFIED with the records published and Postal's statuses OK; PENDING naming a wrong DKIM, a missing SPF include and Postal's return-path error; UNKNOWN when a lookup can't conclude; FAILED on 404; the service unreachable → `SendingProviderError` without the token; a non-uuid ref refused before any call; remove tolerates 404; `get_provider()` without the settings → ImproperlyConfigured; the Anymail Postal keys only when set.
2. Run, watch them fail. 3. Implement. 4. Whole suite, ruff, migrations check. 5. Commit `feat(backend): Postal sending domain provider`.

## Task 3: docs

- `.env.example`: `postal` in the provider list; a paragraph on the service, the token, the server, that the instance's own From domains (`DEFAULT_FROM_EMAIL`'s, `INBOUND_EMAIL_DOMAIN`) must be verified domains of that server too, with their SPF, DKIM and return path published, and the host's PTR, SPF and DKIM; the Anymail Postal keys.
- Design §7.2 (adapter list), §8 (variables), §11 (a row for `postal`, operators' settings), Known limitations.
- Commit `docs: Postal sending domain provider`.

**Batch review**, fixes, PR, CI, merge, dev deploy. Real validation needs a Postal server and the service on its host (Dimitri).
