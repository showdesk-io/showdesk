"""Storing what arrives: once, with its raw mail, before any processing."""

from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command

from apps.email_channel.inbound import store
from apps.email_channel.models import InboundEmail
from apps.email_channel.tokens import reply_address
from tests.email_channel.mails import build, fixture_bytes, parse
from tests.factories import MailboxFactory, OrganizationFactory, TicketFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]


@pytest.fixture
def delay():
    with mock.patch("apps.email_channel.tasks.process_inbound_email.delay") as delay:
        yield delay


@pytest.fixture
def mailbox():
    return MailboxFactory(public_address="support@acme.example.com")


def test_storing_twice_keeps_one_row_and_runs_once(
    mailbox, delay, django_capture_on_commit_callbacks
):
    raw = build(Subject="Printer on fire")
    with django_capture_on_commit_callbacks(execute=True):
        stored = store(parse(raw))
        assert store(parse(raw)) is None

    assert list(InboundEmail.objects.all()) == [stored]
    delay.assert_called_once_with(str(stored.id))
    assert stored.mailbox == mailbox
    assert stored.status == InboundEmail.Status.PENDING
    assert stored.message_id == "<1@mail.example.org>"
    assert stored.sender == "ann@example.org"
    assert stored.subject == "Printer on fire"
    assert "support@acme.example.com" in stored.recipients
    with stored.raw.open("rb") as file:
        assert file.read() == raw


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


def test_unknown_recipient_is_stored_rejected_with_no_task(
    delay, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        stored = store(parse(build(To="nobody@example.com")))

    assert stored.mailbox is None
    assert stored.status == InboundEmail.Status.REJECTED
    assert stored.reason == "unknown_recipient"
    assert stored.raw
    delay.assert_not_called()


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
