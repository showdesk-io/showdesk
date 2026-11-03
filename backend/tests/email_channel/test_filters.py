"""Which inbound mails are ignored, and why (design §4.2)."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.db.models import F
from django.utils import timezone

from apps.email_channel.filters import classify
from apps.email_channel.inbound import store
from apps.email_channel.models import InboundEmail
from apps.email_channel.recipients import resolve
from apps.tickets.models import TicketMessage
from tests.email_channel.mails import build, fixture_bytes, parse
from tests.factories import (
    AdminFactory,
    InboundEmailFactory,
    MailboxFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]

OUR_MESSAGE_ID = "<0f2a4c1e-5b6d-4e7f-8a9b-0c1d2e3f4a5b@in.example.com>"


@pytest.fixture(autouse=True)
def _no_queue():
    with mock.patch("apps.email_channel.tasks.process_inbound_email.delay"):
        yield


@pytest.fixture
def mailbox():
    return MailboxFactory(
        local_part="acme-fixture01", public_address="support@acme.example.com"
    )


def run(raw: bytes, *, envelope_recipient: str | None = None):
    """Store a mail as it arrives, then classify it as the pipeline will."""
    message = parse(raw, envelope_recipient=envelope_recipient)
    inbound = store(message, raw=raw)
    return classify(message, inbound, resolve(message)), inbound


def test_a_gmail_forwarding_confirmation_goes_to_the_active_admins_only(
    mailbox, django_capture_on_commit_callbacks
):
    admin = AdminFactory(organization=mailbox.organization)
    AdminFactory(organization=mailbox.organization, is_active=False)
    UserFactory(organization=mailbox.organization)  # An agent.
    AdminFactory()  # Another organization's.

    with django_capture_on_commit_callbacks(execute=True):
        verdict, _ = run(
            fixture_bytes("gmail_forwarding_confirmation.eml"),
            envelope_recipient=mailbox.inbound_address,
        )

    assert (verdict.status, verdict.reason) == (
        InboundEmail.Status.IGNORED,
        "forwarding_confirmation",
    )
    mailbox.refresh_from_db()
    confirmation = mailbox.forwarding_confirmation
    assert confirmation["code"] == "614028937"
    assert confirmation["url"] == (
        "https://mail-settings.google.com/mail/vf-%5BANGjdJ8example%5D-AbCdEfGh"
    )
    assert confirmation["detected_at"]
    assert [message.to for message in mail.outbox] == [[admin.email]]
    assert "614028937" in mail.outbox[0].body


def test_a_confirmation_counts_only_delivered_to_the_inbound_address(mailbox):
    # Anyone can write to the public address with a forged From.
    raw = fixture_bytes("gmail_forwarding_confirmation.eml")

    verdict, _ = run(raw, envelope_recipient="support@acme.example.com")

    assert verdict is None
    mailbox.refresh_from_db()
    assert mailbox.forwarding_confirmation == {}


def test_a_confirmation_keeps_no_link_outside_google(mailbox):
    raw = fixture_bytes("gmail_forwarding_confirmation.eml").replace(
        b"https://mail-settings.google.com/", b"https://mail-settings.example.com/"
    )

    verdict, _ = run(raw, envelope_recipient=mailbox.inbound_address)

    assert verdict.reason == "forwarding_confirmation"
    mailbox.refresh_from_db()
    assert mailbox.forwarding_confirmation["url"] == ""
    assert mailbox.forwarding_confirmation["code"] == "614028937"


def test_auto_replies_are_ignored_but_not_auto_submitted_no(mailbox):
    verdict, _ = run(build(Auto_Submitted="auto-replied"))
    assert verdict.reason == "auto_reply"

    verdict, _ = run(build(Message_ID="<2@mail.example.org>", X_Autoreply="yes"))
    assert verdict.reason == "auto_reply"

    verdict, _ = run(build(Message_ID="<3@mail.example.org>", Auto_Submitted="no"))
    assert verdict is None


def test_bulk_mail_is_ignored(mailbox):
    verdict, _ = run(build(Precedence="bulk"))
    assert verdict.reason == "bulk"

    verdict, _ = run(
        build(Message_ID="<2@mail.example.org>", List_Id="<news.example.net>")
    )
    assert verdict.reason == "bulk"


def test_a_bounce_marks_our_message_failed_in_the_mailboxs_organization_only(
    mailbox,
):
    ours = TicketMessageFactory(
        ticket__organization=mailbox.organization,
        external_id=OUR_MESSAGE_ID,
        email_delivery_status=TicketMessage.DeliveryStatus.SENT,
    )
    elsewhere = TicketMessageFactory(
        external_id=OUR_MESSAGE_ID,
        email_delivery_status=TicketMessage.DeliveryStatus.SENT,
    )

    # It also says Auto-Submitted, as many bounces do: it is still a bounce.
    verdict, _ = run(
        fixture_bytes("bounce.eml"), envelope_recipient=mailbox.inbound_address
    )

    assert verdict.reason == "bounce"
    ours.refresh_from_db()
    elsewhere.refresh_from_db()
    assert ours.email_delivery_status == TicketMessage.DeliveryStatus.FAILED
    assert elsewhere.email_delivery_status == TicketMessage.DeliveryStatus.SENT


def test_a_delay_report_is_ignored_and_marks_nothing(mailbox):
    ours = TicketMessageFactory(
        ticket__organization=mailbox.organization,
        external_id=OUR_MESSAGE_ID,
        email_delivery_status=TicketMessage.DeliveryStatus.SENT,
    )
    raw = fixture_bytes("bounce.eml").replace(b"Action: failed", b"Action: delayed")

    verdict, _ = run(raw)

    assert verdict.reason == "bounce"
    ours.refresh_from_db()
    assert ours.email_delivery_status == TicketMessage.DeliveryStatus.SENT


def test_a_bounce_never_marks_a_customers_message(mailbox):
    # A customer's own Message-ID, quoted in a forged bounce.
    theirs = TicketMessageFactory(
        ticket__organization=mailbox.organization,
        sender_type=TicketMessage.SenderType.USER,
        author=None,
        external_id=OUR_MESSAGE_ID,
    )

    verdict, _ = run(fixture_bytes("bounce.eml"))

    assert verdict.reason == "bounce"
    theirs.refresh_from_db()
    assert theirs.email_delivery_status == ""


def test_mail_from_our_own_domain_is_a_loop(mailbox):
    verdict, _ = run(build(From="Acme <reply+abc@in.example.com>"))

    assert verdict.reason == "loop"


def test_the_providers_spam_verdict_is_followed(mailbox):
    raw = build()
    message = parse(raw)
    message.spam_detected = True
    inbound = store(message, raw=raw)

    verdict = classify(message, inbound, resolve(message))

    assert verdict.reason == "spam"


def test_rate_limit_counts_the_last_hour_for_the_sender_and_mailbox(mailbox, settings):
    settings.INBOUND_EMAIL_RATE_LIMIT_PER_HOUR = 2
    now = timezone.now()
    InboundEmailFactory(mailbox=mailbox, sender="ann@example.org")
    InboundEmailFactory(
        mailbox=mailbox,
        sender="ann@example.org",
        received_at=now - timedelta(hours=2),
    )
    InboundEmailFactory(mailbox=MailboxFactory(), sender="ann@example.org")
    InboundEmailFactory(mailbox=mailbox, sender="bob@example.org")

    verdict, _ = run(build())
    assert verdict is None

    raw = build(Message_ID="<2@mail.example.org>")
    verdict, inbound = run(raw)
    assert verdict.reason == "rate_limited"

    # A replay hours later gives the same answer: the hour is the mail's own.
    InboundEmail.objects.update(received_at=F("received_at") - timedelta(hours=3))
    inbound.refresh_from_db()
    message = parse(raw)
    assert classify(message, inbound, resolve(message)).reason == "rate_limited"


def test_a_confirmation_link_with_a_disguised_host_is_dropped(mailbox):
    for index, url in enumerate(
        (
            b"https://evil.example\\@mail.google.com/x",
            b"https://user@mail.google.com/x",
            b"https://mail.google.com:8443/x",
        )
    ):
        raw = fixture_bytes("gmail_forwarding_confirmation.eml").replace(
            b"https://mail-settings.google.com/mail/vf-%5BANGjdJ8example%5D-AbCdEfGh",
            url,
        )
        message_id = b"<disguised-%d@google.com>" % index
        raw = raw.replace(b"<confirmation-1@google.com>", message_id)

        run(raw, envelope_recipient=mailbox.inbound_address)

        mailbox.refresh_from_db()
        assert mailbox.forwarding_confirmation["url"] == ""


def test_confirmations_are_rate_limited_and_mailed_once_in_ten_minutes(
    mailbox, settings, django_capture_on_commit_callbacks
):
    AdminFactory(organization=mailbox.organization)
    raw = fixture_bytes("gmail_forwarding_confirmation.eml")

    with django_capture_on_commit_callbacks(execute=True):
        for index in range(3):
            message_id = b"<confirmation-%d@google.com>" % index
            verdict, _ = run(
                raw.replace(b"<confirmation-1@google.com>", message_id),
                envelope_recipient=mailbox.inbound_address,
            )
            assert verdict.reason == "forwarding_confirmation"
    assert len(mail.outbox) == 1

    settings.INBOUND_EMAIL_RATE_LIMIT_PER_HOUR = 3
    mailbox.forwarding_confirmation = {}
    mailbox.save()
    verdict, _ = run(
        raw.replace(b"<confirmation-1@google.com>", b"<confirmation-9@google.com>"),
        envelope_recipient=mailbox.inbound_address,
    )
    assert verdict.reason == "rate_limited"
    mailbox.refresh_from_db()
    assert mailbox.forwarding_confirmation == {}


def test_a_mailbox_takes_a_bounded_number_of_mails_an_hour(mailbox, settings):
    settings.INBOUND_EMAIL_MAILBOX_RATE_LIMIT_PER_HOUR = 2
    InboundEmailFactory(mailbox=mailbox, sender="bob@example.org")
    InboundEmailFactory(mailbox=MailboxFactory(), sender="carol@example.org")

    verdict, _ = run(build())
    assert verdict is None

    verdict, _ = run(build(Message_ID="<2@mail.example.org>", From="d@example.net"))
    assert verdict.reason == "mailbox_rate_limited"


def test_mail_from_the_organizations_own_address_is_a_loop(mailbox):
    verdict, _ = run(build(From="Acme <Support@Acme.example.com>"))

    assert verdict.reason == "loop"


def test_a_message_id_already_on_a_ticket_of_the_organization_is_a_duplicate(
    mailbox,
):
    # Sent to the reply address and to the inbound address at once.
    TicketMessageFactory(
        ticket__organization=mailbox.organization, external_id="<1@mail.example.org>"
    )
    TicketMessageFactory(external_id="<2@mail.example.org>")

    verdict, _ = run(build())
    assert verdict.reason == "duplicate"

    verdict, _ = run(build(Message_ID="<2@mail.example.org>"))
    assert verdict is None
