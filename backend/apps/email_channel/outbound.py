"""The requester's mail of an agent's reply: when it goes, and what it carries (§5).

A reply reaches a requester who has the widget open there first, and by mail only
if it's still unread after ``WIDGET_UNREAD_EMAIL_DELAY_MINUTES``. That mail groups
every unread reply.
"""

import enum
import logging
import re
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.cache import cache

from apps.core.text import one_line
from apps.email_channel import presence
from apps.email_channel.content import REPLY_MARKER
from apps.email_channel.models import Mailbox
from apps.email_channel.tokens import conversation_token, reply_address
from apps.tickets.access import ticket_session_ids
from apps.tickets.models import (
    PRE_LOGIN_ANONYMOUS_KEY,
    Ticket,
    TicketMessage,
)

logger = logging.getLogger(__name__)

# Enough for a mail client to thread on, and a bound on the headers of a long one.
MAX_REFERENCES = 20
# What a reply mail recalls of the conversation before its new replies.
CONTEXT_MESSAGES = 3
# Below the broker's visibility timeout (an hour with Redis), past which a task
# not yet run is delivered again.
MAX_DELAY_MINUTES = 55
# How long a ticket's reply mail may take to build and send, at most.
REPLY_LOCK_SECONDS = 300
# What a reply mail attaches of its replies' files, in all. The rest is only named.
MAIL_ATTACHMENTS_MAX_BYTES = 10 * 1024 * 1024
_MIMETYPE = re.compile(r"[\w.+-]+/[\w.+-]+")


class Delivery(enum.StrEnum):
    """When a reply is emailed to its requester."""

    NOW = "now"
    LATER = "later"  # Unless read in the widget first.
    NEVER = "never"


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
    if not any(presence.is_connected(s) for s in ticket_session_ids(ticket)):
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
            countdown=min(settings.WIDGET_UNREAD_EMAIL_DELAY_MINUTES, MAX_DELAY_MINUTES)
            * 60,
        )


def carried_by_later_reply(message) -> bool:
    """Tell if the next reply of an agent's carries ``message`` in its mail.

    It does unless the requester read, wrote or was emailed in between: that
    reply's mail then starts after ``message``, which goes on its own.
    """
    later = (
        message.ticket.messages.filter(
            sender_type=TicketMessage.SenderType.AGENT,
            message_type=TicketMessage.MessageType.REPLY,
            created_at__gt=message.created_at,
        )
        .order_by("created_at")
        .first()
    )
    return later is not None and message in unread_replies(later)


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


def mail_attachments(replies) -> tuple[list[tuple[str, bytes, str]], set]:
    """The files of ``replies`` their mail attaches, and the ids of those attached.

    In the order they were sent, as long as they fit in
    ``MAIL_ATTACHMENTS_MAX_BYTES`` together; one that doesn't is left for the next,
    smaller ones. A file storage can't read is left out too: the mail names it.
    """
    budget = MAIL_ATTACHMENTS_MAX_BYTES
    files, attached = [], set()
    for reply in replies:
        for attachment in sorted(reply.attachments.all(), key=lambda a: a.created_at):
            if not attachment.file or attachment.file_size > budget:
                continue
            try:
                with attachment.file.open("rb") as stored:
                    content = stored.read(budget + 1)
            except Exception:
                logger.exception(
                    "Couldn't read attachment %s to mail it", attachment.pk
                )
                continue
            if len(content) > budget:
                continue
            budget -= len(content)
            mimetype = attachment.content_type
            if not _MIMETYPE.fullmatch(mimetype or ""):
                mimetype = "application/octet-stream"
            files.append((one_line(attachment.filename) or "file", content, mimetype))
            attached.add(attachment.pk)
    return files, attached


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
    name = one_line(organization.email_from_name) or one_line(organization.name)
    return formataddr((name, mailbox.inbound_address))


def reply_to(ticket) -> list[str] | None:
    """Where a reply to the ticket's mail goes, while the inbound domain is set."""
    return [reply_address(ticket)] if settings.INBOUND_EMAIL_DOMAIN else None


def reply_marker() -> str:
    """The line a reply is written above, if replies come back to us."""
    return REPLY_MARKER if settings.INBOUND_EMAIL_DOMAIN else ""


def threading_headers(ticket, before=None) -> dict[str, str]:
    """``In-Reply-To`` and ``References`` on the ticket's mails, those before ``before``.

    At most ``MAX_REFERENCES`` ids: the thread's first, and the latest.
    """
    messages = ticket.messages.exclude(external_id="")
    if before is not None:
        messages = messages.filter(created_at__lt=before)
    ids = [
        message_id
        for message_id in messages.order_by("created_at").values_list(
            "external_id", flat=True
        )
        if message_id.startswith("<") and message_id.endswith(">")
    ]
    if not ids:
        return {}
    if len(ids) > MAX_REFERENCES:
        ids = ids[:1] + ids[-(MAX_REFERENCES - 1) :]
    return {"In-Reply-To": ids[-1], "References": " ".join(ids)}


def conversation_url(ticket, address: str) -> str:
    """A link to the ticket's conversation, mailed to ``address``, or "".

    Only to the address its contact holds: a link opens the contact's
    conversation, and the ticket's address may be someone else's (an agent
    relinked the ticket) or merely declared. Never on a ticket a login moved, whose
    contact isn't necessarily who wrote it.
    """
    contact = ticket.contact
    metadata = ticket.context_metadata
    if (
        contact is None
        or contact.is_anonymized
        or not contact.email
        or contact.email.strip().lower() != address.strip().lower()
        or (isinstance(metadata, dict) and PRE_LOGIN_ANONYMOUS_KEY in metadata)
    ):
        return ""
    token = conversation_token(ticket, contact, address)
    return f"{settings.SITE_URL.rstrip('/')}/c/{token}"


def sender_label(message, address: str = "") -> str:
    """Who wrote ``message``, as the requester mailed at ``address`` reads it.

    "You" for their own words; a third party copied on the thread by name, else
    by address.
    """
    if message.sender_type == TicketMessage.SenderType.USER:
        name, sender = parseaddr(message.external_sender)
        if not sender or sender.strip().lower() == address.strip().lower():
            return "You"
        return one_line(name) or sender
    author = message.author
    if author is None:
        return "Support"
    return one_line(author.first_name) or (
        author.email.split("@")[0] if author.email else "Support"
    )


def reply_lock_key(ticket) -> str:
    """The cache key held while a reply mail of ``ticket`` is built and sent."""
    return f"email_channel:reply_lock:{ticket.pk}"


def lock_replies(ticket) -> bool:
    """Take the ticket's reply lock, if free: one reply mail at a time per ticket."""
    return cache.add(reply_lock_key(ticket), 1, REPLY_LOCK_SECONDS)


def unlock_replies(ticket) -> None:
    cache.delete(reply_lock_key(ticket))
