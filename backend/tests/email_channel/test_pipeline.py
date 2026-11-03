"""From a signed webhook to a ticket: the whole inbound pipeline (design §4)."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.utils import timezone

from apps.contacts.gdpr import PREVIOUS_TICKET_KEY
from apps.email_channel.models import InboundEmail
from apps.email_channel.tasks import process_inbound_email
from apps.tickets.models import Ticket, TicketAttachment, TicketMessage
from tests.email_channel.mails import build, fixture_bytes
from tests.email_channel.postal import post_to_postal, postal_payload
from tests.factories import (
    AdminFactory,
    ContactFactory,
    MailboxFactory,
    TeamFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]

INBOUND_ADDRESS = "acme-abc@in.example.com"


@pytest.fixture(autouse=True)
def _realtime():
    """Websocket events, which need a channel layer: recorded instead."""
    with (
        mock.patch("apps.email_channel.pipeline.notify_new_ticket") as new_ticket,
        mock.patch("apps.email_channel.pipeline.notify_new_message") as new_message,
        mock.patch("apps.email_channel.pipeline.notify_ticket_update") as update,
    ):
        yield {"new_ticket": new_ticket, "new_message": new_message, "update": update}


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture
def mailbox():
    mailbox = MailboxFactory(
        local_part="acme-abc",
        public_address="support@acme.example.com",
        default_team=None,
    )
    mailbox.default_team = TeamFactory(organization=mailbox.organization)
    mailbox.save()
    return mailbox


@pytest.fixture
def agent(mailbox):
    return AdminFactory(organization=mailbox.organization, email="agent@acme.example")


@pytest.fixture
def deliver(postal_key, django_capture_on_commit_callbacks):
    """Post a mail to the signed webhook and run everything that follows."""

    def _deliver(raw: bytes, *, rcpt_to: str = INBOUND_ADDRESS) -> InboundEmail:
        with django_capture_on_commit_callbacks(execute=True):
            response = post_to_postal(postal_payload(raw, rcpt_to=rcpt_to), postal_key)
        assert response.status_code == 200
        return InboundEmail.objects.order_by("-created_at").first()

    return _deliver


@pytest.mark.parametrize(
    "name",
    [
        "forwarded_by_gmail.eml",
        "no_message_id.eml",
        "html_only.eml",
        "attachments.eml",
        "reply_gmail_en.eml",
        "reply_gmail_fr.eml",
        "reply_outlook_en.eml",
        "reply_outlook_fr.eml",
        "reply_apple_mail_en.eml",
        "reply_apple_mail_fr.eml",
        "reply_thunderbird_en.eml",
        "reply_thunderbird_fr.eml",
    ],
)
def test_each_fixture_opens_a_ticket(name, mailbox, agent, deliver, _realtime):
    inbound = deliver(fixture_bytes(name))

    assert (inbound.status, inbound.reason) == (InboundEmail.Status.PROCESSED, "")
    ticket, message = inbound.ticket, inbound.ticket_message
    assert ticket.source == Ticket.Source.EMAIL
    assert ticket.mailbox == mailbox
    assert ticket.assigned_team == mailbox.default_team
    assert ticket.contact.email == ticket.requester_email == inbound.sender
    # A From is only a claim.
    assert ticket.sender_verified is False
    assert (message.channel, message.sender_type) == ("email", "user")
    assert message.author is None
    assert message.external_id == inbound.message_id
    assert message.body and message.body == ticket.description
    assert inbound.processed_at is not None
    _realtime["new_ticket"].assert_called_once_with(ticket)
    _realtime["new_message"].assert_called_once_with(message)
    [notification] = mail.outbox
    assert notification.to == [agent.email]


def test_files_are_kept_and_the_dropped_ones_named(mailbox, agent, deliver):
    inbound = deliver(fixture_bytes("attachments.eml"))

    message = inbound.ticket_message
    files = TicketAttachment.objects.filter(message=message).order_by("filename")
    assert [(f.filename, f.uploaded_by, f.ticket) for f in files] == [
        ("notes.txt", None, inbound.ticket),
        ("screen.png", None, inbound.ticket),
    ]
    assert files[1].file.read().startswith(b"\x89PNG")
    assert message.body == (
        "Here are the files.\n\nAttachments not kept: setup.exe (file type not allowed)."
    )


def test_markup_in_a_mail_stays_text(mailbox, agent, deliver):
    inbound = deliver(build(body="Look: <script>alert(1)</script>"))

    assert inbound.ticket_message.body == "Look: <script>alert(1)</script>"
    html, _ = mail.outbox[0].alternatives[0]
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_replay_adds_no_second_message(mailbox, agent, deliver):
    raw = build()
    inbound = deliver(raw)
    deliver(raw)
    process_inbound_email.delay(str(inbound.id))

    assert TicketMessage.objects.count() == 1
    assert InboundEmail.objects.count() == 1


def test_a_forward_keeps_its_quoted_part(mailbox, agent, deliver):
    body = (
        "FYI\n\nOn Mon, Nov 2, 2026 at 10:00 AM Bob wrote:\n> The printer is on fire."
    )

    inbound = deliver(build(Subject="Fwd: printer", body=body))

    assert inbound.ticket_message.body == body


def test_a_reply_reopens_a_recently_closed_ticket(mailbox, agent, deliver, _realtime):
    contact = ContactFactory(organization=mailbox.organization, email="ann@example.org")
    ticket = TicketFactory(
        organization=mailbox.organization,
        reference="OLD-1",
        contact=contact,
        status=Ticket.Status.CLOSED,
        closed_at=timezone.now() - timedelta(days=1),
    )
    TicketMessageFactory(ticket=ticket, external_id="<sent-1@in.example.com>")

    inbound = deliver(build(In_Reply_To="<sent-1@in.example.com>", body="Again"))

    ticket.refresh_from_db()
    assert inbound.ticket == ticket
    assert ticket.status == Ticket.Status.OPEN
    assert inbound.ticket_message.body == "Again"
    _realtime["new_ticket"].assert_not_called()
    _realtime["update"].assert_called_once_with(ticket)
    # The agents hear of the reply, not of a new ticket.
    assert "replied" in mail.outbox[0].body


def test_a_reply_to_a_ticket_closed_long_ago_opens_one_naming_it(
    mailbox, agent, deliver, settings
):
    settings.INBOUND_EMAIL_REOPEN_DAYS = 7
    old = TicketFactory(
        organization=mailbox.organization,
        reference="OLD-1",
        status=Ticket.Status.CLOSED,
        closed_at=timezone.now() - timedelta(days=30),
    )
    TicketMessageFactory(ticket=old, external_id="<sent-1@in.example.com>")

    inbound = deliver(build(In_Reply_To="<sent-1@in.example.com>"))

    assert inbound.ticket != old
    assert inbound.ticket.context_metadata == {PREVIOUS_TICKET_KEY: str(old.id)}
    old.refresh_from_db()
    assert old.status == Ticket.Status.CLOSED


def test_a_third_party_on_a_thread_keeps_the_tickets_contact(mailbox, agent, deliver):
    contact = ContactFactory(organization=mailbox.organization, email="ann@example.org")
    ticket = TicketFactory(
        organization=mailbox.organization, contact=contact, reference="OLD-1"
    )
    TicketMessageFactory(ticket=ticket, external_id="<sent-1@in.example.com>")

    inbound = deliver(
        build(
            From="Bob Colleague <bob@example.net>",
            In_Reply_To="<sent-1@in.example.com>",
        )
    )

    ticket.refresh_from_db()
    assert inbound.ticket == ticket
    assert ticket.contact == contact
    message = inbound.ticket_message
    assert message.external_sender == '"Bob Colleague" <bob@example.net>'
    assert message.sender_name == "Bob Colleague"
    # Nobody's contact is created for a mere participant.
    assert not contact.organization.contacts.filter(email="bob@example.net").exists()


def test_mail_from_staff_has_no_contact(mailbox, agent, deliver):
    UserFactory(organization=mailbox.organization, email="helper@acme.example")

    inbound = deliver(build(From="Helper <HELPER@acme.example>"))

    assert inbound.status == InboundEmail.Status.PROCESSED
    assert inbound.ticket.contact is None
    assert not mailbox.organization.contacts.exists()


def test_mail_from_an_anonymized_address_has_no_contact(mailbox, agent, deliver):
    anonymized = ContactFactory(
        organization=mailbox.organization,
        email="anonymized-1@example.invalid",
        is_anonymized=True,
    )

    inbound = deliver(build(From=anonymized.email))

    assert inbound.status == InboundEmail.Status.PROCESSED
    assert inbound.ticket.contact is None


def test_a_failure_is_recorded_then_retried(mailbox, agent, deliver, settings):
    with mock.patch(
        "apps.email_channel.pipeline.extract_body", side_effect=RuntimeError("boom")
    ):
        inbound = deliver(build())

    inbound.refresh_from_db()
    assert (inbound.status, inbound.reason) == (InboundEmail.Status.FAILED, "exception")
    assert not Ticket.objects.exists()

    process_inbound_email.delay(str(inbound.id))

    inbound.refresh_from_db()
    assert inbound.status == InboundEmail.Status.PROCESSED
    assert TicketMessage.objects.count() == 1


def test_the_gmail_confirmation_is_read_from_the_stored_envelope(
    mailbox, agent, deliver
):
    raw = fixture_bytes("gmail_forwarding_confirmation.eml").replace(
        b"acme-fixture01", b"acme-abc"
    )

    # The headers name the inbound address, but the provider delivered it to the
    # public one: anyone can do that.
    forged = deliver(raw, rcpt_to="support@acme.example.com")
    assert forged.status == InboundEmail.Status.PROCESSED
    mailbox.refresh_from_db()
    assert mailbox.forwarding_confirmation == {}

    genuine = deliver(raw.replace(b"<confirmation-1@", b"<confirmation-2@"))
    assert (genuine.status, genuine.reason) == ("ignored", "forwarding_confirmation")
    mailbox.refresh_from_db()
    assert mailbox.forwarding_confirmation["code"] == "614028937"


def test_the_providers_spam_verdict_is_read_from_the_stored_row(mailbox, deliver):
    inbound = deliver(build(X_Postal_Spam="yes"))

    assert inbound.spam_detected is True
    assert (inbound.status, inbound.reason) == ("ignored", "spam")
    assert not Ticket.objects.exists()
