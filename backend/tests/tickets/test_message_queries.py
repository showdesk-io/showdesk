"""Showing a conversation costs the same number of queries, however long it is.

``TicketMessage.sender_name`` reads the author, the widget session and the
ticket's contact: every list of messages loads them up front.
"""

from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.notifications.signals import notify_new_message
from apps.tickets.messages import create_user_message
from apps.tickets.models import TicketMessage, WidgetSession
from tests.factories import (
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def _conversation(rounds: int):
    org = OrganizationFactory()
    session = WidgetSession.objects.create(organization=org, name="Ann")
    ticket = TicketFactory(
        organization=org,
        widget_session=session,
        contact=ContactFactory(organization=org, name="Ann"),
    )
    for _ in range(rounds):
        TicketMessageFactory(
            ticket=ticket, author=UserFactory(organization=org, role="agent")
        )
        TicketMessageFactory(
            ticket=ticket,
            author=None,
            sender_type=TicketMessage.SenderType.USER,
            widget_session=WidgetSession.objects.create(organization=org),
        )
        TicketMessageFactory(
            ticket=ticket,
            author=None,
            sender_type=TicketMessage.SenderType.USER,
            channel=TicketMessage.Channel.EMAIL,
        )
    client = APIClient()
    client.credentials(
        HTTP_X_WIDGET_TOKEN=org.api_token, HTTP_X_WIDGET_SESSION=str(session.pk)
    )
    return ticket, client


def _queries(client, ticket) -> int:
    with CaptureQueriesContext(connection) as queries:
        res = client.get(
            "/api/v1/tickets/widget_conversation/", {"ticket_id": str(ticket.pk)}
        )
    assert res.status_code == 200
    return len(queries)


def test_the_widget_conversation_loads_its_senders_up_front():
    short = _queries(*reversed(_conversation(1)))
    long = _queries(*reversed(_conversation(4)))

    assert long == short


def test_a_ticket_shown_to_agents_loads_its_senders_up_front():
    def queries(ticket) -> int:
        agent = UserFactory(organization=ticket.organization, role="agent")
        client = APIClient()
        client.force_authenticate(user=agent)
        with CaptureQueriesContext(connection) as captured:
            res = client.get(f"/api/v1/tickets/{ticket.pk}/")
        assert res.status_code == 200
        return len(captured)

    assert queries(_conversation(4)[0]) == queries(_conversation(1)[0])


def test_a_widget_message_is_announced_without_loading_its_session_again():
    ticket, _ = _conversation(0)
    message = create_user_message(ticket, session=ticket.widget_session, body="Hello")
    layer = mock.Mock(group_send=mock.AsyncMock())

    with (
        mock.patch("apps.notifications.signals.get_channel_layer", return_value=layer),
        CaptureQueriesContext(connection) as captured,
    ):
        notify_new_message(message)

    sent = layer.group_send.await_args_list[-1].args[1]["data"]
    assert sent["sender_name"] == "Ann"
    lookups = [
        query["sql"]
        for query in captured
        if 'FROM "tickets_widgetsession"' in query["sql"] and "LIMIT 21" in query["sql"]
    ]
    assert lookups == []
