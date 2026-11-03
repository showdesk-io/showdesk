"""A widget message on a resolved or closed ticket follows the mail's reopen rule.

Within ``INBOUND_EMAIL_REOPEN_DAYS`` the ticket reopens, as for a mail or the
conversation page; past that, the widget is told to start a new conversation.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.tickets.models import Ticket, TicketAttachment, TicketMessage, WidgetSession
from tests.factories import OrganizationFactory, TicketFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]

API = "/api/v1/tickets/"


def _closed_ticket(days_ago: int):
    org = OrganizationFactory()
    session = WidgetSession.objects.create(organization=org)
    ticket = TicketFactory(
        organization=org,
        widget_session=session,
        status=Ticket.Status.RESOLVED,
        resolved_at=timezone.now() - timedelta(days=days_ago),
    )
    client = APIClient()
    client.credentials(
        HTTP_X_WIDGET_TOKEN=org.api_token, HTTP_X_WIDGET_SESSION=str(session.pk)
    )
    return ticket, client


def _write(client, ticket) -> list[int]:
    message = client.post(
        f"{API}widget_message/",
        {"ticket_id": str(ticket.pk), "body": "Still broken"},
        format="json",
    )
    attachment = client.post(
        f"{API}widget_message_attachment/",
        {
            "ticket_id": str(ticket.pk),
            "body_type": "image",
            "file": SimpleUploadedFile("a.png", b"\x89PNG", "image/png"),
        },
        format="multipart",
    )
    return [message, attachment]


def test_a_recently_resolved_ticket_reopens(settings):
    settings.INBOUND_EMAIL_REOPEN_DAYS = 7
    ticket, client = _closed_ticket(days_ago=2)

    with mock.patch("apps.tickets.views.notify_ticket_update") as update:
        responses = _write(client, ticket)

    assert [res.status_code for res in responses] == [201, 201]
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.resolved_at is None
    assert TicketMessage.objects.filter(ticket=ticket).count() == 2
    update.assert_called()


def test_a_ticket_resolved_too_long_ago_takes_nothing_more(settings):
    settings.INBOUND_EMAIL_REOPEN_DAYS = 7
    ticket, client = _closed_ticket(days_ago=8)

    responses = _write(client, ticket)

    assert [res.status_code for res in responses] == [409, 409]
    assert "new conversation" in responses[0].data["error"]
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.RESOLVED
    assert not TicketMessage.objects.filter(ticket=ticket).exists()
    assert not TicketAttachment.objects.filter(ticket=ticket).exists()
