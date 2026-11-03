"""Which ticket an inbound mail continues, if any (design §4.3)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.contacts.gdpr import PREVIOUS_TICKET_KEY, _kept_metadata
from apps.email_channel.recipients import Recipient
from apps.email_channel.thread_matching import (
    ReopenOutcome,
    apply_reopen_rule,
    find_ticket,
    is_forward,
)
from apps.email_channel.tokens import reply_address
from apps.tickets.models import Ticket
from tests.email_channel.mails import build, parse
from tests.factories import (
    ContactFactory,
    MailboxFactory,
    TicketFactory,
    TicketMessageFactory,
)

pytestmark = pytest.mark.django_db

ANN = "ann@example.org"


@pytest.fixture
def mailbox():
    return MailboxFactory(public_address="support@acme.example.com")


@pytest.fixture
def ticket(mailbox):
    contact = ContactFactory(organization=mailbox.organization, email=ANN)
    return TicketFactory(
        organization=mailbox.organization,
        contact=contact,
        mailbox=mailbox,
        reference="SD-0012",
    )


def _find(raw: bytes, mailbox, *, sender: str = ANN, to_ticket=None):
    recipient = Recipient(
        mailbox=mailbox,
        ticket=to_ticket,
        address=reply_address(to_ticket) if to_ticket else mailbox.inbound_address,
    )
    return find_ticket(parse(raw), recipient, sender, mailbox.organization)


def test_in_reply_to_a_stored_message_of_the_organization(mailbox, ticket):
    TicketMessageFactory(ticket=ticket, external_id="<sent-1@in.example.com>")

    match = _find(
        build(
            In_Reply_To="<sent-1@in.example.com>",
            References="<old@mail.example.org> <sent-1@in.example.com>",
        ),
        mailbox,
        sender="someone-else@example.net",  # Headers are enough, from anyone.
    )

    assert (match.ticket, match.by) == (ticket, "headers")


def test_the_same_header_on_another_organizations_message_is_no_match(mailbox):
    TicketMessageFactory(external_id="<sent-1@in.example.com>")

    assert _find(build(In_Reply_To="<sent-1@in.example.com>"), mailbox) is None


def test_the_reply_address_alone_is_a_match(mailbox, ticket):
    match = _find(build(), mailbox, to_ticket=ticket)

    assert (match.ticket, match.by) == (ticket, "reply_address")


def test_the_reference_in_the_subject_counts_only_from_the_contact(mailbox, ticket):
    raw = build(Subject="Re: [SD-0012] My invoice is wrong")

    match = _find(raw, mailbox)
    assert (match.ticket, match.by) == (ticket, "subject")

    assert _find(raw, mailbox, sender="mallory@example.net") is None


def test_a_forward_only_continues_by_its_headers(mailbox, ticket):
    for prefix in ("Fwd:", "TR :", "wg:", "Fw:"):
        raw = build(Subject=f"{prefix} [SD-0012] My invoice is wrong")
        assert _find(raw, mailbox) is None
        assert _find(raw, mailbox, to_ticket=ticket) is None
    assert is_forward("Re: Fwd: hello") is False


def test_an_anonymized_contacts_ticket_is_never_continued(mailbox, ticket):
    ticket.contact.is_anonymized = True
    ticket.contact.save()
    TicketMessageFactory(ticket=ticket, external_id="<sent-1@in.example.com>")

    assert _find(build(In_Reply_To="<sent-1@in.example.com>"), mailbox) is None
    assert _find(build(), mailbox, to_ticket=ticket) is None


def test_a_recently_closed_ticket_reopens(ticket, settings):
    settings.INBOUND_EMAIL_REOPEN_DAYS = 7
    now = timezone.now()
    ticket.status = Ticket.Status.CLOSED
    ticket.resolved_at = now - timedelta(days=3)
    ticket.closed_at = now - timedelta(days=2)
    ticket.save()

    assert apply_reopen_rule(ticket) == ReopenOutcome.REOPENED

    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.OPEN
    assert (ticket.resolved_at, ticket.closed_at) == (None, None)
    assert apply_reopen_rule(ticket) == ReopenOutcome.OPEN


def test_a_ticket_closed_for_longer_stays_closed_for_a_new_one(ticket, settings):
    settings.INBOUND_EMAIL_REOPEN_DAYS = 7
    ticket.status = Ticket.Status.RESOLVED
    ticket.resolved_at = timezone.now() - timedelta(days=8)
    ticket.save()

    assert apply_reopen_rule(ticket) == ReopenOutcome.EXPIRED

    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.RESOLVED
    # The new ticket names it, and anonymization keeps that: it's no personal data.
    assert _kept_metadata({PREVIOUS_TICKET_KEY: str(ticket.id)}) == {
        PREVIOUS_TICKET_KEY: str(ticket.id)
    }
    assert _kept_metadata({PREVIOUS_TICKET_KEY: "ann's old ticket"}) == {}


def test_an_id_on_several_tickets_prefers_ours_then_the_oldest(mailbox, ticket):
    other = TicketFactory(organization=mailbox.organization, reference="SD-0013")
    third = TicketFactory(organization=mailbox.organization, reference="SD-0014")
    # A customer quoting our id in their own Message-ID can't take the thread.
    TicketMessageFactory(
        ticket=other,
        author=None,
        sender_type="user",
        external_id="<sent-1@in.example.com>",
    )
    TicketMessageFactory(ticket=ticket, external_id="<sent-1@in.example.com>")
    TicketMessageFactory(ticket=third, external_id="<sent-1@in.example.com>")

    match = _find(build(In_Reply_To="<sent-1@in.example.com>"), mailbox)

    assert match.ticket == ticket
