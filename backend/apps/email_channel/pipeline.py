"""Turning a stored inbound mail into a ticket or a message (design §4.2 to §4.5).

What a mail says of its sender is a claim: it names a contact, never proves one,
and it never makes anyone a contact who works for the organization.
"""

import logging
from email.utils import parseaddr

from anymail.inbound import AnymailInboundMessage
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from apps.contacts.gdpr import PREVIOUS_TICKET_KEY
from apps.contacts.services import is_staff_address, resolve_contact_for_email
from apps.email_channel.content import (
    Attachment,
    dropped_note,
    extract_attachments,
    extract_body,
    strip_history,
)
from apps.email_channel.filters import classify
from apps.email_channel.models import InboundEmail
from apps.email_channel.recipients import Recipient, one_line, stored_recipient
from apps.email_channel.thread_matching import (
    ReopenOutcome,
    apply_reopen_rule,
    find_ticket,
    is_forward,
    lock_matched_ticket,
)
from apps.notifications.signals import (
    notify_new_message,
    notify_new_ticket,
    notify_ticket_update,
)
from apps.tickets.models import Ticket, TicketAttachment, TicketMessage

logger = logging.getLogger(__name__)

PROCESSABLE = (InboundEmail.Status.PENDING, InboundEmail.Status.FAILED)
NO_SUBJECT = "(no subject)"

_TITLE_MAX_LENGTH = Ticket._meta.get_field("title").max_length
_NAME_MAX_LENGTH = Ticket._meta.get_field("requester_name").max_length
_EMAIL_MAX_LENGTH = Ticket._meta.get_field("requester_email").max_length
_EXTERNAL_SENDER_MAX_LENGTH = TicketMessage._meta.get_field(
    "external_sender"
).max_length


class Unprocessable(Exception):
    """A mail that no retry will process: it's marked failed with ``reason``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _parsed(inbound: InboundEmail):
    """The stored mail, with what the provider said that its bytes don't hold."""
    if not inbound.raw or not inbound.raw.storage.exists(inbound.raw.name):
        raise Unprocessable("raw_missing")
    with inbound.raw.open("rb") as file:
        raw = file.read()
    try:
        message = AnymailInboundMessage.parse_raw_mime_bytes(raw)
    except RecursionError:
        raise Unprocessable("unparseable") from None
    message.envelope_recipient = inbound.envelope_recipient or None
    message.envelope_sender = inbound.envelope_sender or None
    message.spam_detected = inbound.spam_detected
    message.spam_score = inbound.spam_score
    return message


def _sender(message) -> tuple[str, str]:
    """The display name and address of the mail's From, the address "" if unusable."""
    name, address = parseaddr(one_line(message.get("From")))
    address = address.strip().lower()
    try:
        validate_email(address)
    except ValidationError:
        address = ""
    if len(address) > _EMAIL_MAX_LENGTH:
        address = ""
    return one_line(name), address


def _external_sender(name: str, address: str) -> str:
    """``"Name" <address>``, quoted so that a comma in a name doesn't split it."""
    if not name:
        return address[:_EXTERNAL_SENDER_MAX_LENGTH]
    quoted = name.replace("\\", "\\\\").replace('"', '\\"')
    value = f'"{quoted}" <{address}>' if address else name
    return value if len(value) <= _EXTERNAL_SENDER_MAX_LENGTH else address


def _finish(inbound: InboundEmail, status: str, reason: str = "") -> None:
    inbound.status = status
    inbound.reason = reason
    inbound.processed_at = timezone.now()
    inbound.save(
        update_fields=[
            "status",
            "reason",
            "processed_at",
            "ticket",
            "ticket_message",
            "updated_at",
        ]
    )


def _locked(inbound_id: str) -> InboundEmail | None:
    """The row, locked, if it's still to process and no other run holds it."""
    return (
        InboundEmail.objects.select_for_update(of=("self",), skip_locked=True)
        .select_related("mailbox__organization")
        .filter(pk=inbound_id, status__in=PROCESSABLE)
        .first()
    )


def _mark_unprocessable(inbound_id: str, reason: str) -> None:
    InboundEmail.objects.filter(pk=inbound_id, status__in=PROCESSABLE).update(
        status=InboundEmail.Status.FAILED,
        reason=reason,
        processed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def process(inbound_id: str) -> None:
    """Run one stored mail through the pipeline. Safe to run again.

    Does nothing unless the mail is pending or failed and no other run holds it:
    it can be queued twice. First its recipient and filters, under the row's lock.
    Then its files are stored, outside any transaction, and the ticket and message
    are written in a second one, which deletes those files if it fails. Realtime
    events and emails go once it's committed. A mail no retry would help is marked
    failed with the reason, and returns.
    """
    try:
        with transaction.atomic():
            inbound = _locked(inbound_id)
            if inbound is None:
                return
            message = _parsed(inbound)
            recipient = _triage(inbound, message)
            if recipient is None:
                return
        body, attachments = _content(message)
    except Unprocessable as exc:
        _mark_unprocessable(inbound_id, exc.reason)
        return
    except RecursionError:
        _mark_unprocessable(inbound_id, "unparseable")
        return

    stored = _store_files(attachments)
    landed = False
    try:
        with transaction.atomic():
            inbound = _locked(inbound_id)
            if inbound is not None:
                _write(inbound, message, recipient, body, stored)
                landed = True
    finally:
        if not landed:
            _delete_files(name for _, name in stored)


def _triage(inbound: InboundEmail, message) -> Recipient | None:
    """The mail's recipient, or None once it's finished as rejected or ignored."""
    recipient = stored_recipient(inbound, message)
    if recipient is None:
        _finish(inbound, InboundEmail.Status.REJECTED, "unknown_recipient")
        return None
    if not recipient.organization.is_active:
        _finish(inbound, InboundEmail.Status.REJECTED, "inactive_organization")
        return None
    verdict = classify(message, inbound, recipient)
    if verdict is not None:
        _finish(inbound, verdict.status, verdict.reason)
        return None
    return recipient


def _content(message) -> tuple[str, list[Attachment]]:
    body = extract_body(message)
    # What a forward quotes is the request itself.
    if not is_forward(message.get("Subject")):
        body = strip_history(body)
    attachments, dropped = extract_attachments(
        message, settings.INBOUND_EMAIL_MAX_SIZE_MB * 1024 * 1024
    )
    note = dropped_note(dropped)
    return "\n\n".join(part for part in (body, note) if part), attachments


def _store_files(attachments: list[Attachment]) -> list[tuple[Attachment, str]]:
    """Store the files, before the transaction that takes the organization's lock."""
    field = TicketAttachment._meta.get_field("file")
    stored = []
    try:
        for attachment in attachments:
            name = field.generate_filename(None, attachment.filename)
            name = field.storage.save(name, ContentFile(attachment.content))
            stored.append((attachment, name))
    except BaseException:
        _delete_files(name for _, name in stored)
        raise
    return stored


def _delete_files(names) -> None:
    storage = TicketAttachment._meta.get_field("file").storage
    for name in names:
        try:
            storage.delete(name)
        except Exception:
            logger.exception("Couldn't delete the attachment file %s", name)


def _write(
    inbound: InboundEmail,
    message,
    recipient: Recipient,
    body: str,
    stored: list[tuple[Attachment, str]],
) -> None:
    organization = recipient.organization
    name, address = _sender(message)
    match = find_ticket(message, recipient, address, organization)
    ticket, previous, reopened = None, None, False
    if match is not None:
        ticket = lock_matched_ticket(match, organization)
    if ticket is not None:
        outcome = apply_reopen_rule(ticket)
        if outcome == ReopenOutcome.EXPIRED:
            ticket, previous = None, ticket
        reopened = outcome == ReopenOutcome.REOPENED

    created = ticket is None
    if created:
        ticket = _new_ticket(message, recipient, organization, name, address, body)
        if previous is not None:
            ticket.context_metadata = {PREVIOUS_TICKET_KEY: str(previous.id)}
            ticket.save(update_fields=["context_metadata", "updated_at"])
    ticket_message = TicketMessage.objects.create(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        channel=TicketMessage.Channel.EMAIL,
        body=body,
        external_id=inbound.message_id,
        external_sender=_external_sender(name, address),
    )
    TicketAttachment.objects.bulk_create(
        TicketAttachment(
            ticket=ticket,
            message=ticket_message,
            uploaded_by=None,
            file=name,
            filename=attachment.filename,
            content_type=attachment.content_type,
            file_size=len(attachment.content),
        )
        for attachment, name in stored
    )
    inbound.ticket = ticket
    inbound.ticket_message = ticket_message
    _finish(inbound, InboundEmail.Status.PROCESSED)
    transaction.on_commit(
        lambda: _announce(ticket, ticket_message, created=created, reopened=reopened)
    )


def _new_ticket(message, recipient, organization, name: str, address: str, body: str):
    contact = None
    if address and not is_staff_address(organization.id, address):
        contact = resolve_contact_for_email(organization, address, name=name)
    mailbox = recipient.mailbox
    title = one_line(message.get("Subject"))[:_TITLE_MAX_LENGTH] or NO_SUBJECT
    return Ticket.objects.create(
        organization=organization,
        reference=organization.next_ticket_reference(),
        title=title,
        description=body,
        source=Ticket.Source.EMAIL,
        mailbox=mailbox,
        assigned_team=mailbox.default_team if mailbox else None,
        contact=contact,
        requester_email=address,
        requester_name=name[:_NAME_MAX_LENGTH],
    )


def _announce(ticket, message, *, created: bool, reopened: bool) -> None:
    """Tell agents, and the widget, of what a mail added."""
    from apps.tickets.tasks import send_ticket_created_email, send_ticket_reply_email

    events = [lambda: notify_new_message(message)]
    if created:
        events.insert(0, lambda: notify_new_ticket(ticket))
    elif reopened:
        events.insert(0, lambda: notify_ticket_update(ticket))
    for event in events:
        try:
            event()
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
    try:
        if created:
            send_ticket_created_email.delay(str(ticket.id))
        else:
            send_ticket_reply_email.delay(str(message.id))
    except Exception:
        # The mail is in: only the agents' email about it is lost.
        logger.exception(
            "Couldn't queue the notification email of %s", ticket.reference
        )
