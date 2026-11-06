# Reply-To Public Address Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan, with a review after the batch.

**Goal:** Like Zendesk, Freshdesk or Help Scout, a customer sees and replies to the organization's own address: a mailbox's reply mails carry `Reply-To: support@acme.com` instead of `reply+{token}@{INBOUND_EMAIL_DOMAIN}` once mail goes out from that address and its forwarding to the mailbox is proven.

**Why:** Decided by Dimitri on 2026-11-06. A reply-to address on Showdesk's domain looks foreign to customers, and leaves the organization's own mailbox out of the thread.

**Architecture:** `Mailbox.forwarding_verified_at`, stamped by the inbound pipeline when a processed mail came in through the mailbox's inbound address while naming its public address, and cleared when the public address changes. `outbound.reply_to(ticket)` picks the public address when `sendable_address(mailbox)` is truthy and the proof is there, else the reply token as today. Threading of the replies that come back through the forwarding is unchanged: `In-Reply-To` / `References` on our stored Message-IDs, then `[SD-123]` from the contact (§4.3).

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

Each one is pinned by a test in the task named.

| # | Choice | Why | Task |
|---|---|---|---|
| R1 | Forwarding is proven by a **processed** mail whose stored envelope recipient is the mailbox's inbound address, whose `RECIPIENT_HEADERS` name the mailbox's public address, and whose `To` / `Cc` don't name the inbound address. A mail stored without an envelope (`ingest_eml` without `--recipient`), delivered to a reply address or to the public address directly, or ignored / rejected (auto-reply, bounce, spam, loop, rate limit) proves nothing. | Headers are declarations; the envelope is what the provider delivered to. A mail addressed to both addresses reaches the inbound one directly, forwarding or not. That is the evidence Gmail forwarding gives. | 1 |
| R2 | Every such mail stamps `forwarding_verified_at` with its processing time (the date of the last proof), by a conditional update on the public address still being the one the mail named. | Admins see when forwarding last worked; a public address changed meanwhile doesn't inherit a proof of the previous one. | 1 |
| R3 | `forwarding_verified_at` is cleared whenever the public address changes: in `Mailbox.save()` (against the value loaded from the database), and where `on_ownership_verified` frees other organizations' addresses. Also when the inbound address is regenerated (found while implementing: forwarding to the previous one is refused from then on). Admins clear it with `POST /api/v1/mailboxes/{id}/reset-forwarding/`. | A proof is about one address forwarded to one inbound address. Resetting is how admins stop replies going to an address whose forwarding they broke. | 1 |
| R4 | `Reply-To` is the public address iff `INBOUND_EMAIL_DOMAIN` is set, `sendable_address(mailbox)` is truthy and `forwarding_verified_at` is set, for the same mailbox the `From` is taken from. Decided at send time, as the From (§11 choice 10). The reply marker stays. | Replying to an address we don't send from would look odd, and one we can't receive from would lose the reply. One rule for the four mails using `outbound.reply_to`. | 1 |
| R5 | The API gives `forwarding_verified_at` read-only to every staff member; the frontend derives "customers reply to the public address" from `sends_from_public_address && forwarding_verified_at`. No other field. | The rule is those two facts; one more field would only repeat them. | 1, 2 |
| R6 | Reply addresses keep working: mail already sent with one, and mailboxes without proof, still come back through it. | Nothing in flight breaks when a mailbox switches. | 1 |

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
