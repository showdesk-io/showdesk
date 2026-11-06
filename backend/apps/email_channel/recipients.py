"""Which mailbox, or which ticket, an inbound mail is for (design §4.1)."""

from dataclasses import dataclass
from email.utils import getaddresses

from django.conf import settings
from django.db.models import Q

from apps.core.text import one_line
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
    for _, address in getaddresses([one_line(value) for value in values]):
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
    inbound or public address of an active mailbox, an inbound address winning over
    a public one equal to it.
    """
    if message.envelope_recipient:
        addresses = _addresses([str(message.envelope_recipient)])
    else:
        addresses = recipient_addresses(message)
    ticket, address = _reply_ticket(addresses)
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
        # An inbound address first: a public address must never shadow one.
        mailbox = next(
            (m for m in mailboxes if address == m.inbound_address.lower()), None
        ) or next((m for m in mailboxes if address == m.public_address), None)
        if mailbox is not None:
            return Recipient(mailbox=mailbox, ticket=None, address=address)
    return None


def _reply_ticket(addresses: list[str]) -> tuple[Ticket | None, str]:
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
            return ticket, address
    return None, ""


def stored_recipient(inbound, message) -> Recipient | None:
    """What a stored mail was found to be for, rebuilt from its row.

    From the stored envelope recipient: a reply address gives its ticket again,
    and the row's mailbox is the one found on arrival. Only a mail stored without
    an envelope, as ``ingest_eml`` without ``--recipient`` stores it, is read from
    its headers, and for the mailbox only one of its own addresses counts. The
    row's ``ticket`` is where the mail landed, never where it was sent. None when
    neither the ticket nor the mailbox still exists.
    """
    mailbox = inbound.mailbox
    if inbound.envelope_recipient:
        addresses = _addresses([inbound.envelope_recipient])
    else:
        addresses = recipient_addresses(message)
    ticket, address = _reply_ticket(addresses)
    if ticket is not None:
        return Recipient(mailbox, ticket, address)
    if mailbox is None:
        return None
    if inbound.envelope_recipient:
        return Recipient(mailbox, None, addresses[0] if addresses else "")
    own = {mailbox.inbound_address.lower(), mailbox.public_address} - {""}
    address = next((address for address in addresses if address in own), "")
    return Recipient(mailbox, None, address)


def proves_forwarding(inbound, message, mailbox: Mailbox | None) -> bool:
    """Tell if a mail shows that the mailbox's public address forwards to it.

    The provider delivered it to the mailbox's inbound address (the envelope,
    which the sender doesn't write), from an envelope sender on the public
    address's domain, as its server's forward gets (OVH ``support+_redir+…@``,
    Gmail ``…+caf_=…@``, Microsoft's SRS), while its headers name the public
    address, as a forward keeps them. A mail also addressed to the inbound
    address itself, in ``To`` or ``Cc``, reached it directly and proves nothing.
    """
    if mailbox is None or not mailbox.public_address:
        return False
    inbound_address = mailbox.inbound_address.lower()
    if _addresses([inbound.envelope_recipient]) != [inbound_address]:
        return False
    _, at, sender_domain = inbound.envelope_sender.strip().lower().rpartition("@")
    if not at or sender_domain != mailbox.public_address.rpartition("@")[2]:
        return False
    if inbound_address in _addresses(
        [str(value) for name in ("To", "Cc") for value in message.get_all(name, [])]
    ):
        return False
    named = _addresses(
        [
            str(value)
            for name in RECIPIENT_HEADERS
            for value in message.get_all(name, [])
        ]
    )
    return mailbox.public_address in named
