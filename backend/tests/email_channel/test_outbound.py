"""The requester's mail of an agent's reply: when it goes, and what it carries (§5)."""

from smtplib import SMTPException
from unittest import mock

import pytest
from celery.exceptions import Retry
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from apps.core.email import _format_from_email
from apps.email_channel import presence
from apps.email_channel.content import REPLY_MARKER
from apps.email_channel.outbound import (
    Delivery,
    delivery_decision,
    queue_reply_email,
    reply_lock_key,
)
from apps.email_channel.tokens import (
    outbound_message_id,
    read_conversation_token,
    reply_address,
)
from apps.organizations.models import OrganizationDomain
from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from apps.tickets.tasks import (
    REPLY_LOCK_OUTAGE_MAX_RETRIES,
    send_ticket_reply_email,
    send_ticket_resolved_email,
    send_unread_reply_email,
)
from tests.email_channel.mails import INBOUND_DOMAIN
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
    presence.mark_connected(str(ticket.widget_session_id), "socket")


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


def _sending_domain(organization, **fields) -> OrganizationDomain:
    return OrganizationDomain.objects.create(
        organization=organization,
        domain="acme.com",
        is_sending=True,
        status=fields.pop("status", OrganizationDomain.Status.VERIFIED),
        sending_status=fields.pop(
            "sending_status", OrganizationDomain.SendingStatus.VERIFIED
        ),
        sending_provider_ref="acme.com",
        sending_provider="manual",
        **fields,
    )


def test_a_reply_mail_comes_from_the_public_address_once_sendable(
    ticket, agent, settings
):
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    ticket.mailbox = MailboxFactory(
        organization=ticket.organization, public_address="support@acme.com"
    )
    ticket.save()
    row = _sending_domain(ticket.organization)

    send_ticket_reply_email(_reply(ticket, agent).id)
    row.sending_status = OrganizationDomain.SendingStatus.PENDING
    row.save()
    send_ticket_reply_email(_reply(ticket, agent).id)

    sendable, pending = mail.outbox
    assert sendable.from_email == "Acme <support@acme.com>"
    assert sendable.reply_to == [reply_address(ticket)]
    assert pending.from_email == f"Acme <{ticket.mailbox.inbound_address}>"


def test_customers_reply_to_the_public_address_once_its_forwarding_is_proven(
    ticket, agent, settings
):
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    ticket.mailbox = MailboxFactory(
        organization=ticket.organization,
        public_address="support@acme.com",
        forwarding_verified_at=timezone.now(),
    )
    ticket.save()
    row = _sending_domain(ticket.organization, sending_status="pending")

    send_ticket_reply_email(_reply(ticket, agent).id)
    row.sending_status = OrganizationDomain.SendingStatus.VERIFIED
    row.save()
    send_ticket_reply_email(_reply(ticket, agent).id)
    ticket.status = Ticket.Status.RESOLVED
    ticket.resolved_at = timezone.now()
    ticket.save()
    send_ticket_resolved_email(ticket.id)
    ticket.mailbox.forwarding_verified_at = None
    ticket.mailbox.save()
    send_ticket_reply_email(_reply(ticket, agent).id)

    not_sent_from_it, proven, resolved, unproven = mail.outbox
    assert not_sent_from_it.reply_to == [reply_address(ticket)]
    assert proven.reply_to == resolved.reply_to == ["support@acme.com"]
    assert proven.body.startswith(REPLY_MARKER)
    assert unproven.reply_to == [reply_address(ticket)]


def test_the_inbound_address_is_used_without_ownership_or_provider(
    ticket, agent, settings
):
    from apps.email_channel.sending.services import sendable_address

    mailbox = MailboxFactory(
        organization=ticket.organization, public_address="support@acme.com"
    )
    row = _sending_domain(ticket.organization, status=OrganizationDomain.Status.FAILED)
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    assert sendable_address(mailbox) is None

    row.status = OrganizationDomain.Status.VERIFIED
    row.save()
    assert sendable_address(mailbox) == "support@acme.com"
    settings.SENDING_DOMAIN_PROVIDER = "none"
    assert sendable_address(mailbox) is None


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


def test_waiting_for_the_ticket_leaves_the_smtp_attempts_whole(ticket, agent, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    message = _reply(ticket, agent)
    attempts = []

    def send(email, *args, **kwargs):
        attempts.append(1)
        raise SMTPException("down")

    with mock.patch(
        "django.core.mail.EmailMultiAlternatives.send", autospec=True, side_effect=send
    ):
        # As after many retries spent waiting for the ticket's lock.
        send_ticket_reply_email.apply(args=[str(message.id)], retries=20)

    assert len(attempts) == 4
    message.refresh_from_db()
    assert message.email_delivery_status == TicketMessage.DeliveryStatus.FAILED


def test_a_cache_outage_that_lasts_fails_the_delivery(ticket, agent):
    message = _reply(ticket, agent)

    with mock.patch(
        "apps.email_channel.outbound.cache.add",
        side_effect=RedisConnectionError("down"),
    ):
        send_ticket_reply_email.apply(
            args=[str(message.id)],
            kwargs={"lock_outages": REPLY_LOCK_OUTAGE_MAX_RETRIES},
        )

    assert mail.outbox == []
    message.refresh_from_db()
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


def test_a_resolved_mail_is_answered_to_the_ticket_and_threads_on_it(ticket, agent):
    _from_user(ticket, "email", external_id="<1@mail.example.org>")
    ticket.resolved_at = timezone.now()
    ticket.save()

    send_ticket_resolved_email(ticket.id)
    send_ticket_resolved_email(ticket.id)

    first, retried = mail.outbox
    assert first.reply_to == [reply_address(ticket)]
    assert first.extra_headers["In-Reply-To"] == "<1@mail.example.org>"
    # A retry sends the same mail.
    assert first.extra_headers["Message-ID"] == retried.extra_headers["Message-ID"]
    assert first.extra_headers["Message-ID"].endswith(f"@{INBOUND_DOMAIN}>")


def test_a_resolved_mail_reaches_the_unsubscribed_only_on_a_ticket_opened_by_email(
    ticket,
):
    ticket.contact.is_unsubscribed = True
    ticket.contact.save()

    send_ticket_resolved_email(ticket.id)
    assert mail.outbox == []

    ticket.source = Ticket.Source.EMAIL
    ticket.save()
    send_ticket_resolved_email(ticket.id)
    assert [sent.to for sent in mail.outbox] == [[ADDRESS]]


# Who gets a conversation link


def _link_and_history(ticket, agent) -> tuple[bool, bool]:
    _from_user(ticket, "widget", body="Earlier words")
    send_ticket_reply_email(_reply(ticket, agent).id)
    body = mail.outbox[-1].body
    return "/c/" in body, "Earlier words" in body


def test_a_link_and_the_history_go_to_the_address_the_contact_holds(ticket, agent):
    ticket.requester_email = ADDRESS.upper()
    ticket.save()

    assert _link_and_history(ticket, agent) == (True, True)


def test_no_link_nor_history_to_an_address_the_contact_doesnt_hold(ticket, agent):
    """An agent relinked the ticket: the mail goes to whoever wrote it."""
    ticket.contact = ContactFactory(organization=ticket.organization)
    ticket.save()

    assert _link_and_history(ticket, agent) == (False, False)


def test_no_link_nor_history_on_a_ticket_a_login_moved(ticket, agent):
    ticket.context_metadata = {"pre_login_anonymous": True}
    ticket.save()

    assert _link_and_history(ticket, agent) == (False, False)


def test_no_link_nor_history_to_a_merely_declared_address(ticket, agent):
    contact = ticket.contact
    contact.email, contact.declared_email = "", ADDRESS
    contact.save()
    ticket.requester_email = ""
    ticket.save()

    assert _link_and_history(ticket, agent) == (False, False)
    assert mail.outbox[-1].to == [ADDRESS]


def test_no_link_nor_history_without_a_contact(ticket, agent):
    ticket.contact = None
    ticket.save()

    assert _link_and_history(ticket, agent) == (False, False)


def test_no_link_nor_history_for_an_anonymized_contact(ticket, agent):
    """Its mail only goes to an address left on the ticket by an older scrub."""
    ticket.contact.is_anonymized = True
    ticket.contact.save()

    with mock.patch("apps.tickets.tasks._requester_address", return_value=ADDRESS):
        assert _link_and_history(ticket, agent) == (False, False)


# Mails that must not go wrong


def test_a_two_line_widget_message_is_titled_and_emailed_on_one_line(
    ticket, agent, settings
):
    session = ticket.widget_session
    session.email = ADDRESS
    session.save()
    with (
        mock.patch("apps.tickets.views.notify_new_ticket"),
        mock.patch("apps.tickets.views.notify_new_message"),
        mock.patch("apps.tickets.views.send_ticket_created_email.delay"),
    ):
        response = APIClient().post(
            "/api/v1/tickets/widget_message/",
            {"body": "My invoice\nis wrong"},
            HTTP_X_WIDGET_TOKEN=str(ticket.organization.api_token),
            HTTP_X_WIDGET_SESSION=str(session.id),
            format="json",
        )
    assert response.status_code == 201, response.data
    created = Ticket.objects.get(pk=response.data["ticket_id"])
    assert created.title == "My invoice is wrong"

    Ticket.objects.filter(pk=created.pk).update(title="Two\nlines")
    send_ticket_reply_email(_reply(created, agent).id)

    assert mail.outbox[-1].subject == f"Re: [{created.reference}] Two lines"


def test_a_from_name_on_two_lines_is_sent_on_one(ticket, agent):
    organization = ticket.organization
    organization.email_from_name = "Acme\nSupport"
    organization.save()
    MailboxFactory(organization=organization)

    send_ticket_reply_email(_reply(ticket, agent).id)

    assert mail.outbox[0].from_email.startswith("Acme Support <")


def test_the_text_part_shows_bodies_unescaped(ticket, agent):
    send_ticket_reply_email(_reply(ticket, agent, body="Tom & Jerry's <tag>").id)

    assert "Tom & Jerry's <tag>" in mail.outbox[0].body


def test_a_third_party_is_quoted_by_name_and_the_requester_as_you(ticket, agent):
    for body, sender in (
        ("Colleague", "Bob Other <bob@example.net>"),
        ("Unnamed", "carol@example.net"),
        ("Mine", f"Ann <{ADDRESS.upper()}>"),
    ):
        _from_user(ticket, "email", body=body, external_sender=sender)

    send_ticket_reply_email(_reply(ticket, agent).id)

    history = mail.outbox[0].body.partition("Earlier in this conversation:")[2]
    labels = [line.partition(" (")[0] for line in history.splitlines() if " (" in line]
    assert labels == ["Bob Other", "carol@example.net", "You"]


# Grouping, ordering and concurrency


def test_a_scheduled_reply_is_sent_when_a_later_one_wont_carry_it(ticket, agent):
    first = _reply(ticket, agent, body="First reply")
    _from_user(ticket, "email", body="Answered by mail")
    second = _reply(ticket, agent, body="Second reply")

    send_ticket_reply_email(second.id)
    send_unread_reply_email(first.id)

    assert len(mail.outbox) == 2
    assert "First reply" in mail.outbox[1].body
    first.refresh_from_db()
    assert first.email_delivery_status == TicketMessage.DeliveryStatus.SENT


def test_a_ticket_sends_one_reply_mail_at_a_time(ticket, agent):
    message = _reply(ticket, agent)
    cache.add(reply_lock_key(ticket), "busy")

    with pytest.raises(Retry):
        send_ticket_reply_email(message.id)
    assert mail.outbox == []

    cache.delete(reply_lock_key(ticket))
    send_ticket_reply_email(message.id)
    assert len(mail.outbox) == 1
    assert cache.get(reply_lock_key(ticket)) is None


def test_a_cache_outage_retries_the_reply_mail(ticket, agent):
    message = _reply(ticket, agent)

    with (
        mock.patch(
            "apps.email_channel.outbound.cache.add",
            side_effect=RedisConnectionError("down"),
        ),
        pytest.raises(Retry),
    ):
        send_ticket_reply_email(message.id)
    assert mail.outbox == []

    send_ticket_reply_email(message.id)
    assert len(mail.outbox) == 1


def test_the_delay_stays_below_the_brokers_redelivery(ticket, agent, settings):
    settings.WIDGET_UNREAD_EMAIL_DELAY_MINUTES = 600
    _connect(ticket)

    with mock.patch("apps.tickets.tasks.send_unread_reply_email.apply_async") as later:
        queue_reply_email(_reply(ticket, agent))

    assert later.call_args.kwargs["countdown"] == 55 * 60


def test_an_agent_cant_post_a_message_as_the_requester(ticket, agent):
    client = APIClient()
    client.force_authenticate(agent)

    with (
        mock.patch("apps.tickets.views.notify_new_message"),
        mock.patch("apps.tickets.tasks.send_ticket_reply_email.delay") as now,
    ):
        response = client.post(
            "/api/v1/messages/",
            {"ticket": str(ticket.id), "body": "Hi", "sender_type": "user"},
        )

    assert response.status_code == 201
    assert TicketMessage.objects.get(pk=response.data["id"]).sender_type == "agent"
    now.assert_called_once()


def test_agents_are_told_who_wrote_a_mail_in_copy(ticket, agent):
    ticket.requester_name = "Ann Customer"
    ticket.save(update_fields=["requester_name"])
    colleague = _from_user(
        ticket, "email", body="Same here", external_sender="Bob <bob@example.org>"
    )
    own = _from_user(ticket, "email", body="Still broken")

    send_ticket_reply_email(colleague.id)
    send_ticket_reply_email(own.id)

    assert [sent.to for sent in mail.outbox] == [[agent.email]] * 2
    assert "Bob replied on ticket" in mail.outbox[0].body
    assert "Ann Customer replied on ticket" in mail.outbox[1].body
