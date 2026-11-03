"""Anonymization and export of what came in by email."""

import io
import json
import zipfile

import pytest
from django.core.files.base import ContentFile

from apps.contacts.gdpr import anonymize_contact, build_contact_export
from apps.email_channel.models import InboundEmail
from apps.organizations.models import OTPCode
from apps.tickets.models import TicketMessage, WidgetSession
from tests.factories import (
    ContactFactory,
    InboundEmailFactory,
    MailboxFactory,
    OrganizationFactory,
    TicketFactory,
    TicketMessageFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]

ANN = "ann@example.org"


def _with_raw(inbound: InboundEmail) -> InboundEmail:
    inbound.raw.save("raw.eml", ContentFile(b"From: ann@example.org\r\n\r\nHi"))
    return inbound


@pytest.fixture
def mailbox():
    return MailboxFactory()


@pytest.fixture
def contact(mailbox):
    return ContactFactory(organization=mailbox.organization, email=ANN)


def test_anonymization_deletes_the_contacts_mail_and_its_traces(
    mailbox, contact, django_capture_on_commit_callbacks
):
    ticket = TicketFactory(organization=mailbox.organization, contact=contact)
    message = TicketMessageFactory(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        channel=TicketMessage.Channel.EMAIL,
        external_id="<CAF0rwd-1@mail.example.org>",
        external_sender="Ann <ann@example.org>",
    )
    # A colleague in copy, on the contact's ticket.
    on_ticket = _with_raw(
        InboundEmailFactory(mailbox=mailbox, ticket=ticket, sender="bob@example.net")
    )
    # Ignored mail from the contact's address, which made no ticket.
    ignored = _with_raw(
        InboundEmailFactory(
            mailbox=mailbox, sender=ANN, status=InboundEmail.Status.IGNORED
        )
    )
    elsewhere = _with_raw(InboundEmailFactory(sender=ANN))
    storage = on_ticket.raw.storage
    files = [on_ticket.raw.name, ignored.raw.name]

    with django_capture_on_commit_callbacks(execute=True):
        anonymize_contact(contact)

    assert list(InboundEmail.objects.all()) == [elsewhere]
    assert not any(storage.exists(name) for name in files)
    assert storage.exists(elsewhere.raw.name)
    message.refresh_from_db()
    assert (message.external_id, message.external_sender) == ("", "")
    assert message.channel == TicketMessage.Channel.EMAIL

    contact.refresh_from_db()
    updated_at = contact.updated_at
    anonymize_contact(contact)
    contact.refresh_from_db()
    assert contact.updated_at == updated_at
    assert list(InboundEmail.objects.all()) == [elsewhere]


def test_the_export_tells_the_channel_and_holds_no_mail(mailbox, contact):
    ticket = TicketFactory(organization=mailbox.organization, contact=contact)
    TicketMessageFactory(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        channel=TicketMessage.Channel.EMAIL,
        external_id="<CAF0rwd-1@mail.example.org>",
    )
    _with_raw(InboundEmailFactory(mailbox=mailbox, ticket=ticket, sender=ANN))

    archive = zipfile.ZipFile(io.BytesIO(build_contact_export(contact)))

    assert sorted(archive.namelist()) == ["contact.json", "tickets.csv", "tickets.json"]
    [exported] = json.loads(archive.read("tickets.json"))
    assert [message["channel"] for message in exported["messages"]] == ["email"]
    assert "CAF0rwd-1" not in archive.read("tickets.json").decode()


def test_anonymization_clears_the_contacts_address_as_a_mail_sender(mailbox, contact):
    # A reply from the contact's address, on a ticket that isn't theirs.
    elsewhere_in_org = TicketMessageFactory(
        ticket__organization=mailbox.organization,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        external_sender='"Ann" <Ann@Example.org>',
    )
    in_another_org = TicketMessageFactory(
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        external_sender="ann@example.org",
    )

    anonymize_contact(contact)

    elsewhere_in_org.refresh_from_db()
    in_another_org.refresh_from_db()
    assert elsewhere_in_org.external_sender == ""
    assert in_another_org.external_sender == "ann@example.org"


def test_anonymization_deletes_the_contacts_widget_codes(mailbox, contact):
    org = mailbox.organization
    own_session = WidgetSession.objects.create(
        organization=org, contact=contact, email="ann@other.example"
    )
    stranger = WidgetSession.objects.create(organization=org, email=ANN)
    elsewhere = OrganizationFactory()
    kept = [
        OTPCode.generate(ANN),  # A login code: the address may be an agent's too.
        OTPCode.generate(
            ANN,
            purpose=OTPCode.Purpose.WIDGET_EMAIL,
            organization=elsewhere,
            widget_session=WidgetSession.objects.create(organization=elsewhere),
        ),
    ]
    for session in (own_session, stranger):
        OTPCode.generate(
            session.email,
            purpose=OTPCode.Purpose.WIDGET_EMAIL,
            organization=org,
            widget_session=session,
        )

    anonymize_contact(contact)

    assert set(OTPCode.objects.values_list("pk", flat=True)) == {otp.pk for otp in kept}
