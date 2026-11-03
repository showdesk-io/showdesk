"""Whether a widget session has the widget open, as its socket tells (design §5.2)."""

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator

from apps.email_channel import presence
from apps.notifications.consumers import WidgetConsumer
from apps.tickets.models import WidgetSession
from tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _in_memory_channel_layer(settings):
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }


@pytest.fixture
def session():
    return WidgetSession.objects.create(organization=OrganizationFactory())


def test_a_session_is_connected_from_its_mark_until_it_leaves():
    assert not presence.is_connected("s1")
    assert not presence.is_connected(None)

    presence.mark_connected("s1")
    assert presence.is_connected("s1")
    assert not presence.is_connected("s2")

    presence.mark_disconnected("s1")
    assert not presence.is_connected("s1")


def test_the_widget_socket_marks_its_session_on_connect_ping_and_disconnect(session):
    session_id = str(session.id)
    seen = {}

    async def run() -> None:
        communicator = WebsocketCommunicator(WidgetConsumer.as_asgi(), "/ws/widget/")
        communicator.scope["widget_session"] = session
        await communicator.connect()
        seen["connected"] = presence.is_connected(session_id)

        # Expired while the socket stays open: the next ping marks it again.
        presence.mark_disconnected(session_id)
        await communicator.send_json_to({"type": "ping"})
        assert await communicator.receive_json_from() == {"type": "pong"}
        seen["pinged"] = presence.is_connected(session_id)

        await communicator.disconnect()
        seen["left"] = presence.is_connected(session_id)

    async_to_sync(run)()

    assert seen == {"connected": True, "pinged": True, "left": False}
