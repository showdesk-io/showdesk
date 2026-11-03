"""Storing what arrives, before anything else reads it (design §4)."""

import hashlib
from email.utils import parseaddr

from django.core.files.base import ContentFile
from django.db import transaction

from apps.email_channel.models import InboundEmail
from apps.email_channel.recipients import one_line, recipient_addresses, resolve

_MESSAGE_ID_MAX_LENGTH = InboundEmail._meta.get_field("message_id").max_length
_SENDER_MAX_LENGTH = InboundEmail._meta.get_field("sender").max_length
_SUBJECT_MAX_LENGTH = InboundEmail._meta.get_field("subject").max_length
_ENVELOPE_MAX_LENGTH = InboundEmail._meta.get_field("envelope_recipient").max_length


def _hashed_message_id(value: bytes) -> str:
    return f"<{hashlib.sha256(value).hexdigest()}@hashed.invalid>"


def normalize_message_id(message, raw: bytes) -> str:
    """The mail's Message-ID, or a stable stand-in that fits the column.

    A mail without one is known by its content, so that a provider's retry is
    still a duplicate.
    """
    message_id = one_line(message.get("Message-ID"))
    if not message_id:
        return _hashed_message_id(raw)
    if len(message_id) > _MESSAGE_ID_MAX_LENGTH:
        return _hashed_message_id(message_id.encode("utf-8", "surrogateescape"))
    return message_id


def _envelope_address(value) -> str:
    """An envelope address as stored: lowercased, or "" if it can't fit.

    Truncated, it would be another address.
    """
    address = one_line(value).lower()
    return address if len(address) <= _ENVELOPE_MAX_LENGTH else ""


def _provider_verdict(message) -> dict:
    """What the provider said of the mail, which its raw bytes don't hold."""
    spam_detected = getattr(message, "spam_detected", None)
    spam_score = getattr(message, "spam_score", None)
    return {
        "envelope_recipient": _envelope_address(message.envelope_recipient),
        "envelope_sender": _envelope_address(getattr(message, "envelope_sender", "")),
        "spam_detected": spam_detected if isinstance(spam_detected, bool) else None,
        "spam_score": float(spam_score) if spam_score is not None else None,
    }


def store(message, *, raw: bytes | None = None) -> InboundEmail | None:
    """Store an inbound mail and queue its processing. None for a duplicate.

    The only entry point of inbound mail, for the provider webhooks and
    ``ingest_eml`` alike. ``raw`` is the mail as received, when the caller has it.
    A mail for no mailbox is kept as rejected, and goes no further. Exceptions
    propagate, so that a provider retries.
    """
    if raw is None:
        raw = message.as_bytes()
    with transaction.atomic():
        recipient = resolve(message)
        mailbox = recipient.mailbox if recipient else None
        _, sender = parseaddr(one_line(message.get("From")))
        defaults = {
            "ticket": recipient.ticket if recipient else None,
            "sender": sender.lower()[:_SENDER_MAX_LENGTH],
            "recipients": recipient_addresses(message),
            "subject": one_line(message.get("Subject"))[:_SUBJECT_MAX_LENGTH],
            **_provider_verdict(message),
        }
        if recipient is None:
            defaults["status"] = InboundEmail.Status.REJECTED
            defaults["reason"] = "unknown_recipient"
        elif not recipient.organization.is_active:
            defaults["status"] = InboundEmail.Status.REJECTED
            defaults["reason"] = "inactive_organization"
        inbound, created = InboundEmail.objects.get_or_create(
            message_id=normalize_message_id(message, raw),
            mailbox=mailbox,
            defaults=defaults,
        )
        if not created:
            # A retry of the provider: the first queuing may have failed after
            # commit. Running the task twice is harmless.
            if inbound.status == InboundEmail.Status.PENDING:
                _queue_after_commit(inbound)
            return None
        inbound.raw.save("raw.eml", ContentFile(raw), save=False)
        inbound.save(update_fields=["raw", "updated_at"])
        if inbound.status == InboundEmail.Status.PENDING:
            _queue_after_commit(inbound)
    return inbound


def _queue_after_commit(inbound: InboundEmail) -> None:
    from apps.email_channel.tasks import process_inbound_email

    inbound_id = str(inbound.id)
    transaction.on_commit(lambda: process_inbound_email.delay(inbound_id))
