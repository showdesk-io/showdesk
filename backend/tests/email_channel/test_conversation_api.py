"""The conversation page's API, reached by a signed link (§6.1)."""

import time
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail, signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.email_channel.conversation_views import ConversationWriteThrottle
from apps.email_channel.tokens import conversation_token, read_conversation_token
from apps.tickets.models import PRE_LOGIN_ANONYMOUS_KEY, Ticket, TicketMessage
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


def _expired():
    """Run the code under it a day after the links' lifetime."""
    later = time.time() + timedelta(days=31).total_seconds()
    clock = mock.patch("django.core.signing.time")
    started = clock.start()
    started.time.return_value = later
    return clock


def test_the_page_shows_the_public_thread_branded(client, ticket, token):
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

    response = client.get(_url(token))

    assert response.status_code == 200
    data = response.json()
    assert data["organization"]["name"] == "Acme"
    assert data["organization"]["color"] == "#123456"
    assert data["reference"] == ticket.reference
    assert data["status"] == Ticket.Status.WAITING
    assert data["can_reply"] is True
    assert [m["body"] for m in data["messages"]] == ["Have you tried X?"]
    assert data["messages"][0]["sender_name"] == "Alice Martin"
    assert "Customer is grumpy" not in response.content.decode()
    assert "alice.private" not in response.content.decode()


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


def test_an_expired_link_only_says_it_can_be_renewed(client, token):
    clock = _expired()
    try:
        response = client.get(_url(token))
        posted = client.post(_url(token, "messages/"), {"body": "Hi"})
    finally:
        clock.stop()

    assert response.status_code == 410
    assert response.json() == {"renewable": True}
    assert posted.status_code == 410


def test_opening_a_link_verifies_the_contact_but_not_the_ticket(
    client, ticket, contact, token
):
    client.get(_url(token))

    contact.refresh_from_db()
    first = contact.email_verified_at
    assert first is not None
    assert Ticket.objects.get(pk=ticket.pk).sender_verified is False

    client.get(_url(token))
    contact.refresh_from_db()
    assert contact.email_verified_at == first


def test_an_old_link_proves_nothing_of_a_changed_address(
    client, ticket, contact, token, notified
):
    contact.email = "ann@new.example"
    contact.save()

    assert client.get(_url(token)).status_code == 200
    assert client.post(_url(token, "messages/"), {"body": "Hi"}).status_code == 201

    contact.refresh_from_db()
    assert contact.email_verified_at is None
    assert Ticket.objects.get(pk=ticket.pk).sender_verified is False


def test_a_posted_message_reaches_agents_and_verifies_the_sender(
    client, ticket, token, notified, settings, django_capture_on_commit_callbacks
):
    settings.INBOUND_EMAIL_DOMAIN = ""  # The page works without the inbound channel.
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
    notified.assert_called_once_with(message)
    ticket = Ticket.objects.get(pk=ticket.pk)
    assert ticket.status == Ticket.Status.WAITING
    assert ticket.sender_verified_at is not None
    assert ticket.sender_verified is True
    assert client.post(_url(token, "messages/"), {"body": " "}).status_code == 400


def test_an_agent_moving_the_ticket_drops_its_senders_proof(ticket):
    ticket.sender_verified_at = timezone.now()
    ticket.save()
    agent = UserFactory(organization=ticket.organization, role="agent")
    client = APIClient()
    client.force_authenticate(agent)
    other = ContactFactory(organization=ticket.organization)

    response = client.patch(
        f"/api/v1/tickets/{ticket.id}/", {"contact": str(other.id)}, format="json"
    )

    assert response.status_code == 200
    assert Ticket.objects.get(pk=ticket.pk).sender_verified is False


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
    clock = _expired()
    try:
        first = client.post(
            "/api/v1/conversations/renew/",
            {"token": token, "email": "mallory@example.org"},
            format="json",
        )
        second = client.post(
            "/api/v1/conversations/renew/", {"token": token}, format="json"
        )
    finally:
        clock.stop()

    assert first.status_code == second.status_code == 202
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == [ADDRESS]
    fresh = sent.body.split("/c/")[1].split()[0]
    claim = read_conversation_token(fresh)
    assert claim.ticket_id == str(ticket.id)
    assert claim.holds(ADDRESS)


def test_renewal_answers_the_same_and_mails_nothing_otherwise(
    client, ticket, contact, token, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    contact.email = ""
    contact.save()
    renew = "/api/v1/conversations/renew/"

    answers = [
        client.post(renew, {"token": token}, format="json"),
        client.post(renew, {"token": token[:-2] + "xx"}, format="json"),
        client.post(renew, {}, format="json"),
        client.post(renew, "not json", content_type="application/json"),
        client.post(renew, {"token": ["a", "list"]}, format="json"),
    ]

    assert {answer.status_code for answer in answers} == {202}
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
