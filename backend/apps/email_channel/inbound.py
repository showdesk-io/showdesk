"""Storing what arrives, before anything else reads it (design §4)."""

import hashlib
from email.utils import parseaddr

from django.core.files.base import ContentFile
from django.db import transaction

from apps.email_channel.models import InboundEmail
from apps.email_channel.recipients import recipient_addresses, resolve

_MESSAGE_ID_MAX_LENGTH = InboundEmail._meta.get_field("message_id").max_length
_SENDER_MAX_LENGTH = InboundEmail._meta.get_field("sender").max_length
_SUBJECT_MAX_LENGTH = InboundEmail._meta.get_field("subject").max_length


def _one_line(value) -> str:
    return " ".join(str(value or "").split())


def _hashed_message_id(value: bytes) -> str:
    return f"<{hashlib.sha256(value).hexdigest()}@hashed.invalid>"


def normalize_message_id(message, raw: bytes) -> str:
    """The mail's Message-ID, or a stable stand-in that fits the column.

    A mail without one is known by its content, so that a provider's retry is
    still a duplicate.
    """
    message_id = _one_line(message.get("Message-ID"))
    if not message_id:
        return _hashed_message_id(raw)
    if len(message_id) > _MESSAGE_ID_MAX_LENGTH:
        return _hashed_message_id(message_id.encode("utf-8", "surrogateescape"))
    return message_id


def store(message, *, raw: bytes | None = None) -> InboundEmail | None:
    """Store an inbound mail and queue its processing. None for a duplicate.

    The only entry point of inbound mail, for the provider webhooks and
    ``ingest_eml`` alike. ``raw`` is the mail as received, when the caller has it.
    A mail for no mailbox is kept as rejected, and goes no further. Exceptions
    propagate, so that a provider retries.
    """
    from apps.email_channel.tasks import process_inbound_email

    if raw is None:
        raw = message.as_bytes()
    with transaction.atomic():
        recipient = resolve(message)
        mailbox = recipient.mailbox if recipient else None
        _, sender = parseaddr(_one_line(message.get("From")))
        defaults = {
            "ticket": recipient.ticket if recipient else None,
            "sender": sender.lower()[:_SENDER_MAX_LENGTH],
            "recipients": recipient_addresses(message),
            "subject": _one_line(message.get("Subject"))[:_SUBJECT_MAX_LENGTH],
        }
        if recipient is None:
            defaults["status"] = InboundEmail.Status.REJECTED
            defaults["reason"] = "unknown_recipient"
        inbound, created = InboundEmail.objects.get_or_create(
            message_id=normalize_message_id(message, raw),
            mailbox=mailbox,
            defaults=defaults,
        )
        if not created:
            return None
        inbound.raw.save("raw.eml", ContentFile(raw), save=False)
        inbound.save(update_fields=["raw", "updated_at"])
        if inbound.status == InboundEmail.Status.PENDING:
            inbound_id = str(inbound.id)
            transaction.on_commit(lambda: process_inbound_email.delay(inbound_id))
    return inbound
