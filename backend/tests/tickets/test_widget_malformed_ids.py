"""A malformed id gets the same response as an unknown one, never a 500."""

import uuid

import pytest
from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.notifications.middleware import get_widget_session
from apps.tickets.models import WidgetSession
from tests.factories import TicketMessageFactory

pytestmark = pytest.mark.django_db
BASE = "/api/v1/tickets"


@pytest.fixture
def headers(organization) -> dict:
    session = WidgetSession.objects.create(organization=organization)
    return {
        "HTTP_X_WIDGET_TOKEN": str(organization.api_token),
        "HTTP_X_WIDGET_SESSION": str(session.id),
    }


def _file() -> SimpleUploadedFile:
    return SimpleUploadedFile("a.txt", b"x", content_type="text/plain")


def _upload(client, ticket_id, headers):
    return client.post(
        f"{BASE}/widget_upload_attachment/",
        {"ticket": ticket_id, "file": _file()},
        format="multipart",
        **headers,
    )


def _message_attachment(client, ticket_id, headers):
    return client.post(
        f"{BASE}/widget_message_attachment/",
        {"ticket_id": ticket_id, "file": _file()},
        format="multipart",
        **headers,
    )


def _conversation(client, ticket_id, headers):
    return client.get(
        f"{BASE}/widget_conversation/", {"ticket_id": ticket_id}, **headers
    )


def _mark_read(client, ticket_id, headers):
    return client.post(
        f"{BASE}/widget_mark_read/", {"ticket_id": ticket_id}, format="json", **headers
    )


def _message_delete(client, message_id, headers):
    return client.delete(
        f"{BASE}/widget_message_delete/?message_id={message_id}", **headers
    )


ROUTES = [_upload, _message_attachment, _conversation, _mark_read, _message_delete]


@pytest.mark.usefixtures("local_media")
@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.__name__)
def test_malformed_id_reads_as_unknown(api_client, headers, route) -> None:
    unknown = route(api_client, str(uuid.uuid4()), headers)
    malformed = route(api_client, "not-a-uuid", headers)
    assert unknown.status_code == 404
    assert malformed.status_code == 404
    assert malformed.data == unknown.data


def test_mark_read_with_a_non_string_id(api_client, headers) -> None:
    res = _mark_read(api_client, ["not-a-uuid"], headers)
    assert res.status_code == 404


def test_message_delete_still_deletes(api_client, headers, organization) -> None:
    session = WidgetSession.objects.get(organization=organization)
    message = TicketMessageFactory(
        ticket__organization=organization,
        ticket__requester=None,
        author=None,
        widget_session=session,
        sender_type="user",
    )
    assert _message_delete(api_client, str(message.id), headers).status_code == 204


def test_malformed_session_is_an_invalid_session(api_client, organization) -> None:
    res = api_client.get(
        f"{BASE}/widget_history/",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        HTTP_X_WIDGET_SESSION="not-a-uuid",
    )
    assert res.status_code == 401
    assert res.data == {"error": "Invalid session."}


def test_malformed_session_to_resume_starts_a_new_one(api_client, organization) -> None:
    res = api_client.post(
        f"{BASE}/widget_session/",
        {"session_id": "not-a-uuid"},
        format="json",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
    )
    assert res.status_code == 201


@pytest.mark.usefixtures("local_media")
@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("tickets/widget_submit/", {"title": "t"}),
        ("tickets/widget_upload_attachment/", {"ticket": "x"}),
        ("tickets/widget_session/", {}),
        ("videos/widget_upload/", {}),
    ],
    ids=["submit", "upload", "session", "video"],
)
def test_malformed_token_is_an_invalid_token(api_client, path, body) -> None:
    res = api_client.post(
        f"/api/v1/{path}/".replace("//", "/"),
        body,
        format="multipart",
        HTTP_X_WIDGET_TOKEN="not-a-uuid",
    )
    assert res.status_code == 401


def test_malformed_token_on_ticket_history(api_client) -> None:
    res = api_client.get(
        f"{BASE}/widget_tickets/?external_user_id=u", HTTP_X_WIDGET_TOKEN="not-a-uuid"
    )
    assert res.status_code == 401


@pytest.mark.django_db(transaction=True)
def test_widget_socket_with_a_malformed_session_is_refused(organization) -> None:
    session = WidgetSession.objects.create(organization=organization)
    token = str(organization.api_token)
    assert async_to_sync(get_widget_session)(token, "not-a-uuid") is None
    assert async_to_sync(get_widget_session)("not-a-uuid", str(session.id)) is None
    assert async_to_sync(get_widget_session)(token, str(session.id)) == session
