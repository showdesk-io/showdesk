"""The requester's mail of an agent's reply: when it goes, and what it carries (§5).

A reply reaches a requester who has the widget open there first, and by mail only
if it's still unread after ``WIDGET_UNREAD_EMAIL_DELAY_MINUTES``. That mail groups
every unread reply.
"""

import enum
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.db.models import Q

from apps.email_channel import presence
from apps.email_channel.content import REPLY_MARKER
from apps.email_channel.models import Mailbox
from apps.email_channel.tokens import conversation_token, reply_address
from apps.tickets.models import Ticket, TicketMessage, WidgetSession

# Enough for a mail client to thread on, and a bound on the headers of a long one.
MAX_REFERENCES = 20
# What a reply mail recalls of the conversation before its new replies.
CONTEXT_MESSAGES = 3


class Delivery(enum.StrEnum):
    """When a reply is emailed to its requester."""

    NOW = "now"
    LATER = "later"  # Unless read in the widget first.
    NEVER = "never"


def entitled_session_ids(ticket) -> list[str]:
    """The widget sessions where ``ticket``'s replies show: the one that opened it."""
    return [
        str(session_id)
        for session_id in WidgetSession.objects.filter(
            Q(pk=ticket.widget_session_id)
        ).values_list("id", flat=True)
    ]


def suppressed_by_unsubscribe(ticket) -> bool:
    """Tell if the contact unsubscribed, on a ticket they didn't open by email.

    Mail is the channel they chose for a ticket they opened by email: its replies
    still go there. Those of any other ticket wait in the widget.
    """
    contact = ticket.contact
    return bool(
        contact and contact.is_unsubscribed and ticket.source != Ticket.Source.EMAIL
    )


def delivery_decision(message) -> Delivery:
    """When an agent's ``message`` is emailed to the requester (§5.2)."""
    if message.message_type == TicketMessage.MessageType.INTERNAL_NOTE:
        return Delivery.NEVER
    ticket = message.ticket
    if suppressed_by_unsubscribe(ticket):
        return Delivery.NEVER
    last = (
        ticket.messages.filter(
            sender_type=TicketMessage.SenderType.USER,
            created_at__lte=message.created_at,
        )
        .order_by("-created_at")
        .first()
    )
    if last is not None and last.channel == TicketMessage.Channel.EMAIL:
        return Delivery.NOW
    if not any(presence.is_connected(s) for s in entitled_session_ids(ticket)):
        return Delivery.NOW
    return Delivery.LATER


def queue_reply_email(message) -> None:
    """Email an agent's ``message`` now, after the delay, or not at all."""
    from apps.tickets.tasks import send_ticket_reply_email, send_unread_reply_email

    decision = delivery_decision(message)
    if decision == Delivery.NOW:
        send_ticket_reply_email.delay(str(message.id))
    elif decision == Delivery.LATER:
        send_unread_reply_email.apply_async(
            args=[str(message.id)],
            countdown=settings.WIDGET_UNREAD_EMAIL_DELAY_MINUTES * 60,
        )


def superseded(message) -> bool:
    """Tell if a later reply of an agent's will email ``message`` with it."""
    return message.ticket.messages.filter(
        sender_type=TicketMessage.SenderType.AGENT,
        message_type=TicketMessage.MessageType.REPLY,
        created_at__gt=message.created_at,
    ).exists()


def read_in_widget(message) -> bool:
    """Tell if the requester saw ``message`` in the widget."""
    read_at = message.ticket.widget_last_read_at
    return read_at is not None and read_at >= message.created_at


def unread_replies(message) -> list[TicketMessage]:
    """The agents' replies a mail of ``message`` carries, ``message`` last.

    Those since the requester last read the widget, wrote, or was emailed one.
    """
    ticket = message.ticket
    earlier = ticket.messages.filter(created_at__lt=message.created_at)
    marks = [
        ticket.widget_last_read_at,
        earlier.filter(sender_type=TicketMessage.SenderType.USER)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first(),
        earlier.filter(email_delivery_status=TicketMessage.DeliveryStatus.SENT)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first(),
    ]
    since = max((mark for mark in marks if mark is not None), default=None)
    replies = earlier.filter(
        sender_type=TicketMessage.SenderType.AGENT,
        message_type=TicketMessage.MessageType.REPLY,
    )
    if since is not None:
        replies = replies.filter(created_at__gt=since)
    return [
        *replies.select_related("author").prefetch_related("attachments")
        .order_by("created_at"),
        message,
    ]  # fmt: skip


def context_messages(first) -> list[TicketMessage]:
    """The last public messages before ``first``, oldest first."""
    messages = (
        first.ticket.messages.filter(
            created_at__lt=first.created_at,
            message_type=TicketMessage.MessageType.REPLY,
        )
        .exclude(sender_type=TicketMessage.SenderType.SYSTEM)
        .select_related("author")
        .order_by("-created_at")[:CONTEXT_MESSAGES]
    )
    return list(reversed(messages))


def from_address(ticket) -> str | None:
    """The ``From`` of the ticket's mail, None for ``DEFAULT_FROM_EMAIL`` (§5.1).

    The ticket's mailbox, or else the organization's first active one, while the
    inbound domain is set.
    """
    if not settings.INBOUND_EMAIL_DOMAIN:
        return None
    mailbox = ticket.mailbox if ticket.mailbox_id else None
    if mailbox is None or not mailbox.is_active:
        mailbox = (
            Mailbox.objects.filter(
                organization_id=ticket.organization_id, is_active=True
            )
            .order_by("created_at")
            .first()
        )
    if mailbox is None:
        return None
    organization = ticket.organization
    return formataddr(
        (organization.email_from_name or organization.name, mailbox.inbound_address)
    )


def reply_to(ticket) -> list[str] | None:
    """Where a reply to the ticket's mail goes, while the inbound domain is set."""
    return [reply_address(ticket)] if settings.INBOUND_EMAIL_DOMAIN else None


def reply_marker() -> str:
    """The line a reply is written above, if replies come back to us."""
    return REPLY_MARKER if settings.INBOUND_EMAIL_DOMAIN else ""


def threading_headers(message) -> dict[str, str]:
    """``In-Reply-To`` and ``References`` on the ticket's mails before ``message``.

    At most ``MAX_REFERENCES`` ids: the thread's first, and the latest.
    """
    ids = [
        message_id
        for message_id in message.ticket.messages.filter(
            created_at__lt=message.created_at
        )
        .exclude(external_id="")
        .order_by("created_at")
        .values_list("external_id", flat=True)
        if message_id.startswith("<") and message_id.endswith(">")
    ]
    if not ids:
        return {}
    if len(ids) > MAX_REFERENCES:
        ids = ids[:1] + ids[-(MAX_REFERENCES - 1) :]
    return {"In-Reply-To": ids[-1], "References": " ".join(ids)}


def conversation_url(ticket, address: str) -> str:
    """A link to the ticket's conversation, mailed to ``address``; "" without a contact."""
    contact = ticket.contact
    if contact is None or contact.is_anonymized:
        return ""
    token = conversation_token(ticket, contact, address)
    return f"{settings.SITE_URL.rstrip('/')}/c/{token}"


def sender_label(message) -> str:
    """Who wrote ``message``, as the requester reads it."""
    if message.sender_type == TicketMessage.SenderType.USER:
        return parseaddr(message.external_sender)[0] or "You"
    author = message.author
    if author is None:
        return "Support"
    return (author.first_name or "").strip() or (
        author.email.split("@")[0] if author.email else "Support"
    )
