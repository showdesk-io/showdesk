"""Receivers of the email channel's signals."""

import logging

from anymail.signals import AnymailInboundEvent
from django.db import transaction

from apps.email_channel.inbound import store

logger = logging.getLogger(__name__)


def store_inbound_event(
    sender, event: AnymailInboundEvent, esp_name: str, **kwargs
) -> None:
    """Store a mail a provider's webhook received.

    Exceptions reach the webhook's response, so that the provider retries.
    """
    message = event.message
    store(message, raw=getattr(message, "raw_bytes", None))


def delete_raw_mail(sender, instance, **kwargs) -> None:
    """Delete a deleted row's raw mail once the deletion is committed.

    Rows also go by cascade, with their mailbox or organization: a mail holds
    personal data, and no row would point to its file anymore.
    """
    if not instance.raw:
        return
    storage, name = instance.raw.storage, instance.raw.name

    def delete() -> None:
        try:
            storage.delete(name)
        except Exception:
            logger.exception("Couldn't delete the raw mail %s", name)

    transaction.on_commit(delete)
