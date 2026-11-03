"""The requester's mail of an agent's reply: when it goes, and what it carries (§5)."""

from smtplib import SMTPException
from unittest import mock

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.email import _format_from_email
from apps.email_channel import presence
from apps.email_channel.content import REPLY_MARKER
from apps.email_channel.outbound import Delivery, delivery_decision
from apps.email_channel.tokens import (
    outbound_message_id,
    read_conversation_token,
    reply_address,
)
from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from apps.tickets.tasks import (
    send_ticket_reply_email,
    send_ticket_resolved_email,
    send_unread_reply_email,
)
from tests.factories import (
    ContactFactory,
    MailboxFactory,
    OrganizationFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

ADDRESS = "ann@example.org"


@pytest.fixture
def agent():
    return UserFactory(
        organization=OrganizationFactory(name="Acme"), role="agent", first_name="Alice"
    )


@pytest.fixture
def ticket(agent):
    organization = agent.organization
    return TicketFactory(
        organization=organization,
        requester=None,
        requester_email=ADDRESS,
        contact=ContactFactory(organization=organization, email=ADDRESS),
        widget_session=WidgetSession.objects.create(organization=organization),
    )


def _reply(ticket, agent, body="Have you tried X?", **fields) -> TicketMessage:
    return TicketMessageFactory(
        ticket=ticket, author=agent, body=body, channel="agent", **fields
    )


def _from_user(ticket, channel, **fields) -> TicketMessage:
    return TicketMessageFactory(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        channel=channel,
        **fields,
    )


def _connect(ticket) -> None:
    presence.mark_connected(str(ticket.widget_session_id))


# What a reply mail carries


def test_a_reply_mail_comes_from_the_mailbox_and_is_answered_to_the_ticket(
    ticket, agent, settings
):
    ticket.mailbox = MailboxFactory(organization=ticket.organization)
    ticket.save()
    message = _reply(ticket, agent)

    send_ticket_reply_email(message.id)

    [sent] = mail.outbox
    assert sent.from_email == f"Acme <{ticket.mailbox.inbound_address}>"
    assert sent.reply_to == [reply_address(ticket)]
    assert sent.to == [ADDRESS]
    assert sent.extra_headers["Message-ID"] == outbound_message_id(message)
    assert sent.body.startswith(REPLY_MARKER)
    message.refresh_from_db()
    assert message.external_id == outbound_message_id(message)
    assert message.email_delivery_status == TicketMessage.DeliveryStatus.SENT

    # The link opens the conversation, for the address it was mailed to.
    link = f"{settings.SITE_URL}/c/"
    token = sent.body.partition(link)[2].split()[0]
    claim = read_conversation_token(token)
    assert claim.ticket_id == str(ticket.id)
    assert claim.contact_id == str(ticket.contact_id)
    assert claim.holds(ADDRESS)
    assert f"{link}{token}" in sent.alternatives[0][0]


def test_without_a_mailbox_of_its_own_a_ticket_takes_the_first_active_one(
    ticket, agent
):
    organization = ticket.organization
    MailboxFactory(organization=organization, name="A", is_active=False)
    active = MailboxFactory(organization=organization, name="B")

    send_ticket_reply_email(_reply(ticket, agent).id)

    assert mail.outbox[0].from_email == f"Acme <{active.inbound_address}>"


def test_a_reply_mail_threads_on_the_tickets_mails_and_keeps_twenty_ids(ticket, agent):
    ids = [f"<{n}@mail.example.org>" for n in range(25)]
    for message_id in ids:
        _from_user(ticket, "email", external_id=message_id)
    _from_user(ticket, "widget")
    message = _reply(ticket, agent)

    send_ticket_reply_email(message.id)

    headers = mail.outbox[0].extra_headers
    assert headers["In-Reply-To"] == ids[-1]
    # The thread's first mail, and the latest ones.
    assert headers["References"].split() == ids[:1] + ids[-19:]


def test_a_retry_sends_the_same_message_id_and_failing_for_good_says_so(
    ticket, agent, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    message = _reply(ticket, agent)
    attempts = []

    def send(email, *args, **kwargs):
        attempts.append(email.extra_headers["Message-ID"])
        raise SMTPException("down")

    with mock.patch(
        "django.core.mail.EmailMultiAlternatives.send", autospec=True, side_effect=send
    ):
        send_ticket_reply_email.apply(args=[str(message.id)])

    assert attempts == [outbound_message_id(message)] * 4
    message.refresh_from_db()
    assert message.external_id == outbound_message_id(message)
    assert message.email_delivery_status == TicketMessage.DeliveryStatus.FAILED


def test_without_an_inbound_domain_a_reply_mail_is_sent_as_before(
    ticket, agent, settings
):
    settings.INBOUND_EMAIL_DOMAIN = ""
    MailboxFactory(organization=ticket.organization)

    send_ticket_reply_email(_reply(ticket, agent).id)

    [sent] = mail.outbox
    assert sent.from_email == _format_from_email(None, ticket.organization)
    assert sent.reply_to == []
    assert REPLY_MARKER not in sent.body
    assert "Have you tried X?" in sent.body


# When it goes


def test_a_reply_is_emailed_now_to_a_requester_away_from_the_widget(ticket, agent):
    assert delivery_decision(_reply(ticket, agent)) == Delivery.NOW


def test_a_reply_waits_for_a_requester_in_the_widget(ticket, agent):
    _connect(ticket)

    assert delivery_decision(_reply(ticket, agent)) == Delivery.LATER


def test_a_requester_who_last_wrote_by_email_gets_it_now_even_in_the_widget(
    ticket, agent
):
    _from_user(ticket, "widget")
    _from_user(ticket, "email")
    _connect(ticket)

    assert delivery_decision(_reply(ticket, agent)) == Delivery.NOW


def test_an_unsubscribed_contact_gets_mail_only_on_a_ticket_opened_by_email(
    ticket, agent
):
    ticket.contact.is_unsubscribed = True
    ticket.contact.save()

    assert delivery_decision(_reply(ticket, agent)) == Delivery.NEVER
    send_ticket_reply_email(_reply(ticket, agent).id)
    assert mail.outbox == []

    ticket.source = Ticket.Source.EMAIL
    ticket.save()
    assert delivery_decision(_reply(ticket, agent)) == Delivery.NOW
    send_ticket_reply_email(_reply(ticket, agent).id)
    assert [sent.to for sent in mail.outbox] == [[ADDRESS]]


def test_an_internal_note_is_never_emailed(ticket, agent):
    note = _reply(ticket, agent, message_type="internal_note")

    assert delivery_decision(note) == Delivery.NEVER


def test_an_agents_reply_is_scheduled_after_the_delay_while_in_the_widget(
    ticket, agent, settings
):
    settings.WIDGET_UNREAD_EMAIL_DELAY_MINUTES = 7
    client = APIClient()
    client.force_authenticate(agent)
    _connect(ticket)

    with (
        mock.patch("apps.tickets.views.notify_new_message"),
        mock.patch("apps.tickets.tasks.send_ticket_reply_email.delay") as now,
        mock.patch("apps.tickets.tasks.send_unread_reply_email.apply_async") as later,
    ):
        response = client.post(
            "/api/v1/messages/", {"ticket": str(ticket.id), "body": "Hi"}
        )

    assert response.status_code == 201
    now.assert_not_called()
    later.assert_called_once_with(args=[response.data["id"]], countdown=7 * 60)


# The mail of unread replies


def test_a_reply_read_in_the_widget_before_the_delay_isnt_emailed(ticket, agent):
    message = _reply(ticket, agent)
    ticket.widget_last_read_at = timezone.now()
    ticket.save()

    send_unread_reply_email(message.id)

    assert mail.outbox == []


def test_unread_replies_go_in_one_mail_sent_by_the_latest_ones_task(ticket, agent):
    first = _reply(ticket, agent, body="First reply")
    second = _reply(ticket, agent, body="Second reply")

    send_unread_reply_email(first.id)
    assert mail.outbox == []
    send_unread_reply_email(second.id)
    send_unread_reply_email(second.id)

    [sent] = mail.outbox
    assert sent.body.index("First reply") < sent.body.index("Second reply")
    for message in (first, second):
        message.refresh_from_db()
        assert message.email_delivery_status == TicketMessage.DeliveryStatus.SENT


def test_a_reply_emailed_now_takes_the_unread_ones_with_it(ticket, agent):
    first = _reply(ticket, agent, body="First reply")
    second = _reply(ticket, agent, body="Second reply")

    send_ticket_reply_email(second.id)
    send_unread_reply_email(first.id)

    [sent] = mail.outbox
    assert "First reply" in sent.body and "Second reply" in sent.body


def test_a_reply_mail_recalls_the_conversation_before_it(ticket, agent):
    for body in ("Old one", "Earlier 1", "Earlier 2"):
        _from_user(ticket, "widget", body=body)
    _reply(ticket, agent, body="Not for you", message_type="internal_note")
    ticket.widget_last_read_at = timezone.now()
    ticket.save()
    _from_user(ticket, "widget", body="Earlier 3")
    message = _reply(ticket, agent, body="New reply")

    send_ticket_reply_email(message.id)

    body = mail.outbox[0].body
    assert "Earlier 1" in body and "Earlier 3" in body and "New reply" in body
    assert "Old one" not in body
    assert "Not for you" not in body


# The resolved mail


def test_a_resolved_mail_skips_the_unsubscribed_and_is_answered_to_the_ticket(
    ticket,
):
    send_ticket_resolved_email(ticket.id)
    assert mail.outbox[0].reply_to == [reply_address(ticket)]

    ticket.contact.is_unsubscribed = True
    ticket.contact.save()
    ticket.source = Ticket.Source.EMAIL
    ticket.save()
    send_ticket_resolved_email(ticket.id)
    assert len(mail.outbox) == 1
