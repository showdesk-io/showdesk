"""A widget's token and session only reach the tickets of their organization.

The widget's token is public, so nothing here relies on who holds it.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.tickets.models import TicketMessage, WidgetSession
from tests.factories import OrganizationFactory, TicketFactory, TicketMessageFactory

pytestmark = pytest.mark.django_db
BASE = "/api/v1/tickets"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    """Local files, as the default storage needs an S3 server."""
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path)},
        },
    }


@pytest.fixture
def headers(organization) -> dict:
    session = WidgetSession.objects.create(organization=organization)
    return {
        "HTTP_X_WIDGET_TOKEN": str(organization.api_token),
        "HTTP_X_WIDGET_SESSION": str(session.id),
    }


@pytest.fixture
def foreign_ticket():
    """A ticket of another organization, and of a session of that organization."""
    org = OrganizationFactory()
    session = WidgetSession.objects.create(organization=org)
    return TicketFactory(organization=org, widget_session=session, requester=None)


def _file() -> SimpleUploadedFile:
    return SimpleUploadedFile("a.txt", b"x", content_type="text/plain")


def test_upload_attachment(api_client, headers, foreign_ticket):
    res = api_client.post(
        f"{BASE}/widget_upload_attachment/",
        {"ticket": str(foreign_ticket.id), "file": _file()},
        format="multipart",
        **headers,
    )
    assert res.status_code == 404
    assert not foreign_ticket.attachments.exists()


def test_message(api_client, headers, foreign_ticket):
    res = api_client.post(
        f"{BASE}/widget_message/",
        {"ticket_id": str(foreign_ticket.id), "body": "hello"},
        format="json",
        **headers,
    )
    assert res.status_code == 404
    assert not foreign_ticket.messages.exists()


def test_message_attachment(api_client, headers, foreign_ticket):
    res = api_client.post(
        f"{BASE}/widget_message_attachment/",
        {"ticket_id": str(foreign_ticket.id), "file": _file()},
        format="multipart",
        **headers,
    )
    assert res.status_code == 404
    assert not foreign_ticket.messages.exists()


def test_mark_read(api_client, headers, foreign_ticket):
    res = api_client.post(
        f"{BASE}/widget_mark_read/",
        {"ticket_id": str(foreign_ticket.id)},
        format="json",
        **headers,
    )
    assert res.status_code == 404
    foreign_ticket.refresh_from_db()
    assert foreign_ticket.widget_last_read_at is None


def test_conversation(api_client, headers, foreign_ticket):
    res = api_client.get(
        f"{BASE}/widget_conversation/?ticket_id={foreign_ticket.id}", **headers
    )
    assert res.status_code == 404


def test_message_delete(api_client, headers, foreign_ticket):
    message = TicketMessageFactory(
        ticket=foreign_ticket,
        author=None,
        widget_session=foreign_ticket.widget_session,
        sender_type=TicketMessage.SenderType.USER,
    )
    res = api_client.delete(
        f"{BASE}/widget_message_delete/?message_id={message.id}", **headers
    )
    assert res.status_code == 404
    assert TicketMessage.objects.filter(pk=message.pk).exists()


def test_a_session_of_another_organization_is_refused(
    api_client, organization, foreign_ticket
):
    res = api_client.get(
        f"{BASE}/widget_conversation/?ticket_id={foreign_ticket.id}",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        HTTP_X_WIDGET_SESSION=str(foreign_ticket.widget_session_id),
    )
    assert res.status_code == 401
