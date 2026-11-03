"""The conversation page's API, reached by a signed link (§6.1)."""

import time
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail, signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.email_channel.conversation_views import ConversationWriteThrottle
from apps.email_channel.tokens import conversation_token, read_conversation_token
from apps.tickets.messages import MessageRefused, create_user_message
from apps.tickets.models import (
    PRE_LOGIN_ANONYMOUS_KEY,
    Ticket,
    TicketMessage,
    WidgetSession,
)
from apps.tickets.serializers import TicketAttachmentSerializer
from tests.factories import (
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

ADDRESS = "ann@example.org"
RENEW = "/api/v1/conversations/renew/"


@pytest.fixture
def contact():
    organization = OrganizationFactory(name="Acme", primary_color="#123456")
    return ContactFactory(organization=organization, email=ADDRESS, name="Ann")


@pytest.fixture
def ticket(contact):
    return TicketFactory(
        organization=contact.organization,
        contact=contact,
        requester=None,
        requester_email=ADDRESS,
        status=Ticket.Status.WAITING,
    )


@pytest.fixture
def token(ticket, contact):
    return conversation_token(ticket, contact, ADDRESS)


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def notified():
    with (
        mock.patch("apps.email_channel.conversation_views.notify_new_message") as new,
        mock.patch("apps.email_channel.conversation_views.notify_ticket_update"),
    ):
        yield new


def _url(token, route=""):
    return f"/api/v1/conversations/{token}/{route}"


@contextmanager
def _days_later(days):
    later = time.time() + timedelta(days=days).total_seconds()
    with mock.patch("django.core.signing.time") as clock:
        clock.time.return_value = later
        yield


def test_the_page_shows_the_public_thread_branded_and_marks_it_read(
    client, ticket, token
):
    agent = UserFactory(
        organization=ticket.organization,
        role="agent",
        first_name="Alice",
        last_name="Martin",
        email="alice.private@acme.example",
    )
    TicketMessageFactory(ticket=ticket, author=agent, body="Have you tried X?")
    TicketMessageFactory(
        ticket=ticket,
        author=agent,
        body="Customer is grumpy",
        message_type=TicketMessage.MessageType.INTERNAL_NOTE,
    )
    # Someone else's session, its name and email, on the contact's ticket.
    session = WidgetSession.objects.create(
        organization=ticket.organization, name="Bob Other", email="bob@other.example"
    )
    TicketMessageFactory(
        ticket=ticket,
        author=None,
        widget_session=session,
        sender_type=TicketMessage.SenderType.USER,
        body="Me too",
    )
    updated_at = Ticket.objects.get(pk=ticket.pk).updated_at

    response = client.get(_url(token))

    assert response.status_code == 200
    data = response.json()
    assert data["organization"]["name"] == "Acme"
    assert data["organization"]["color"] == "#123456"
    assert data["reference"] == ticket.reference
    assert data["status"] == Ticket.Status.WAITING
    assert data["can_reply"] is True
    assert [m["body"] for m in data["messages"]] == ["Have you tried X?", "Me too"]
    assert [m["sender_name"] for m in data["messages"]] == ["Alice Martin", ""]
    content = response.content.decode()
    for hidden in ("Customer is grumpy", "alice.private", "Bob Other", "bob@"):
        assert hidden not in content
    ticket = Ticket.objects.get(pk=ticket.pk)
    assert ticket.widget_last_read_at is not None
    assert ticket.updated_at == updated_at


def test_a_tampered_or_foreign_token_opens_nothing(client, ticket, contact, token):
    payload = signing.loads(token, salt="showdesk.email_channel.conversation")
    foreign = [
        token[:-2] + ("AA" if not token.endswith("AA") else "BB"),
        signing.dumps(payload, compress=True),
        signing.dumps(payload, salt="showdesk.email_channel.reply", compress=True),
    ]

    for bad in foreign:
        assert client.get(_url(bad)).status_code == 404
        assert client.post(_url(bad, "messages/"), {"body": "Hi"}).status_code == 404


def test_a_link_opens_nothing_once_the_ticket_isnt_its_contacts(
    client, ticket, contact, token
):
    ticket.contact = ContactFactory(organization=ticket.organization)
    ticket.save()
    assert client.get(_url(token)).status_code == 404

    ticket.contact = contact
    ticket.context_metadata = {PRE_LOGIN_ANONYMOUS_KEY: True}
    ticket.save()
    assert client.get(_url(token)).status_code == 404

    ticket.context_metadata = {}
    ticket.save()
    contact.is_anonymized = True
    contact.save()
    assert client.get(_url(token)).status_code == 404
    assert client.post(_url(token, "messages/"), {"body": "Hi"}).status_code == 404


def test_a_link_opens_nothing_once_its_address_isnt_the_contacts(
    client, ticket, contact, token
):
    # An agent corrected a mistyped address: its holder loses the conversation.
    contact.email = "ann@new.example"
    contact.save()

    assert client.get(_url(token)).status_code == 404
    assert client.post(_url(token, "messages/"), {"body": "Hi"}).status_code == 404
    contact.refresh_from_db()
    assert contact.email_verified_at is None
    assert not ticket.messages.exists()


def test_an_expired_link_only_says_whether_it_can_be_renewed(
    client, ticket, contact, token
):
    ticket.contact = ContactFactory(organization=ticket.organization)
    ticket.save()  # Whatever the ticket's state.

    with _days_later(31):
        response = client.get(_url(token))
        posted = client.post(_url(token, "messages/"), {"body": "Hi"})
    with _days_later(181):
        too_old = client.get(_url(token))

    assert response.status_code == posted.status_code == 410
    assert response.json() == {"renewable": True}
    assert too_old.status_code == 410
    assert too_old.json() == {"renewable": False}


def test_opening_a_link_verifies_the_contact_but_not_the_ticket(
    client, ticket, contact, token
):
    client.get(_url(token))

    contact.refresh_from_db()
    first = contact.email_verified_at
    assert first is not None
    assert Ticket.objects.get(pk=ticket.pk).sender_verified is False

    with mock.patch(
        "apps.email_channel.conversation_views.mark_email_proven"
    ) as proven:
        assert client.get(_url(token)).status_code == 200
    proven.assert_not_called()  # A poll of a verified contact writes nothing.
    contact.refresh_from_db()
    assert contact.email_verified_at == first


def test_a_posted_message_reaches_agents_without_verifying_the_sender(
    client,
    ticket,
    contact,
    token,
    notified,
    settings,
    django_capture_on_commit_callbacks,
):
    settings.INBOUND_EMAIL_DOMAIN = ""  # The page works without the inbound channel.
    ticket.widget_session = WidgetSession.objects.create(
        organization=ticket.organization, contact=contact
    )
    ticket.save()
    # An agent's credentials, left in the browser, are none of this API's business.
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-jwt")

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            _url(token, "messages/"), {"body": "Still broken"}, format="json"
        )

    assert response.status_code == 201
    message = TicketMessage.objects.get(pk=response.json()["id"])
    assert message.body == "Still broken"
    assert message.sender_type == TicketMessage.SenderType.USER
    assert message.channel == TicketMessage.Channel.WIDGET
    assert message.widget_session_id == ticket.widget_session_id
    notified.assert_called_once_with(message)
    ticket = Ticket.objects.get(pk=ticket.pk)
    assert ticket.status == Ticket.Status.WAITING
    # It proves who holds the mailbox now, not who wrote the ticket.
    assert ticket.sender_verified is False
    assert client.post(_url(token, "messages/"), {"body": " "}).status_code == 400


def test_a_posted_message_stays_off_a_session_that_isnt_the_contacts(
    client, ticket, token, notified
):
    ticket.widget_session = WidgetSession.objects.create(
        organization=ticket.organization, name="Bob Other"
    )
    ticket.save()

    response = client.post(_url(token, "messages/"), {"body": "Hi"})

    assert response.status_code == 201
    assert response.json()["sender_name"] == ""
    assert TicketMessage.objects.get(pk=response.json()["id"]).widget_session is None


def test_no_message_lands_on_an_anonymized_contacts_ticket(client, ticket, contact):
    # Found before the anonymization committed, written after.
    session = WidgetSession.objects.create(organization=ticket.organization)
    ticket.widget_session = session
    ticket.save()
    contact.is_anonymized = True
    contact.save()

    with pytest.raises(MessageRefused):
        create_user_message(ticket, body="Hi")
    widget = client.post(
        "/api/v1/tickets/widget_message/",
        {"ticket_id": str(ticket.id), "body": "Hi"},
        format="json",
        HTTP_X_WIDGET_TOKEN=str(ticket.organization.api_token),
        HTTP_X_WIDGET_SESSION=str(session.id),
    )
    assert widget.status_code == 404
    assert not ticket.messages.exists()


def test_a_message_reopens_a_recently_closed_ticket_only(
    client, ticket, contact, token, notified
):
    ticket.status = Ticket.Status.RESOLVED
    ticket.resolved_at = timezone.now() - timedelta(days=1)
    ticket.save()
    assert client.post(_url(token, "messages/"), {"body": "Again"}).status_code == 201
    assert Ticket.objects.get(pk=ticket.pk).status == Ticket.Status.OPEN

    old = TicketFactory(
        organization=ticket.organization,
        contact=contact,
        requester=None,
        status=Ticket.Status.CLOSED,
        closed_at=timezone.now() - timedelta(days=30),
    )
    old_token = conversation_token(old, contact, ADDRESS)
    assert client.get(_url(old_token)).json()["can_reply"] is False
    assert client.post(_url(old_token, "messages/"), {"body": "Hi"}).status_code == 409
    assert not old.messages.exists()


def test_an_attachment_follows_the_widgets_limits(
    client, ticket, token, notified, local_media
):
    response = client.post(
        _url(token, "attachments/"),
        {"file": SimpleUploadedFile("log.txt", b"trace", "text/plain")},
        format="multipart",
    )
    assert response.status_code == 201
    message = ticket.messages.get()
    assert message.attachments.get().filename == "log.txt"
    assert message.sender_type == TicketMessage.SenderType.USER

    blocked = client.post(
        _url(token, "attachments/"),
        {"file": SimpleUploadedFile("run.exe", b"MZ", "application/octet-stream")},
        format="multipart",
    )
    with mock.patch.object(TicketAttachmentSerializer, "MAX_FILE_SIZE", 3):
        large = client.post(
            _url(token, "attachments/"),
            {"file": SimpleUploadedFile("big.txt", b"four", "text/plain")},
            format="multipart",
        )
    assert blocked.status_code == large.status_code == 400
    assert ticket.messages.count() == 1


def test_renewal_mails_a_fresh_link_to_the_contact_once_an_hour(
    client, ticket, token, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with _days_later(31):
        first = client.post(
            RENEW, {"token": token, "email": "mallory@example.org"}, format="json"
        )
        second = client.post(RENEW, {"token": token}, format="json")

    assert first.status_code == second.status_code == 202
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == [ADDRESS]
    fresh = sent.body.split("/c/")[1].split()[0]
    claim = read_conversation_token(fresh)
    assert claim.ticket_id == str(ticket.id)
    assert claim.holds(ADDRESS)


def test_renewal_mails_a_contact_three_times_a_day_at_most(client, contact, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    tickets = [
        TicketFactory(
            organization=contact.organization, contact=contact, requester=None
        )
        for _ in range(4)
    ]

    for ticket in tickets:
        token = conversation_token(ticket, contact, ADDRESS)
        assert client.post(RENEW, {"token": token}, format="json").status_code == 202

    assert len(mail.outbox) == 3


def test_renewal_answers_the_same_and_mails_nothing_otherwise(
    client, ticket, contact, token, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    moved = TicketFactory(
        organization=contact.organization,
        contact=ContactFactory(organization=contact.organization),
        requester=None,
    )
    contact.email = ""
    contact.save()

    answers = [
        client.post(RENEW, {"token": token}, format="json"),
        client.post(
            RENEW,
            {"token": conversation_token(moved, contact, ADDRESS)},
            format="json",
        ),
        client.post(RENEW, {"token": token[:-2] + "xx"}, format="json"),
        client.post(RENEW, {}, format="json"),
        client.post(RENEW, "not json", content_type="application/json"),
        client.post(RENEW, {"token": ["a", "list"]}, format="json"),
    ]

    assert {answer.status_code for answer in answers} == {202}
    assert mail.outbox == []


def test_a_link_too_old_to_renew_mails_nothing(client, ticket, token, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    with _days_later(181):
        assert client.post(RENEW, {"token": token}, format="json").status_code == 202

    assert mail.outbox == []


def test_the_conversation_routes_have_their_own_rates(client, token, notified):
    from django.conf import settings

    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert {"conversation_read", "conversation_write", "conversation_renew"} <= set(
        rates
    )
    with mock.patch.object(
        ConversationWriteThrottle, "THROTTLE_RATES", {"conversation_write": "1/minute"}
    ):
        assert client.post(_url(token, "messages/"), {"body": "1"}).status_code == 201
        assert client.post(_url(token, "messages/"), {"body": "2"}).status_code == 429
