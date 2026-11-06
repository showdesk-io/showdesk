"""From a signed webhook to a ticket: the whole inbound pipeline (design §4)."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.contacts.gdpr import PREVIOUS_TICKET_KEY
from apps.email_channel.models import InboundEmail
from apps.email_channel.tasks import process_inbound_email
from apps.email_channel.thread_matching import Match
from apps.email_channel.tokens import reply_address
from apps.tickets.models import Ticket, TicketAttachment, TicketMessage
from tests.email_channel.mails import build, fixture_bytes
from tests.email_channel.postal import post_to_postal, postal_payload
from tests.factories import (
    AdminFactory,
    ContactFactory,
    InboundEmailFactory,
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

    def _deliver(
        raw: bytes,
        *,
        rcpt_to: str = INBOUND_ADDRESS,
        mail_from: str = "customer@example.org",
    ) -> InboundEmail:
        payload = postal_payload(raw, rcpt_to=rcpt_to, mail_from=mail_from)
        with django_capture_on_commit_callbacks(execute=True):
            response = post_to_postal(payload, postal_key)
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


@pytest.mark.parametrize("mail_sent", ["resolved", "conversation_link"])
def test_a_reply_to_the_resolved_or_link_mail_lands_on_its_ticket(
    mailbox, agent, deliver, mail_sent
):
    from apps.email_channel.tasks import send_conversation_link
    from apps.tickets.tasks import send_ticket_resolved_email

    contact = ContactFactory(organization=mailbox.organization, email="ann@example.org")
    ticket = TicketFactory(
        organization=mailbox.organization,
        mailbox=mailbox,
        contact=contact,
        requester=None,
        requester_email=contact.email,
        source=Ticket.Source.EMAIL,
        status=Ticket.Status.RESOLVED,
        resolved_at=timezone.now(),
    )
    TicketMessageFactory(ticket=ticket, external_id="<sent-1@in.example.com>")
    mail.outbox.clear()
    if mail_sent == "resolved":
        send_ticket_resolved_email(ticket.id)
    else:
        send_conversation_link(str(ticket.id))
    [sent] = mail.outbox
    assert sent.extra_headers["In-Reply-To"] == "<sent-1@in.example.com>"

    # Answered from a client keeping In-Reply-To only, nor the [SD-123].
    inbound = deliver(
        build(
            Subject="Re: thanks",
            Message_ID="<9@mail.example.org>",
            In_Reply_To=sent.extra_headers["Message-ID"],
        )
    )

    assert inbound.ticket == ticket


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


def _deep_mail(depth: int = 3000) -> bytes:
    """A mail nested deeper than Python's parser can recurse."""
    opening = b"".join(
        b'Content-Type: multipart/mixed; boundary="b%d"\r\n\r\n--b%d\r\n' % (i, i)
        for i in range(depth)
    )
    closing = b"".join(b"--b%d--\r\n" % i for i in reversed(range(depth)))
    return (
        b"From: ann@example.org\r\nMessage-ID: <deep@example.org>\r\n"
        b"MIME-Version: 1.0\r\n"
        + opening
        + b"Content-Type: text/plain\r\n\r\nHi\r\n"
        + closing
    )


def test_a_reply_address_is_read_from_the_stored_envelope(agent, mailbox, deliver):
    # A widget ticket: no mailbox, so the row has none either.
    ticket = TicketFactory(organization=mailbox.organization, reference="OLD-1")

    inbound = deliver(build(body="By mail"), rcpt_to=reply_address(ticket))

    assert inbound.mailbox is None
    assert inbound.ticket == ticket
    assert inbound.ticket_message.body == "By mail"


def test_a_replayed_row_lands_once(mailbox, agent, deliver):
    inbound = deliver(build())
    InboundEmail.objects.filter(pk=inbound.pk).update(status=InboundEmail.Status.FAILED)

    process_inbound_email.delay(str(inbound.id))

    inbound.refresh_from_db()
    assert (inbound.status, inbound.reason) == ("ignored", "duplicate")
    assert TicketMessage.objects.count() == 1


def test_the_ticket_a_row_landed_on_is_no_reply_address(mailbox, agent, deliver):
    raw = fixture_bytes("gmail_forwarding_confirmation.eml").replace(
        b"acme-fixture01", b"acme-abc"
    )
    with mock.patch("apps.email_channel.tasks.process_inbound_email.delay"):
        inbound = deliver(raw)
    InboundEmail.objects.filter(pk=inbound.pk).update(
        ticket=TicketFactory(organization=mailbox.organization, reference="OLD-1")
    )

    process_inbound_email.delay(str(inbound.id))

    inbound.refresh_from_db()
    assert inbound.reason == "forwarding_confirmation"


def test_a_missing_raw_mail_fails_without_retrying(mailbox, agent, deliver):
    with mock.patch("apps.email_channel.tasks.process_inbound_email.delay"):
        inbound = deliver(build())
    inbound.raw.storage.delete(inbound.raw.name)

    process_inbound_email.delay(str(inbound.id))

    inbound.refresh_from_db()
    # A retry would have made it "exception".
    assert (inbound.status, inbound.reason) == ("failed", "raw_missing")


def test_a_mail_too_deep_to_parse_is_kept_rejected(mailbox, postal_key):
    response = post_to_postal(postal_payload(_deep_mail()), postal_key)

    assert response.status_code == 200
    inbound = InboundEmail.objects.get()
    assert (inbound.status, inbound.reason) == ("rejected", "unparseable")
    assert inbound.message_id.endswith("@hashed.invalid>")
    assert inbound.raw.read() == _deep_mail()


def test_a_stored_mail_too_deep_to_parse_fails_without_retrying(mailbox):
    inbound = InboundEmailFactory(mailbox=mailbox)
    inbound.raw.save("raw.eml", ContentFile(_deep_mail()))

    process_inbound_email.delay(str(inbound.id))

    inbound.refresh_from_db()
    assert (inbound.status, inbound.reason) == ("failed", "unparseable")


def test_files_are_stored_before_and_deleted_if_the_write_fails(
    mailbox, agent, deliver, tmp_path
):
    with mock.patch(
        "apps.email_channel.pipeline.Ticket.objects.create",
        side_effect=RuntimeError("boom"),
    ):
        inbound = deliver(fixture_bytes("attachments.eml"))

    inbound.refresh_from_db()
    assert inbound.status == "failed"
    # Uploads go to tmp_path (the local_media fixture): stored, then deleted.
    assert (tmp_path / "attachments").is_dir()
    assert not list((tmp_path / "attachments").rglob("*.*"))


def test_a_ticket_anonymized_before_its_lock_is_no_match(mailbox, agent, deliver):
    contact = ContactFactory(organization=mailbox.organization, is_anonymized=True)
    ticket = TicketFactory(
        organization=mailbox.organization, contact=contact, reference="OLD-1"
    )

    with mock.patch(
        "apps.email_channel.pipeline.find_ticket", return_value=Match(ticket, "headers")
    ):
        inbound = deliver(build())

    assert inbound.ticket != ticket
    assert ticket.messages.count() == 0


def test_a_lost_notification_is_logged_as_such(mailbox, agent, deliver, caplog):
    with mock.patch(
        "apps.tickets.tasks.send_ticket_created_email.delay",
        side_effect=ConnectionError("broker down"),
    ):
        inbound = deliver(build())

    assert inbound.status == InboundEmail.Status.PROCESSED
    assert "Couldn't queue" in caplog.text
    assert "Inbound mail" not in caplog.text


# Forwarding from the public address (customers may reply to it once proven)

# The envelope sender a forward gets from the public address's own server.
FORWARDER = "support+caf_=acme-abc=in.example.com@Acme.Example.com"


def test_a_forward_from_the_public_address_lets_admins_have_customers_reply_to_it(
    mailbox, agent, deliver, settings
):
    from apps.organizations.models import OrganizationDomain
    from apps.tickets.tasks import send_ticket_reply_email

    settings.SENDING_DOMAIN_PROVIDER = "manual"
    OrganizationDomain.objects.create(
        organization=mailbox.organization,
        domain="acme.example.com",
        is_sending=True,
        status=OrganizationDomain.Status.VERIFIED,
        sending_status=OrganizationDomain.SendingStatus.VERIFIED,
        sending_provider_ref="acme.example.com",
        sending_provider="manual",
    )

    def replied_to(ticket):
        mail.outbox.clear()
        reply = TicketMessageFactory(ticket=ticket, author=agent, channel="agent")
        send_ticket_reply_email(reply.id)
        [sent] = mail.outbox
        return sent

    # Anyone can write To: support@…, not deliver from its domain's server.
    deliver(build(Message_ID="<0@mail.example.org>"))
    mailbox.refresh_from_db()
    assert mailbox.forwarding_verified_at is None

    first = deliver(build(), mail_from=FORWARDER)
    mailbox.refresh_from_db()
    assert mailbox.forwarding_verified_at == first.received_at
    # The proof alone changes nothing: an admin chooses.
    assert replied_to(first.ticket).reply_to == [reply_address(first.ticket)]

    mailbox.reply_to_public_address = True
    mailbox.save()
    sent = replied_to(first.ticket)
    assert sent.from_email.endswith("<support@acme.example.com>")
    assert sent.reply_to == ["support@acme.example.com"]

    # The customer answers the public address, which forwards it here again.
    answer = deliver(
        build(
            Subject=f"Re: {sent.subject}",
            Message_ID="<2@mail.example.org>",
            In_Reply_To=sent.extra_headers["Message-ID"],
            body="Still broken",
        ),
        mail_from=FORWARDER,
    )
    assert answer.ticket == first.ticket
    assert answer.ticket_message.body == "Still broken"
    mailbox.refresh_from_db()
    assert mailbox.forwarding_verified_at == first.received_at  # Within the hour.

    # Turned off, it stays off whatever comes in next.
    mailbox.reply_to_public_address = False
    mailbox.save()
    deliver(build(Message_ID="<3@mail.example.org>"), mail_from=FORWARDER)
    assert replied_to(first.ticket).reply_to == [reply_address(first.ticket)]


def test_only_a_processed_mail_through_the_inbound_address_proves_forwarding(
    mailbox, agent, deliver
):
    ticket = TicketFactory(
        organization=mailbox.organization, mailbox=mailbox, reference="OLD-1"
    )
    unproven = [
        deliver(
            build(Auto_Submitted="auto-replied", Message_ID="<a@x.org>"),
            mail_from=FORWARDER,
        ),
        deliver(
            build(Message_ID="<b@x.org>"),
            rcpt_to=reply_address(ticket),
            mail_from=FORWARDER,
        ),
        deliver(
            build(
                Message_ID="<c@x.org>", To=INBOUND_ADDRESS, Cc=mailbox.public_address
            ),
            mail_from=FORWARDER,
        ),
        deliver(
            build(Message_ID="<d@x.org>", To="someone@example.org"),
            mail_from=FORWARDER,
        ),
    ]
    stored = InboundEmailFactory(
        mailbox=mailbox, envelope_recipient="", envelope_sender=FORWARDER.lower()
    )
    stored.raw.save("raw.eml", ContentFile(build(Message_ID="<e@x.org>")))
    process_inbound_email.delay(str(stored.id))
    stored.refresh_from_db()

    assert [row.status for row in unproven[1:]] == ["processed"] * 3
    assert unproven[0].status == "ignored"
    assert stored.status == "processed"
    mailbox.refresh_from_db()
    assert mailbox.forwarding_verified_at is None
