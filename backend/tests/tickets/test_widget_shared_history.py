"""A widget session's view of its contact's other conversations (design §6.2).

Session tickets and ``external_user_id`` tickets as before, and the contact's
tickets when the session is identified on that contact or proved the address the
contact holds. Every route taking a ticket id goes through the same rule.
"""

from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.email_channel import outbound
from apps.notifications.signals import notify_new_message
from apps.tickets.access import contact_history_opens, session_tickets
from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from tests.factories import (
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

API = "/api/v1/tickets/"


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def holder(org):
    return ContactFactory(organization=org, email="a@x.io")


@pytest.fixture
def email_ticket(org, holder):
    return _email_ticket(org, holder)


def _email_ticket(org, contact):
    return TicketFactory(
        organization=org,
        contact=contact,
        source=Ticket.Source.EMAIL,
        requester=None,
        requester_email=contact.email,
        widget_session=None,
    )


def _session(org, contact=None, *, proven=False, **fields):
    fields.setdefault("email", contact.email if contact else "")
    return WidgetSession.objects.create(
        organization=org,
        contact=contact,
        email_verified_at=timezone.now() if proven else None,
        **fields,
    )


def _client(org, session) -> APIClient:
    client = APIClient()
    client.credentials(
        HTTP_X_WIDGET_TOKEN=org.api_token, HTTP_X_WIDGET_SESSION=str(session.pk)
    )
    return client


def _by_id(client, ticket) -> dict[str, int]:
    """Each route taking a ticket id, with what it answered on ``ticket``."""
    ticket_id = str(ticket.pk)
    return {
        "conversation": client.get(
            f"{API}widget_conversation/", {"ticket_id": ticket_id}
        ).status_code,
        "message": client.post(
            f"{API}widget_message/",
            {"ticket_id": ticket_id, "body": "Hello"},
            format="json",
        ).status_code,
        "attachment": client.post(
            f"{API}widget_message_attachment/",
            {
                "ticket_id": ticket_id,
                "body_type": "image",
                "file": SimpleUploadedFile("a.png", b"\x89PNG", "image/png"),
            },
            format="multipart",
        ).status_code,
        "mark_read": client.post(
            f"{API}widget_mark_read/", {"ticket_id": ticket_id}, format="json"
        ).status_code,
    }


def _history(client) -> list[str]:
    return [row["id"] for row in client.get(f"{API}widget_history/").data]


REFUSED = {"conversation": 404, "message": 404, "attachment": 404, "mark_read": 404}


@pytest.mark.usefixtures("local_media")
class TestRefused:
    def test_an_unproven_session_on_the_contact(self, org, holder, email_ticket):
        client = _client(org, _session(org, holder))
        assert _by_id(client, email_ticket) == REFUSED
        assert _history(client) == []

    def test_a_session_proven_on_another_contacts_address(
        self, org, holder, email_ticket
    ):
        other = ContactFactory(organization=org, email="b@x.io")
        client = _client(org, _session(org, other, proven=True))
        assert _by_id(client, email_ticket) == REFUSED
        assert _history(client) == []

    def test_a_proof_in_another_session_opens_nothing_here(
        self, org, holder, email_ticket
    ):
        _session(org, holder, proven=True)
        client = _client(org, _session(org, holder))
        assert _by_id(client, email_ticket) == REFUSED

    def test_a_changed_email_drops_the_access(self, org, holder, email_ticket):
        session = _session(org, holder, proven=True)
        client = _client(org, session)
        assert email_ticket.pk in [t.pk for t in session_tickets(session)]

        client.patch(f"{API}widget_session/", {"email": "b@x.io"}, format="json")

        assert _by_id(client, email_ticket) == REFUSED
        assert _history(client) == []

    def test_an_anonymized_contact_opens_nothing(self, org, holder, email_ticket):
        session = _session(org, holder, proven=True)
        type(holder).objects.filter(pk=holder.pk).update(is_anonymized=True)
        session.refresh_from_db()
        assert not contact_history_opens(session)
        assert _history(_client(org, session)) == []

    def test_another_organizations_ticket(self, org, holder):
        elsewhere = TicketFactory(organization=OrganizationFactory(), contact=holder)
        client = _client(org, _session(org, holder, proven=True))
        assert _by_id(client, elsewhere) == REFUSED
        assert _history(client) == []


@pytest.mark.usefixtures("local_media")
class TestShared:
    def test_a_proven_session_sees_and_writes_on_the_contacts_tickets(
        self, org, holder, email_ticket
    ):
        session = _session(org, holder, proven=True)
        client = _client(org, session)

        assert _history(client) == [str(email_ticket.pk)]
        assert _by_id(client, email_ticket) == {
            "conversation": 200,
            "message": 201,
            "attachment": 201,
            "mark_read": 200,
        }
        posted = email_ticket.messages.filter(sender_type="user")
        assert {m.widget_session_id for m in posted} == {session.pk}

    def test_an_identified_contacts_agent_set_email_opens_its_tickets(self, org):
        """§6.2: through an identified contact, an email set by an agent counts."""
        contact = ContactFactory(organization=org, email="a@x.io", external_id="u1")
        ticket = _email_ticket(org, contact)
        session = _session(org, contact, external_user_id="u1")

        assert _history(_client(org, session)) == [str(ticket.pk)]

    def test_deleting_stays_on_the_sessions_own_messages(
        self, org, holder, email_ticket
    ):
        mailed = TicketMessageFactory(
            ticket=email_ticket,
            author=None,
            sender_type=TicketMessage.SenderType.USER,
        )
        client = _client(org, _session(org, holder, proven=True))

        res = client.delete(
            f"{API}widget_message_delete/?message_id={mailed.pk}",
        )

        assert res.status_code == 404
        assert TicketMessage.objects.filter(pk=mailed.pk).exists()


class TestReplies:
    def test_replies_reach_every_entitled_session(self, org, holder, email_ticket):
        proven = _session(org, holder, proven=True)
        _session(org, holder)  # Unproven: nothing reaches it.
        reply = TicketMessageFactory(
            ticket=email_ticket,
            author=UserFactory(organization=org, role="agent"),
            sender_type=TicketMessage.SenderType.AGENT,
        )
        sent = []

        async def group_send(group, event):
            sent.append(group)

        with mock.patch("apps.notifications.signals.get_channel_layer") as layer:
            layer.return_value.group_send = group_send
            notify_new_message(reply)

        assert outbound.entitled_session_ids(email_ticket) == [str(proven.pk)]
        assert sent == [f"org_{org.id}", f"widget_session_{proven.pk}"]
