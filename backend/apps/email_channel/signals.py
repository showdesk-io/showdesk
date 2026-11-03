"""Receivers of the email channel's signals."""

from anymail.signals import AnymailInboundEvent

from apps.email_channel.inbound import store


def store_inbound_event(
    sender, event: AnymailInboundEvent, esp_name: str, **kwargs
) -> None:
    """Store a mail a provider's webhook received.

    Exceptions reach the webhook's response, so that the provider retries.
    """
    message = event.message
    store(message, raw=getattr(message, "raw_bytes", None))
