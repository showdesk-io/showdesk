"""End users only talk to the widget, not to the agents' routes."""

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.notifications.consumers import TicketConsumer
from tests.factories import EndUserFactory, TicketFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def end_user(organization):
    return EndUserFactory(organization=organization)


@pytest.fixture
def client(end_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=end_user)
    return client


@pytest.mark.parametrize("path", ["tickets", "messages", "attachments", "videos"])
def test_lists_are_forbidden(client, organization, path) -> None:
    assert client.get(f"/api/v1/{path}/").status_code == 403


def test_message_create_is_forbidden(client, organization) -> None:
    ticket = TicketFactory(organization=organization, requester=None)
    res = client.post(
        "/api/v1/messages/", {"ticket": str(ticket.id), "body": "hi"}, format="json"
    )
    assert res.status_code == 403
    assert not ticket.messages.exists()


def test_bulk_update_is_forbidden(client, organization) -> None:
    ticket = TicketFactory(organization=organization, requester=None)
    res = client.post(
        "/api/v1/tickets/bulk_update/",
        {"ids": [str(ticket.id)], "priority": "urgent"},
        format="json",
    )
    assert res.status_code == 403


def test_me_stays_available(client) -> None:
    assert client.get("/api/v1/users/me/").status_code == 200


def test_widget_routes_stay_open_to_an_end_users_jwt(client, organization) -> None:
    """Widget routes authenticate with the widget token, whoever calls them."""
    res = client.post(
        "/api/v1/tickets/widget_submit/",
        {"title": "t"},
        format="json",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
    )
    assert res.status_code == 201


@pytest.mark.usefixtures("local_media")
def test_agents_keep_their_access(authenticated_client, organization) -> None:
    ticket = TicketFactory(organization=organization, requester=None)
    for path in ["tickets", "messages", "attachments", "videos"]:
        assert authenticated_client.get(f"/api/v1/{path}/").status_code == 200
    res = authenticated_client.post(
        "/api/v1/videos/",
        {
            "ticket": str(ticket.id),
            "original_file": SimpleUploadedFile(
                "a.webm", b"x", content_type="video/webm"
            ),
        },
        format="multipart",
    )
    assert res.status_code == 201


def _connects(user) -> bool:
    async def connect() -> bool:
        communicator = WebsocketCommunicator(TicketConsumer.as_asgi(), "/ws/tickets/")
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        await communicator.disconnect()
        return connected

    return async_to_sync(connect)()


@pytest.fixture
def memory_channel_layer(settings):
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }


@pytest.mark.usefixtures("memory_channel_layer")
class TestTicketConsumer:
    def test_end_user_is_refused(self, end_user) -> None:
        assert _connects(end_user) is False

    @pytest.mark.django_db(transaction=True)
    def test_agent_connects(self, organization) -> None:
        assert _connects(UserFactory(organization=organization)) is True

    @pytest.mark.django_db(transaction=True)
    def test_user_with_no_organization_is_refused(self) -> None:
        assert _connects(UserFactory(organization=None)) is False
