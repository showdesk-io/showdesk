"""Signed addresses and links, and the Message-IDs of the mail we send.

Signed values are verifiable without a lookup, and unforgeable without SECRET_KEY.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta
from email.utils import parseaddr
from urllib.parse import urlsplit

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


def email_hash(email: str) -> str:
    """A short hash of an address, so that a link doesn't spell it out."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ConversationClaim:
    """What a conversation link claims: a ticket, its contact, the address mailed.

    Only a claim: the ticket must still be that contact's, and the contact must
    still hold that address, for it to prove anything. The address is only known
    by its hash.
    """

    ticket_id: str
    contact_id: str
    email_hash: str

    def holds(self, email: str) -> bool:
        """Tell if ``email`` is the address the link was mailed to."""
        return bool(email.strip()) and constant_time_compare(
            email_hash(email), self.email_hash
        )


def conversation_token(ticket, contact, email: str) -> str:
    """The token of a link to ``ticket``'s conversation, mailed to ``email``."""
    payload = {"t": str(ticket.id), "c": str(contact.id), "h": email_hash(email)}
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
        return ConversationClaim(str(data["t"]), str(data["c"]), str(data["h"]))
    except (signing.BadSignature, KeyError, TypeError):  # Includes SignatureExpired.
        return None


def _outbound_domain() -> str:
    """The domain of our Message-IDs: inbound, else of the mail's From, else the site's."""
    _, at, from_domain = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].rpartition("@")
    return (
        settings.INBOUND_EMAIL_DOMAIN
        or (from_domain if at else "")
        or urlsplit(settings.SITE_URL).hostname
        or "localhost"
    )


def outbound_message_id(message) -> str:
    """The Message-ID of the mail sending ``message``: the same on every retry."""
    return f"<{message.id}@{_outbound_domain()}>"


def resolution_message_id(ticket) -> str:
    """The Message-ID of the mail telling ``ticket`` was resolved, at its resolution.

    The same on every retry; a later resolution gets its own.
    """
    resolved_at = ticket.resolved_at
    stamp = int(resolved_at.timestamp()) if resolved_at else 0
    return f"<resolved-{ticket.id}-{stamp}@{_outbound_domain()}>"
