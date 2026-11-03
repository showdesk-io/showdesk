"""Signed addresses and links, and the Message-IDs of the mail we send.

Signed values are verifiable without a lookup, and unforgeable without SECRET_KEY.
"""

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
_EMAIL_HASH_SALT = "showdesk.email_channel.email_hash"
# How old a link may be and still get a new one mailed. Past that, ask support.
RENEWABLE_FOR = timedelta(days=180)


def _secrets() -> list[str]:
    """The keys a signature may have been made with: the current one, then the old."""
    return [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]


def _reply_signature(ticket_hex: str, secret: str | None = None) -> str:
    return salted_hmac(
        _REPLY_SALT, ticket_hex, secret=secret, algorithm="sha256"
    ).hexdigest()[:16]


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
    if not any(
        constant_time_compare(signature, _reply_signature(ticket_hex, secret))
        for secret in _secrets()
    ):
        return None
    try:
        return uuid.UUID(hex=ticket_hex)
    except ValueError:
        return None


def email_hash(email: str, secret: str | None = None) -> str:
    """A short keyed hash of an address, so that a link doesn't spell it out.

    Keyed, so that hashing a list of addresses doesn't find the one a link names.
    """
    return salted_hmac(
        _EMAIL_HASH_SALT, email.strip().lower(), secret=secret, algorithm="sha256"
    ).hexdigest()[:16]


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
        """Tell if ``email`` is the address the link was mailed to.

        The hash may have been made with a key since rotated out of ``SECRET_KEY``.
        """
        return bool(email.strip()) and any(
            constant_time_compare(email_hash(email, secret), self.email_hash)
            for secret in _secrets()
        )


def conversation_token(ticket, contact, email: str) -> str:
    """The token of a link to ``ticket``'s conversation, mailed to ``email``."""
    payload = {"t": str(ticket.id), "c": str(contact.id), "h": email_hash(email)}
    return signing.dumps(payload, salt=_CONVERSATION_SALT, compress=True)


def read_conversation_token(
    token: str, *, allow_expired: bool = False, renewable: bool = False
) -> ConversationClaim | None:
    """Return what a token claims, or None.

    ``renewable`` reads a token young enough to get a new link (``RENEWABLE_FOR``),
    and ``allow_expired`` one of any age, to tell an expired link from a forged one.
    Neither opens a conversation.
    """
    if allow_expired:
        max_age = None
    elif renewable:
        max_age = RENEWABLE_FOR
    else:
        max_age = timedelta(days=settings.CONVERSATION_LINK_MAX_AGE_DAYS)
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
