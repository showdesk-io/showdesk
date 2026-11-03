"""Which mailbox, or which ticket, an inbound mail is for (design §4.1)."""

from dataclasses import dataclass
from email.utils import getaddresses

from django.conf import settings
from django.db.models import Q

from apps.email_channel.models import Mailbox
from apps.email_channel.tokens import ticket_id_from_reply_address
from apps.tickets.models import Ticket

# Searched after the envelope recipient, in this order. A forward keeps ``To`` on
# the public address and puts the inbound address in one of the first ones.
RECIPIENT_HEADERS = ("Delivered-To", "X-Original-To", "X-Forwarded-To", "To", "Cc")
# Enough for any real mail, and a bound on what one mail makes us look up.
_MAX_ADDRESSES = 100


@dataclass(frozen=True)
class Recipient:
    """What an inbound mail was sent to.

    ``ticket`` is set by a reply address, with the ticket's mailbox, if any.
    ``address`` is the address that matched, lowercased.
    """

    mailbox: Mailbox | None
    ticket: Ticket | None
    address: str

    @property
    def organization(self):
        """The organization the mail is for."""
        return self.ticket.organization if self.ticket else self.mailbox.organization


def _addresses(values: list[str]) -> list[str]:
    addresses = []
    for _, address in getaddresses(values):
        address = address.strip().lower()
        if address and address not in addresses:
            addresses.append(address)
    return addresses[:_MAX_ADDRESSES]


def recipient_addresses(message) -> list[str]:
    """The envelope recipient then the recipient headers' addresses, lowercased."""
    values = []
    if message.envelope_recipient:
        values.append(str(message.envelope_recipient))
    for name in RECIPIENT_HEADERS:
        values.extend(str(value) for value in message.get_all(name, []))
    return _addresses(values)


def resolve(message) -> Recipient | None:
    """Find what ``message`` is for, or None when it's for no active mailbox.

    The envelope recipient is what the provider delivered to; headers are whatever
    the sender wrote. So when there is one, it alone decides. Only a mail without
    one, as fed to ``ingest_eml`` without ``--recipient``, is resolved from its
    headers, in the order of ``RECIPIENT_HEADERS``.

    A reply address wins over any mailbox. Otherwise the first address that is the
    inbound or public address of an active mailbox.
    """
    if message.envelope_recipient:
        addresses = _addresses([str(message.envelope_recipient)])
    else:
        addresses = recipient_addresses(message)
    for address in addresses:
        ticket_id = ticket_id_from_reply_address(address)
        if ticket_id is None:
            continue
        ticket = (
            Ticket.objects.select_related("mailbox", "organization")
            .filter(pk=ticket_id)
            .first()
        )
        if ticket is not None:
            return Recipient(mailbox=ticket.mailbox, ticket=ticket, address=address)

    suffix = f"@{settings.INBOUND_EMAIL_DOMAIN.lower()}"
    local_parts = [
        address.removesuffix(suffix)
        for address in addresses
        if settings.INBOUND_EMAIL_DOMAIN and address.endswith(suffix)
    ]
    mailboxes = list(
        Mailbox.objects.select_related("organization")
        .filter(is_active=True)
        .filter(Q(local_part__in=local_parts) | Q(public_address__in=addresses))
    )
    for address in addresses:
        for mailbox in mailboxes:
            if address in (mailbox.inbound_address.lower(), mailbox.public_address):
                return Recipient(mailbox=mailbox, ticket=None, address=address)
    return None
