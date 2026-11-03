"""Storing what arrives, before anything else reads it (design §4)."""

import hashlib
import logging
from datetime import timedelta
from email.utils import parseaddr

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.text import one_line
from apps.email_channel.models import InboundEmail
from apps.email_channel.recipients import recipient_addresses, resolve

logger = logging.getLogger(__name__)

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


def _too_many_rejected(sender: str, mailbox) -> bool:
    """Tell if the sender's rejected mail to ``mailbox`` filled its hour's log.

    Mail nobody here asked for, to an unknown address or an inactive organization,
    still leaves a row: bounded per sender as accepted mail is, so that a flood
    leaves a trace without filling the table.
    """
    rows = InboundEmail.objects.filter(
        sender=sender,
        mailbox=mailbox,
        status=InboundEmail.Status.REJECTED,
        received_at__gt=timezone.now() - timedelta(hours=1),
    )
    return rows.count() >= settings.INBOUND_EMAIL_RATE_LIMIT_PER_HOUR


def store(message, *, raw: bytes | None = None) -> InboundEmail | None:
    """Store an inbound mail and queue its processing. None for a duplicate.

    The only entry point of inbound mail, for the provider webhooks and
    ``ingest_eml`` alike. ``raw`` is the mail as received, when the caller has it.
    A mail for no mailbox, or for an inactive organization, is kept as rejected
    without its content, and goes no further; past the sender's hourly quota of
    such rows, it isn't kept at all. Exceptions propagate, so that a provider
    retries.
    """
    if raw is None:
        raw = message.as_bytes()
    with transaction.atomic():
        recipient = resolve(message)
        mailbox = recipient.mailbox if recipient else None
        _, sender = parseaddr(one_line(message.get("From")))
        # ``ticket`` is where the mail lands, once processed: the ticket of a reply
        # address is found again from the envelope.
        fields = {
            "message_id": normalize_message_id(message, raw),
            "mailbox": mailbox,
            "sender": sender.lower()[:_SENDER_MAX_LENGTH],
            "recipients": recipient_addresses(message),
            "subject": one_line(message.get("Subject"))[:_SUBJECT_MAX_LENGTH],
            **_provider_verdict(message),
        }
        if recipient is None:
            fields["status"] = InboundEmail.Status.REJECTED
            fields["reason"] = "unknown_recipient"
        elif not recipient.organization.is_active:
            fields["status"] = InboundEmail.Status.REJECTED
            fields["reason"] = "inactive_organization"
        rejected = fields.get("status") == InboundEmail.Status.REJECTED
        same = InboundEmail.objects.filter(
            message_id=fields["message_id"], mailbox=mailbox
        )
        if mailbox is None and not rejected:
            # The same mail rejected through an old reply address, say, doesn't
            # make this one a duplicate.
            same = same.exclude(status=InboundEmail.Status.REJECTED)
        stored = same.first()
        if stored is not None:
            # A retry of the provider: the first queuing may have failed after
            # commit. Running the task twice is harmless.
            if stored.status == InboundEmail.Status.PENDING:
                _queue_after_commit(stored)
            return None
        if rejected and _too_many_rejected(fields["sender"], mailbox):
            logger.info("Inbound mail not logged: its sender's quota is used up")
            return None
        try:
            with transaction.atomic():
                inbound = InboundEmail.objects.create(**fields)
        except IntegrityError:
            # Stored meanwhile by another delivery of the same mail, which queues it.
            return None
        if rejected:
            return inbound
        inbound.raw.save("raw.eml", ContentFile(raw), save=False)
        inbound.save(update_fields=["raw", "updated_at"])
        _queue_after_commit(inbound)
    return inbound


def store_unparseable(
    raw: bytes, *, envelope_recipient=None, envelope_sender=None
) -> InboundEmail | None:
    """Keep a mail that can't be parsed, rejected, as a log. None for a duplicate.

    Nested deeper than the parser can go, for instance. It's known by its
    content's hash, so that a provider's retry is still a duplicate.
    """
    with transaction.atomic():
        inbound, created = InboundEmail.objects.get_or_create(
            message_id=_hashed_message_id(raw),
            mailbox=None,
            defaults={
                "status": InboundEmail.Status.REJECTED,
                "reason": "unparseable",
                "envelope_recipient": _envelope_address(envelope_recipient),
                "envelope_sender": _envelope_address(envelope_sender),
            },
        )
        if not created:
            return None
        inbound.raw.save("raw.eml", ContentFile(raw), save=False)
        inbound.save(update_fields=["raw", "updated_at"])
    return inbound


def _queue_after_commit(inbound: InboundEmail) -> None:
    from apps.email_channel.tasks import process_inbound_email

    inbound_id = str(inbound.id)

    def queue() -> None:
        try:
            process_inbound_email.delay(inbound_id)
        except Exception:
            # Stored: the provider's retry, or requeue_stale_inbound, queues it again.
            logger.exception("Couldn't queue inbound mail %s", inbound_id)
            raise

    transaction.on_commit(queue)
