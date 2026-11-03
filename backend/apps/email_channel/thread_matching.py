"""Which ticket an inbound mail continues, if any (design §4.3).

A mail's headers and subject are written by its sender. A match only adds a message
to a ticket of the organization the mail was delivered to; it never shows a ticket
to anyone.
"""

import enum
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Case, Value, When
from django.utils import timezone

from apps.email_channel.recipients import Recipient, one_line
from apps.tickets.models import Ticket, TicketMessage

_MESSAGE_ID = re.compile(r"<[^<>\s]{1,253}>")
# Enough for any thread we take part in, and a bound on what one mail looks up.
_MAX_REFERENCES = 20
_REFERENCE_IN_SUBJECT = re.compile(r"\[([A-Z][A-Z0-9]{0,9}-\d{1,10})\]")
_FORWARD = re.compile(r"^\s*(?:fwd?|tr|wg)\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class Match:
    """The ticket a mail continues, and what told: headers, reply_address, subject."""

    ticket: Ticket
    by: str


class ReopenOutcome(enum.StrEnum):
    """What a matched ticket does with a new mail."""

    OPEN = "open"  # Not closed: it takes the mail.
    REOPENED = "reopened"  # Closed recently: reopened, it takes the mail.
    EXPIRED = "expired"  # Closed for longer: a new ticket takes the mail.


def is_forward(subject: str) -> bool:
    """Tell if a subject is a forward's (Fwd:, Fw:, TR:, WG:), not a reply to one."""
    return bool(_FORWARD.match(one_line(subject)))


def _referenced_ids(message) -> list[str]:
    """In-Reply-To first, then References from the most recent."""
    ids = _MESSAGE_ID.findall(one_line(message.get("In-Reply-To")))
    ids += reversed(_MESSAGE_ID.findall(one_line(message.get("References"))))
    unique = []
    for message_id in ids:
        if message_id not in unique:
            unique.append(message_id)
    return unique[:_MAX_REFERENCES]


def _continuable(organization):
    # An anonymized contact's ticket takes nothing more: what came in would be
    # personal data on a ticket that was erased.
    return Ticket.objects.filter(organization=organization).exclude(
        contact__is_anonymized=True
    )


def _by_headers(message, organization) -> Ticket | None:
    """The ticket of the first id referenced, in the order of ``_referenced_ids``.

    An id on several tickets (a customer can reuse one of ours as their own
    Message-ID) goes to the ticket of our own message, then of the oldest.
    """
    ids = _referenced_ids(message)
    if not ids:
        return None
    candidates = (
        TicketMessage.objects.filter(
            external_id__in=ids, ticket__in=_continuable(organization)
        )
        .annotate(
            from_user=Case(
                When(sender_type=TicketMessage.SenderType.USER, then=Value(1)),
                default=Value(0),
            )
        )
        .order_by("from_user", "created_at", "id")
        .values_list("external_id", "ticket_id")
    )
    found = {}
    for message_id, ticket_id in candidates:
        found.setdefault(message_id, ticket_id)
    for message_id in ids:
        if message_id in found:
            return _continuable(organization).get(pk=found[message_id])
    return None


def _by_reply_address(recipient: Recipient, organization) -> Ticket | None:
    if recipient.ticket is None:
        return None
    return _continuable(organization).filter(pk=recipient.ticket.pk).first()


def _by_subject(message, sender: str, organization) -> Ticket | None:
    match = _REFERENCE_IN_SUBJECT.search(one_line(message.get("Subject")))
    if not match or not sender:
        return None
    # Anyone can write a reference: only the ticket's own contact continues it so.
    return (
        _continuable(organization)
        .filter(contact__email=sender.lower(), reference=match.group(1))
        .first()
    )


def find_ticket(
    message, recipient: Recipient, sender: str, organization
) -> Match | None:
    """Find the ticket of ``organization`` that ``message`` continues, or None.

    In this order: a Message-ID of one of its messages in In-Reply-To or References,
    the reply address it was delivered to, then ``[SD-123]`` in the subject when
    ``sender`` is the ticket's contact. A forward only continues by its headers.
    """
    if ticket := _by_headers(message, organization):
        return Match(ticket, "headers")
    if is_forward(message.get("Subject")):
        return None
    if ticket := _by_reply_address(recipient, organization):
        return Match(ticket, "reply_address")
    if ticket := _by_subject(message, sender, organization):
        return Match(ticket, "subject")
    return None


def lock_matched_ticket(match: Match, organization) -> Ticket | None:
    """Lock the matched ticket, or None if it can't take the mail anymore.

    Its contact may have been anonymized since it was found: under the lock, that
    is current.
    """
    return (
        _continuable(organization)
        .select_for_update(of=("self",))
        .filter(pk=match.ticket.pk)
        .first()
    )


def apply_reopen_rule(ticket: Ticket) -> ReopenOutcome:
    """Reopen ``ticket`` for a new mail if it was closed recently.

    Within ``INBOUND_EMAIL_REOPEN_DAYS`` of being resolved or closed, it reopens as
    an agent's reopen does. Past that, it stays as it is: the mail opens a new
    ticket naming it under ``gdpr.PREVIOUS_TICKET_KEY``.
    """
    if ticket.status not in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
        return ReopenOutcome.OPEN
    ended = max(
        (date for date in (ticket.resolved_at, ticket.closed_at) if date),
        default=ticket.updated_at,
    )
    if timezone.now() - ended > timedelta(days=settings.INBOUND_EMAIL_REOPEN_DAYS):
        return ReopenOutcome.EXPIRED
    ticket.status = Ticket.Status.OPEN
    ticket.resolved_at = None
    ticket.closed_at = None
    ticket.save(update_fields=["status", "resolved_at", "closed_at", "updated_at"])
    return ReopenOutcome.REOPENED
