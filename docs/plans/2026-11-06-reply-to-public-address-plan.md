# Reply-To Public Address Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan, with a review after the batch.

**Goal:** Like Zendesk, Freshdesk or Help Scout, a customer sees and replies to the organization's own address: a mailbox's reply mails carry `Reply-To: support@acme.com` instead of `reply+{token}@{INBOUND_EMAIL_DOMAIN}` once mail goes out from that address, its forwarding to the mailbox is proven, and an admin chose it.

**Why:** Decided by Dimitri on 2026-11-06. A reply-to address on Showdesk's domain looks foreign to customers, and leaves the organization's own mailbox out of the thread.

**Architecture:** `Mailbox.forwarding_verified_at`, stamped by the inbound pipeline when a processed mail came in through the mailbox's inbound address from an envelope sender on the public address's domain while naming the public address; `Mailbox.reply_to_public_address`, an admin's choice allowed by that proof. Both cleared when the public or inbound address changes. `outbound.reply_to(ticket)` picks the public address when `sendable_address(mailbox)` is truthy, the proof is there and the choice is on, else the reply token as today. Replies coming back through the forwarding thread by `In-Reply-To` / `References` on our stored Message-IDs and on the resolved / conversation-link mails' own ids, then `[SD-123]` from the contact (§4.3).

**Tech Stack:** Django 6.1, DRF, React 19 + TanStack Query, Vitest.

**Authoritative documents:** design `docs/plans/2026-10-29-email-channel-design.md` (§ numbers below refer to it), §4.1, §4.3, §5.1, §7, §10, §11 and Known limitations; `docs/plans/2026-11-04-sending-domains-plan.md` (working rules: binding).

**Branch:** `feat/reply-to-public-address` from `develop`, PR to `develop`.

---

## What the code says today

- `outbound.from_address(ticket)` takes the ticket's mailbox, or the organization's first active one, and sends from `sendable_address(mailbox)` or its inbound address. `outbound.reply_to(ticket)` is always `[reply_address(ticket)]` while `INBOUND_EMAIL_DOMAIN` is set. Both are used by the reply, unread-reply and resolved mails (`apps/tickets/tasks.py`) and the conversation-link mail (`apps/email_channel/tasks.py`).
- The pipeline (`pipeline.process`) knows the stored envelope recipient (`InboundEmail.envelope_recipient`) and the mailbox it resolved (`recipients.stored_recipient`); a mail is written in `_write`, which finishes it `processed`. Ignored, rejected, spam, auto-reply and bounce mail finish in `_triage` and never reach `_write`.
- `recipients.RECIPIENT_HEADERS` = `Delivered-To`, `X-Original-To`, `X-Forwarded-To`, `To`, `Cc`.
- A reply that comes back to the public address and is forwarded to the inbound address threads by `In-Reply-To` (our Message-IDs are stored in `external_id`), whatever its envelope.
- A public address changes through `Mailbox.save()` (API, Django admin) or `Mailbox.objects…update(public_address="")` in `sending.services.on_ownership_verified` (another organization verified the domain).

---

## Choices beyond the design

Each one is pinned by a test in the task named. Revised after review (2026-11-06): see "Review fixes".

| # | Choice | Why | Task |
|---|---|---|---|
| R1 | Forwarding is proven by a **processed** mail whose stored envelope recipient is the mailbox's inbound address, whose stored envelope sender is on the public address's domain (exact, case-insensitive), whose `RECIPIENT_HEADERS` name the mailbox's public address, and whose `To` / `Cc` don't name the inbound address. A mail stored without an envelope (`ingest_eml` without `--recipient`), with an empty envelope sender, delivered to a reply address or to the public address directly, or ignored / rejected (auto-reply, bounce, spam, loop, rate limit) proves nothing. | Headers are declarations; the envelope is what the provider delivered to. The domain's own server forwards from an envelope sender there (OVH `support+_redir+…@didouye.com`, Gmail / Workspace `…+caf_=…@domain`, Microsoft 365 SRS); a customer writing `To: support@…` doesn't. A mail addressed to both addresses reaches the inbound one directly. | 1 |
| R2 | Such a mail stamps `forwarding_verified_at` with its reception time (`received_at`), by a conditional update on the public address and the local part still being the ones it went through, skipped when the proof there is less than an hour older. | Admins see when forwarding last worked; a changed address doesn't inherit a proof; no write at each mail of a busy mailbox. | 1 |
| R3 | `reply_to_public_address` (default off) is set by admins with `PATCH /api/v1/mailboxes/{id}/`; turning it on is refused (400 on the field: "Forward {public address} to this mailbox first: a mail that came through it turns this on.") without a proof or while the mailbox doesn't send from its public address. The proof alone switches nothing. Replaces the `reset-forwarding` endpoint of the first version (review, 2026-11-06). | Someone can send to the inbound address with a forged envelope sender on the organization's domain and refresh the proof; only an admin turns the choice on. | Review |
| R4 | Proof and choice are cleared together when the public address changes or is cleared (`Mailbox.save()` compares with the database value when `public_address` is written; no `from_db` override, which Django 6.1's `fetch_mode` outgrew), where `on_ownership_verified` frees other organizations' addresses, and when the inbound address is regenerated. `forwarding_verified_at` is read-only in the Django admin. | A proof is about one address forwarded to one inbound address. | 1 |
| R5 | `Reply-To` is the public address iff `INBOUND_EMAIL_DOMAIN` is set, `sendable_address(mailbox)` is truthy, `forwarding_verified_at` is set and `reply_to_public_address` is on, for the same mailbox the `From` is taken from. Decided at send time, as the From (§11 choice 10). The reply marker stays, and reply addresses keep working. | One rule for the four mails using `outbound.reply_to`; nothing in flight breaks when a mailbox switches. | 1 |
| R6 | `tokens.ticket_id_from_message_id` parses our `<resolved-{ticket}-{stamp}@…>` and `<link-{ticket}-{task id}@…>` ids (on `_outbound_domain()`); `_by_headers` takes their ticket, within the organization, in reference order. The conversation-link mail gets such a Message-ID (the task id: the same on a retry) and the ticket's threading headers. | Parsed rather than stored on a system message: these mails send no message, and parsing needs no write. | Review |
| R7 | Frontend: when the mailbox sends from its public address, "Customers reply to support@acme.com (forwarding confirmed …)" + admin "Use Showdesk's reply address instead" (confirmed); proof without choice: "Customers reply to a Showdesk reply address." + the date + admin "Have customers reply to support@acme.com"; no proof: "Customers reply to a Showdesk reply address. Forward support@acme.com to {inbound address} to let them reply to it." Agents: text only. | The admin sees the date of the last forward whichever way the choice is. | Review |

## Task 1: backend

**Files:**
- Modify: `backend/apps/email_channel/models.py` (`forwarding_verified_at`, cleared in `save()`), `recipients.py` (`proves_forwarding(inbound, message, mailbox)`), `pipeline.py` (`_write` stamps the proof), `outbound.py` (one mailbox for From and Reply-To; `reply_to` rule), `serializers.py` (read-only field), `views.py` (`reset-forwarding`), `sending/services.py` (`on_ownership_verified` clears the proof with the address)
- Create: `backend/apps/email_channel/migrations/0006_mailbox_forwarding_verified_at.py`
- Test: `backend/tests/email_channel/test_pipeline.py`, `test_outbound.py`, `test_mailbox_api.py`, `test_sending_services.py`

**Steps (TDD):**
1. Failing tests, few and distinct:
   - pipeline: a mail forwarded from the public address stamps the proof; an agent's reply then carries `Reply-To: <public address>`; the customer's reply, forwarded back with `In-Reply-To` of that reply's Message-ID, lands on the same ticket.
   - pipeline: no proof from an auto-reply, a mail to a reply address, a mail naming the inbound address in `To` with the public one in `Cc`, a mail not naming the public address, or a mail stored without an envelope.
   - outbound: the reply token while the proof is missing or mail isn't sent from the public address; the public address with both, on the reply and resolved mails.
   - API: `forwarding_verified_at` read-only; a changed public address clears it; `reset-forwarding` clears it, 403 for agents, 404 in another organization.
   - services: freeing a public address on another organization's verification clears its proof.
2. Run, watch them fail. 3. Implement, `makemigrations`. 4. Whole backend suite, ruff, `makemigrations --check`. 5. Commit `feat(backend): let customers reply to the public address once forwarding is proven`.

## Task 2: frontend

**Files:**
- Modify: `frontend/src/types/index.ts` (`forwarding_verified_at: string | null`), `frontend/src/api/mailboxes.ts` (`resetMailboxForwarding`), `frontend/src/hooks/useMailboxes.ts` (`useResetMailboxForwarding`), `frontend/src/components/settings/MailboxesTab.tsx`
- Test: `frontend/src/components/settings/__tests__/MailboxesTab.test.tsx`

**Steps (TDD):**
1. Failing test: under "Replies are sent from …", "Customers reply to support@acme.com" with the date of the last proof and, for admins, "Reset" (posts `reset-forwarding`, confirmed first); "Customers reply to a reply address of Showdesk (forward support@acme.com here to have them reply to it)" when sending from the public address without proof; nothing when sending from the inbound address.
2. Run, watch it fail. 3. Implement. 4. `npm run lint && npm test && npm run build`. 5. Commit `feat(frontend): show where customers reply, and let admins reset it`.

## Task 3: docs

- Design §5.1 (`Reply-To` rule), §11 (choices R1–R6 and the API), Known limitations (broken forwarding).
- Commit `docs: reply-to public address in the email channel design`.

## Review fixes (2026-11-06)

Decided after review; the branch being unmerged, migration 0006 is edited in place.

1. `feat(backend): let admins choose to have customers reply to the public address`: `reply_to_public_address` and its serializer check (R3), the envelope-sender domain check and the stamp's `received_at` / `local_part` / hour (R1, R2), clearing in `save()` against the database (R4), `reset-forwarding` removed, the proof read-only in the Django admin.
2. `fix(backend): thread replies to the resolved and conversation-link mails` (R6).
3. `feat(frontend): let admins choose whether customers reply to the public address` (R7).
4. `docs: …` (design §4.3, §5.1, §11 reply-to block, Known limitations; this plan).
