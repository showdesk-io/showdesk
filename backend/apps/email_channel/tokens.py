"""Signed addresses: verifiable without a lookup, unforgeable without SECRET_KEY."""

import uuid

from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac

_REPLY_SALT = "showdesk.email_channel.reply"


def _reply_signature(ticket_hex: str) -> str:
    return salted_hmac(_REPLY_SALT, ticket_hex, algorithm="sha256").hexdigest()[:16]


def reply_address(ticket) -> str:
    """The address a reply to ``ticket`` goes to: ``reply+{id}.{signature}@…``."""
    ticket_hex = ticket.id.hex
    return (
        f"reply+{ticket_hex}.{_reply_signature(ticket_hex)}"
        f"@{settings.INBOUND_EMAIL_DOMAIN}"
    )


def ticket_id_from_reply_address(address: str) -> uuid.UUID | None:
    """Return the ticket an address names, or None if it isn't one of ours."""
    local, _, domain = address.strip().lower().partition("@")
    inbound_domain = settings.INBOUND_EMAIL_DOMAIN.lower()
    if not inbound_domain or domain != inbound_domain:
        return None
    if not local.startswith("reply+"):
        return None
    ticket_hex, _, signature = local.removeprefix("reply+").partition(".")
    if not constant_time_compare(signature, _reply_signature(ticket_hex)):
        return None
    try:
        return uuid.UUID(hex=ticket_hex)
    except ValueError:
        return None
