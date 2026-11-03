"""Storing what arrives: once, with its raw mail, before any processing."""

from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.email_channel.inbound import store
from apps.email_channel.models import InboundEmail
from apps.email_channel.tasks import replay, requeue_stale_inbound
from apps.email_channel.tokens import reply_address
from tests.email_channel.mails import build, fixture_bytes, parse
from tests.factories import (
    InboundEmailFactory,
    MailboxFactory,
    OrganizationFactory,
    TicketFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]


@pytest.fixture
def delay():
    with mock.patch("apps.email_channel.tasks.process_inbound_email.delay") as delay:
        yield delay


@pytest.fixture
def mailbox():
    return MailboxFactory(public_address="support@acme.example.com")


def test_storing_twice_keeps_one_row_and_requeues_only_while_pending(
    mailbox, delay, django_capture_on_commit_callbacks
):
    raw = build(Subject="Printer on fire")
    with django_capture_on_commit_callbacks(execute=True):
        stored = store(parse(raw))
        # The first queuing may have failed (broker down) and the provider retried.
        assert store(parse(raw)) is None
    assert list(InboundEmail.objects.all()) == [stored]
    assert delay.call_args_list == [mock.call(str(stored.id))] * 2

    InboundEmail.objects.filter(pk=stored.pk).update(
        status=InboundEmail.Status.PROCESSED
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert store(parse(raw)) is None
    assert delay.call_count == 2

    assert stored.mailbox == mailbox
    assert stored.status == InboundEmail.Status.PENDING
    assert stored.message_id == "<1@mail.example.org>"
    assert stored.sender == "ann@example.org"
    assert stored.subject == "Printer on fire"
    assert "support@acme.example.com" in stored.recipients
    with stored.raw.open("rb") as file:
        assert file.read() == raw


def test_what_parsing_the_raw_mail_loses_is_stored(mailbox, delay):
    message = parse(build(), envelope_recipient="Support@Acme.example.com")
    message.envelope_sender = "bounces@example.org"
    message.spam_detected = False
    message.spam_score = 1.5

    stored = store(message)

    assert stored.envelope_recipient == "support@acme.example.com"
    assert stored.envelope_sender == "bounces@example.org"
    assert (stored.spam_detected, stored.spam_score) == (False, 1.5)

    unknown = store(parse(build(Message_ID="<2@mail.example.org>")))
    assert unknown.envelope_recipient == unknown.envelope_sender == ""
    assert (unknown.spam_detected, unknown.spam_score) == (None, None)


def test_no_message_id_gets_a_stable_one_from_the_content(mailbox, delay):
    raw = fixture_bytes("no_message_id.eml")
    stored = store(parse(raw))

    assert stored.message_id.endswith("@hashed.invalid>")
    assert store(parse(raw)) is None
    assert store(parse(raw.replace(b"no Message-ID", b"no Message-Id"))) is not None


def test_an_overlong_message_id_is_replaced_by_its_hash(mailbox, delay):
    long_id = f"<{'x' * 300}@mail.example.org>"
    stored = store(parse(build(Message_ID=long_id)))

    assert stored.message_id.endswith("@hashed.invalid>")
    assert len(stored.message_id) <= 255
    assert store(parse(build(Message_ID=long_id))) is None


def test_control_characters_are_dropped_from_what_is_stored(mailbox, delay):
    # Postgres refuses NUL in text and JSON: the webhook would fail on every retry.
    raw = (
        b"From: Ann\x00 Customer <ann\x00@example.org>\r\n"
        b"To: support@acme.example.com, odd\x00\x01@example.org\r\n"
        b"Subject: Printer\x00 on\x07 fire\r\n"
        b"Message-ID: <nul\x00@mail.example.org>\r\n"
        b"\r\n"
        b"Hello\r\n"
    )
    stored = store(parse(raw), raw=raw)

    stored.refresh_from_db()
    assert stored.subject == "Printer on fire"
    assert stored.sender == "ann@example.org"
    assert stored.message_id == "<nul@mail.example.org>"
    assert stored.recipients == ["support@acme.example.com", "odd@example.org"]
    assert stored.mailbox == mailbox


def test_unknown_recipient_is_stored_rejected_with_no_task(
    delay, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        stored = store(
            parse(
                build(
                    To="nobody@example.com",
                    From="Ann <Ann@example.org>",
                    Subject="Printer on fire",
                )
            )
        )

    assert stored.mailbox is None
    assert stored.status == InboundEmail.Status.REJECTED
    assert stored.reason == "unknown_recipient"
    assert (stored.sender, stored.subject) == ("ann@example.org", "Printer on fire")
    # Nobody here asked for it: its content isn't kept.
    assert not stored.raw
    delay.assert_not_called()


def test_rejected_mail_from_one_sender_is_logged_a_bounded_number_of_times(
    delay, settings
):
    settings.INBOUND_EMAIL_RATE_LIMIT_PER_HOUR = 2

    stored = [
        store(parse(build(To="nobody@example.com", Message_ID=f"<{n}@x>")))
        for n in range(3)
    ]
    other = store(
        parse(
            build(To="nobody@example.com", From="bob@example.org", Message_ID="<b@x>")
        )
    )

    assert [row is not None for row in stored] == [True, True, False]
    assert other is not None
    assert InboundEmail.objects.count() == 3


def test_rejected_mail_from_anyone_is_logged_a_bounded_number_of_times(delay, settings):
    settings.INBOUND_EMAIL_MAILBOX_RATE_LIMIT_PER_HOUR = 2

    stored = [
        store(
            parse(
                build(
                    To="nobody@example.com",
                    From=f"sender{n}@example.org",
                    Message_ID=f"<{n}@x>",
                )
            )
        )
        for n in range(3)
    ]

    # A From costs nothing to change.
    assert [row is not None for row in stored] == [True, True, False]


def test_a_rejected_mail_doesnt_make_the_same_one_to_a_reply_address_a_duplicate(
    delay,
):
    ticket = TicketFactory(mailbox=None)
    raw = build(Message_ID="<same@x>")
    # Sent to an old reply address that no longer verifies, and to the right one.
    old = reply_address(ticket).replace("reply+", "reply+0")

    rejected = store(parse(raw, envelope_recipient=old))
    accepted = store(parse(raw, envelope_recipient=reply_address(ticket)))

    assert rejected.status == InboundEmail.Status.REJECTED
    assert accepted is not None
    assert accepted.status == InboundEmail.Status.PENDING
    assert store(parse(raw, envelope_recipient=reply_address(ticket))) is None
    assert store(parse(raw, envelope_recipient=old)) is None


def test_mail_for_an_inactive_organization_is_rejected(
    delay, django_capture_on_commit_callbacks
):
    organization = OrganizationFactory(is_active=False)
    mailbox = MailboxFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization, mailbox=MailboxFactory(organization=organization)
    )
    with django_capture_on_commit_callbacks(execute=True):
        to_mailbox = store(parse(build(), envelope_recipient=mailbox.inbound_address))
        to_ticket = store(
            parse(build(Message_ID="<2@x>"), envelope_recipient=reply_address(ticket))
        )

    for stored in (to_mailbox, to_ticket):
        assert stored.status == InboundEmail.Status.REJECTED
        assert stored.reason == "inactive_organization"
        assert not stored.raw
    delay.assert_not_called()


def test_ingest_eml_feeds_the_same_pipeline(
    tmp_path, delay, django_capture_on_commit_callbacks
):
    mailbox = MailboxFactory()
    path = tmp_path / "mail.eml"
    path.write_bytes(fixture_bytes("no_message_id.eml"))
    out = StringIO()

    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "ingest_eml", str(path), recipient=mailbox.inbound_address, stdout=out
        )

    stored = InboundEmail.objects.get()
    assert stored.mailbox == mailbox
    delay.assert_called_once_with(str(stored.id))
    assert f"{stored.id} queued" in out.getvalue()


def test_stale_pending_mail_is_queued_again(delay, settings):
    stale = InboundEmailFactory()
    InboundEmailFactory()  # Pending, but its first queuing may still be on its way.
    failed = InboundEmailFactory(status=InboundEmail.Status.FAILED)
    processed = InboundEmailFactory(status=InboundEmail.Status.PROCESSED)
    long_ago = timezone.now() - timedelta(minutes=11)
    InboundEmail.objects.filter(pk__in=[stale.pk, failed.pk, processed.pk]).update(
        received_at=long_ago, updated_at=long_ago
    )

    requeue_stale_inbound()

    delay.assert_called_once_with(str(stale.id))
    # Once per interval: the next run leaves it to the task just queued.
    delay.reset_mock()
    requeue_stale_inbound()
    delay.assert_not_called()
    assert settings.CELERY_BEAT_SCHEDULE["requeue-stale-inbound-emails"] == {
        "task": "apps.email_channel.tasks.requeue_stale_inbound",
        "schedule": 60 * 10,
    }


def test_an_old_mail_just_replayed_is_not_queued_again(
    delay, django_capture_on_commit_callbacks
):
    long_ago = timezone.now() - timedelta(days=2)
    failed = InboundEmailFactory(status=InboundEmail.Status.FAILED)
    InboundEmail.objects.filter(pk=failed.pk).update(
        received_at=long_ago, updated_at=long_ago
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert replay(failed.pk)
    delay.reset_mock()

    requeue_stale_inbound()

    delay.assert_not_called()
