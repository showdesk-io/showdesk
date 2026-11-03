"""An agent's files reach the requester with the reply they belong to.

The agent's app uploads them first, then posts the reply naming them: they're
linked to it before anything announces or mails it.
"""

from unittest import mock

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.email_channel.outbound import MAIL_ATTACHMENTS_MAX_BYTES
from apps.tickets.models import TicketAttachment, TicketMessage, WidgetSession
from tests.factories import (
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]

ADDRESS = "ann@example.org"


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture
def agent():
    return UserFactory(organization=OrganizationFactory(), role="agent")


@pytest.fixture
def ticket(agent):
    org = agent.organization
    return TicketFactory(
        organization=org,
        requester=None,
        requester_email=ADDRESS,
        contact=ContactFactory(organization=org, email=ADDRESS),
        widget_session=WidgetSession.objects.create(organization=org),
    )


@pytest.fixture
def client(agent):
    client = APIClient()
    client.force_authenticate(user=agent)
    return client


def _upload(client, ticket, name="report.pdf", content=b"%PDF-1.4 report", **data):
    res = client.post(
        "/api/v1/attachments/",
        {
            "ticket": str(ticket.pk),
            "file": SimpleUploadedFile(name, content, "application/pdf"),
            "filename": name,
            "content_type": "application/pdf",
            "file_size": len(content),
            **data,
        },
        format="multipart",
    )
    return res


def _reply(client, ticket, attachment_ids, body="Here you go"):
    return client.post(
        "/api/v1/messages/",
        {"ticket": str(ticket.pk), "body": body, "attachment_ids": attachment_ids},
        format="json",
    )


def test_a_reply_takes_its_files_before_it_is_mailed(client, ticket):
    uploaded = _upload(client, ticket)
    assert uploaded.status_code == 201

    with mock.patch("apps.tickets.views.notify_new_message") as notify:
        res = _reply(client, ticket, [uploaded.data["id"]])

    assert res.status_code == 201
    message = TicketMessage.objects.get(pk=res.data["id"])
    assert [a.filename for a in message.attachments.all()] == ["report.pdf"]
    assert [a["filename"] for a in res.data["attachments"]] == ["report.pdf"]
    # Announced with its file, mailed with it as a real attachment.
    assert notify.call_args.args[0].attachments.count() == 1
    (sent,) = mail.outbox
    assert sent.attachments[0][:2] == ("report.pdf", b"%PDF-1.4 report")
    assert "http" not in "".join(
        line for line in sent.body.splitlines() if "report.pdf" in line
    )


def test_a_reply_cannot_take_files_that_are_not_free_on_its_ticket(
    client, ticket, agent
):
    other_ticket = TicketFactory(organization=agent.organization)
    elsewhere = _upload(client, other_ticket).data["id"]
    taken = _upload(client, ticket).data["id"]
    TicketAttachment.objects.filter(pk=taken).update(
        message=TicketMessageFactory(ticket=ticket)
    )
    foreign_org = TicketFactory()
    foreign = TicketAttachment.objects.create(
        ticket=foreign_org,
        filename="x.pdf",
        content_type="application/pdf",
        file_size=1,
    )

    for attachment_id in (elsewhere, taken, str(foreign.pk)):
        res = _reply(client, ticket, [attachment_id])
        assert res.status_code == 400, attachment_id
        assert "attachment_ids" in res.data
    # Nor can an upload name a message of another ticket.
    other_message = TicketMessageFactory(ticket=other_ticket)
    res = _upload(client, ticket, message=str(other_message.pk))
    assert res.status_code == 400
    assert "message" in res.data


def test_a_reply_mail_attaches_files_up_to_its_limit_then_points_to_the_page(
    client, ticket, monkeypatch
):
    monkeypatch.setattr("apps.email_channel.outbound.MAIL_ATTACHMENTS_MAX_BYTES", 20)
    small = _upload(client, ticket, "small.txt", b"0123456789").data["id"]
    large = _upload(client, ticket, "large.txt", b"x" * 15).data["id"]

    assert _reply(client, ticket, [small, large]).status_code == 201

    (sent,) = mail.outbox
    assert [name for name, *_ in sent.attachments] == ["small.txt"]
    assert "large.txt" in sent.body
    assert "too large to attach" in sent.body
    assert "/c/" in sent.body
    assert "amazonaws" not in sent.body and "/media/" not in sent.body
    assert MAIL_ATTACHMENTS_MAX_BYTES == 10 * 1024 * 1024


def test_the_requester_sees_the_files_in_the_widget_and_on_the_page(client, ticket):
    attachment_id = _upload(client, ticket).data["id"]
    layer = mock.Mock(group_send=mock.AsyncMock())
    with mock.patch("apps.notifications.signals.get_channel_layer", return_value=layer):
        _reply(client, ticket, [attachment_id])

    widget_events = [
        call.args[1]["data"]
        for call in layer.group_send.await_args_list
        if call.args[0].startswith("widget_session_")
    ]
    assert [a["filename"] for a in widget_events[0]["attachments"]] == ["report.pdf"]
    assert widget_events[0]["attachments"][0]["file"]

    widget = APIClient()
    widget.credentials(
        HTTP_X_WIDGET_TOKEN=ticket.organization.api_token,
        HTTP_X_WIDGET_SESSION=str(ticket.widget_session_id),
    )
    res = widget.get(
        "/api/v1/tickets/widget_conversation/", {"ticket_id": str(ticket.pk)}
    )
    (reply,) = res.data["messages"]
    assert [a["filename"] for a in reply["attachments"]] == ["report.pdf"]
