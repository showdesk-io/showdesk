"""Signed addresses and links, and the Message-IDs of the mail we send.

Signed values are verifiable without a lookup, and unforgeable without SECRET_KEY.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from email.utils import parseaddr

from django.conf import settings
from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac

_REPLY_SALT = "showdesk.email_channel.reply"
_CONVERSATION_SALT = "showdesk.email_channel.conversation"


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


@dataclass(frozen=True)
class ConversationClaim:
    """What a conversation link claims: a ticket, its contact, the address mailed.

    Only a claim: the ticket must still be that contact's, and the contact must
    still hold that address, for it to prove anything.
    """

    ticket_id: str
    contact_id: str
    email: str


def conversation_token(ticket, contact, email: str) -> str:
    """The token of a link to ``ticket``'s conversation, mailed to ``email``."""
    payload = {"t": str(ticket.id), "c": str(contact.id), "e": email.strip().lower()}
    return signing.dumps(payload, salt=_CONVERSATION_SALT, compress=True)


def read_conversation_token(
    token: str, *, allow_expired: bool = False
) -> ConversationClaim | None:
    """Return what a token claims, or None.

    ``allow_expired`` is only for asking for a new link.
    """
    max_age = (
        None
        if allow_expired
        else timedelta(days=settings.CONVERSATION_LINK_MAX_AGE_DAYS)
    )
    try:
        data = signing.loads(token, salt=_CONVERSATION_SALT, max_age=max_age)
        return ConversationClaim(str(data["t"]), str(data["c"]), str(data["e"]))
    except (signing.BadSignature, KeyError, TypeError):  # Includes SignatureExpired.
        return None


def outbound_message_id(message) -> str:
    """The Message-ID of the mail sending ``message``: the same on every retry.

    On the inbound domain, or without one on the domain mail goes out from.
    """
    domain = (
        settings.INBOUND_EMAIL_DOMAIN
        or (parseaddr(settings.DEFAULT_FROM_EMAIL)[1].rpartition("@")[2])
    )
    return f"<{message.id}@{domain}>"
