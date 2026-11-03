"""Which mailbox, or which ticket, an inbound mail is for."""

import pytest

from apps.email_channel.recipients import resolve
from apps.email_channel.tokens import reply_address
from tests.email_channel.mails import build, fixture_bytes, parse
from tests.factories import MailboxFactory, TicketFactory

pytestmark = pytest.mark.django_db


def test_reply_token_wins_and_gives_the_tickets_mailbox():
    MailboxFactory(public_address="support@acme.example.com")
    ticket = TicketFactory(mailbox=MailboxFactory())
    address = reply_address(ticket)
    # Mail servers may change the case of an address.
    raw = build(To="support@acme.example.com", Cc=address.upper())

    recipient = resolve(parse(raw))

    assert recipient.ticket == ticket
    assert recipient.mailbox == ticket.mailbox
    assert recipient.address == address


def test_forwarded_mail_is_found_by_delivered_to_while_to_stays_public():
    mailbox = MailboxFactory(local_part="acme-fixture01")
    MailboxFactory(public_address="support@acme.example.com")

    recipient = resolve(parse(fixture_bytes("forwarded_by_gmail.eml")))

    assert recipient.mailbox == mailbox
    assert recipient.ticket is None
    assert recipient.address == mailbox.inbound_address


def test_envelope_recipient_comes_before_the_headers():
    mailbox = MailboxFactory()
    MailboxFactory(public_address="support@acme.example.com")

    recipient = resolve(
        parse(build(), envelope_recipient=mailbox.inbound_address.upper())
    )

    assert recipient.mailbox == mailbox


def test_public_address_matches_in_to():
    mailbox = MailboxFactory(public_address="support@acme.example.com")

    recipient = resolve(parse(build(To="Acme <Support@Acme.example.com>")))

    assert recipient.mailbox == mailbox
    assert recipient.address == "support@acme.example.com"


def test_an_inactive_mailbox_is_not_a_recipient():
    MailboxFactory(public_address="support@acme.example.com", is_active=False)

    assert resolve(parse(build())) is None


def test_a_forged_token_is_not_a_recipient():
    ticket = TicketFactory(mailbox=MailboxFactory())
    other = TicketFactory(mailbox=MailboxFactory())
    signature = reply_address(other).split("@")[0].split(".")[1]
    forged = f"reply+{ticket.id.hex}.{signature}@in.example.com"

    assert resolve(parse(build(To=forged))) is None


def test_a_regenerated_address_is_rejected_even_with_the_public_address_in_to():
    # Headers are the sender's to write: only the provider's envelope is trusted.
    mailbox = MailboxFactory(public_address="support@acme.example.com")
    previous = mailbox.inbound_address
    mailbox.regenerate_address()

    assert resolve(parse(build(), envelope_recipient=previous)) is None


def test_the_envelope_wins_over_a_reply_token_in_the_headers():
    other_ticket = TicketFactory(mailbox=MailboxFactory())
    mailbox = MailboxFactory()
    raw = build(Cc=reply_address(other_ticket))

    recipient = resolve(parse(raw, envelope_recipient=mailbox.inbound_address))

    assert recipient.mailbox == mailbox
    assert recipient.ticket is None
