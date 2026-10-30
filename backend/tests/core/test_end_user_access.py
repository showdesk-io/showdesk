"""End users only talk to the widget, not to the agents' routes."""

from types import SimpleNamespace

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.notifications.consumers import TicketConsumer
from apps.organizations.admin import UserAdmin
from apps.organizations.models import OTPCode, User
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


class TestEndUserLeftWithIsStaff:
    """The role decides: is_staff alone, left by a demotion, opens nothing."""

    @pytest.fixture
    def demoted(self, organization):
        return EndUserFactory(
            organization=organization, is_staff=True, email="demoted@example.com"
        )

    @pytest.mark.parametrize("path", ["tickets", "messages", "attachments", "videos"])
    def test_lists_are_forbidden(self, demoted, path) -> None:
        client = APIClient()
        client.force_authenticate(user=demoted)
        assert client.get(f"/api/v1/{path}/").status_code == 403

    @pytest.mark.usefixtures("memory_channel_layer")
    def test_socket_is_refused(self, demoted) -> None:
        assert _connects(demoted) is False

    def test_no_code_is_sent(self, demoted) -> None:
        res = APIClient().post("/api/v1/auth/request-otp/", {"email": demoted.email})
        assert res.status_code == 200
        assert not OTPCode.objects.filter(email=demoted.email).exists()

    def test_a_code_does_not_log_in(self, demoted) -> None:
        otp = OTPCode.generate(demoted.email)
        res = APIClient().post(
            "/api/v1/auth/verify-otp/", {"email": demoted.email, "code": otp.code}
        )
        assert res.status_code == 401

    def test_superusers_keep_their_access(self, organization) -> None:
        superuser = EndUserFactory(
            organization=organization, is_staff=True, is_superuser=True
        )
        client = APIClient()
        client.force_authenticate(user=superuser)
        assert client.get("/api/v1/tickets/").status_code == 200


class TestDemotionClearsIsStaff:
    def _patch(self, admin_client, user, role):
        return admin_client.patch(
            f"/api/v1/users/{user.id}/", {"role": role}, format="json"
        )

    def test_to_end_user(self, admin_client, organization) -> None:
        agent = UserFactory(organization=organization, is_staff=True)
        assert self._patch(admin_client, agent, "end_user").status_code == 200
        agent.refresh_from_db()
        assert agent.role == "end_user"
        assert agent.is_staff is False

    def test_not_to_another_role(self, admin_client, organization) -> None:
        agent = UserFactory(organization=organization, is_staff=True)
        assert self._patch(admin_client, agent, "admin").status_code == 200
        agent.refresh_from_db()
        assert agent.is_staff is True

    def test_a_superuser_keeps_it(self, organization) -> None:
        superuser = UserFactory(
            organization=organization, is_staff=True, is_superuser=True
        )
        client = APIClient()
        client.force_authenticate(user=superuser)
        target = UserFactory(
            organization=organization, is_staff=True, is_superuser=True
        )
        assert self._patch(client, target, "end_user").status_code == 200
        target.refresh_from_db()
        assert target.is_staff is True

    def test_from_the_django_admin(self, organization) -> None:
        agent = UserFactory(organization=organization, is_staff=True)
        agent.role = "end_user"
        form = SimpleNamespace(changed_data=["role"])
        UserAdmin(User, AdminSite()).save_model(None, agent, form, change=True)
        agent.refresh_from_db()
        assert agent.is_staff is False
