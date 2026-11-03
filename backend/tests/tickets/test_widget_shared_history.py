"""A widget session's view of its contact's other conversations (design §6.2).

Session tickets and ``external_user_id`` tickets as before, and the contact's
tickets when the session is identified on that contact or proved the address the
contact holds. Every route taking a ticket id goes through the same rule.
"""

from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.notifications.signals import notify_message_deleted, notify_new_message
from apps.tickets.access import (
    contact_history_opens,
    session_tickets,
    ticket_session_ids,
)
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
    if proven:
        fields.setdefault("email_verified_for", fields["email"].strip().lower())
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

    def test_the_conversation_tells_which_messages_the_session_may_delete(
        self, org, holder, email_ticket
    ):
        """The widget offers to delete only what the session wrote."""
        session = _session(org, holder, proven=True)
        mailed = TicketMessageFactory(
            ticket=email_ticket,
            author=None,
            sender_type=TicketMessage.SenderType.USER,
        )
        own = TicketMessageFactory(
            ticket=email_ticket,
            author=None,
            sender_type=TicketMessage.SenderType.USER,
            widget_session=session,
        )
        reply = TicketMessageFactory(
            ticket=email_ticket, sender_type=TicketMessage.SenderType.AGENT
        )

        res = _client(org, session).get(
            f"{API}widget_conversation/", {"ticket_id": str(email_ticket.pk)}
        )

        deletable = {m["id"]: m["deletable"] for m in res.json()["messages"]}
        assert deletable == {
            str(mailed.pk): False,
            str(own.pk): True,
            str(reply.pk): False,
        }


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

        assert ticket_session_ids(email_ticket) == [str(proven.pk)]
        assert sent == [f"org_{org.id}", f"widget_session_{proven.pk}"]


def _sent_groups(notify, *args) -> list[str]:
    sent = []

    async def group_send(group, event):
        sent.append(group)

    with mock.patch("apps.notifications.signals.get_channel_layer") as layer:
        layer.return_value.group_send = group_send
        notify(*args)
    return sent


class TestProofOfAnotherAddress:
    def test_a_proof_recorded_for_another_address_opens_nothing(
        self, org, holder, email_ticket
    ):
        """What a verify racing an email change would have left: a date, not for this."""
        session = _session(org, holder, proven=True, email_verified_for="b@x.io")
        assert not contact_history_opens(session)
        assert _history(_client(org, session)) == []
        assert ticket_session_ids(email_ticket) == []

    def test_a_ticket_written_under_it_is_not_verified(self, org, holder):
        session = _session(org, holder, proven=True, email_verified_for="b@x.io")
        ticket = TicketFactory(organization=org, contact=holder, widget_session=session)
        assert ticket.sender_verified is False


@pytest.mark.usefixtures("local_media")
class TestWritingFromHistory:
    def test_not_on_a_ticket_opened_by_a_session_without_access(self, org, holder):
        """The owner's unproven session opened it: posting would send them our words."""
        opener = _session(org, holder)
        ticket = TicketFactory(organization=org, contact=holder, widget_session=opener)
        client = _client(org, _session(org, holder, proven=True))

        res = client.post(
            f"{API}widget_message/",
            {"ticket_id": str(ticket.pk), "body": "Hello"},
            format="json",
        )
        conversation = client.get(
            f"{API}widget_conversation/", {"ticket_id": str(ticket.pk)}
        )

        assert res.status_code == 403
        assert "Start a new conversation" in res.data["error"]
        assert not ticket.messages.exists()
        assert (conversation.status_code, conversation.data["read_only"]) == (200, True)

    def test_on_a_ticket_opened_by_an_entitled_session(self, org, holder):
        opener = _session(org, holder, proven=True)
        ticket = TicketFactory(organization=org, contact=holder, widget_session=opener)
        client = _client(org, _session(org, holder, proven=True))

        res = client.post(
            f"{API}widget_message/",
            {"ticket_id": str(ticket.pk), "body": "Hello"},
            format="json",
        )

        assert res.status_code == 201
        conversation = client.get(
            f"{API}widget_conversation/", {"ticket_id": str(ticket.pk)}
        )
        assert conversation.data["read_only"] is False


class TestDeleting:
    def test_not_on_a_ticket_the_session_no_longer_sees(
        self, org, holder, email_ticket
    ):
        session = _session(org, holder, proven=True)
        mine = TicketMessageFactory(
            ticket=email_ticket,
            author=None,
            widget_session=session,
            sender_type=TicketMessage.SenderType.USER,
        )
        client = _client(org, session)
        client.patch(f"{API}widget_session/", {"email": "b@x.io"}, format="json")

        res = client.delete(f"{API}widget_message_delete/?message_id={mine.pk}")

        assert res.status_code == 404
        assert TicketMessage.objects.filter(pk=mine.pk).exists()

    def test_a_deletion_reaches_every_entitled_session(self, org, holder, email_ticket):
        proven = _session(org, holder, proven=True)
        _session(org, holder)

        groups = _sent_groups(
            notify_message_deleted, email_ticket, "m1", TicketMessage.MessageType.REPLY
        )

        assert groups == [f"org_{org.id}", f"widget_session_{proven.pk}"]


def test_a_first_message_survives_a_contact_deleted_meanwhile(org, holder):
    """The session as read names a contact a reunion has since deleted."""
    session = _session(org, holder)
    stale = WidgetSession.objects.get(pk=session.pk)
    holder.delete()
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with mock.patch(
        "apps.tickets.views._get_widget_session", return_value=(stale, None)
    ):
        res = _client(org, session).post(
            f"{API}widget_message/", {"body": "Hello"}, format="json"
        )

    assert res.status_code == 201
    assert Ticket.objects.get(pk=res.data["ticket_id"]).contact_id is None


@pytest.mark.usefixtures("local_media")
class TestTicketsWithoutASession:
    def test_a_forged_widget_submit_ticket_is_read_only(self, org):
        """The public token alone names the victim's external id and the attacker's
        address: the victim's history shows it, but writing there would mail them."""
        victim = ContactFactory(organization=org, email="v@x.io", external_id="u1")
        session = _session(org, victim, external_user_id="u1")
        res = APIClient().post(
            f"{API}widget_submit/",
            {
                "title": "Your invoice",
                "description": "Please answer here",
                "external_user_id": "u1",
                "requester_email": "attacker@evil.io",
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=org.api_token,
        )
        forged = Ticket.objects.get(reference=res.data["reference"])
        client = _client(org, session)

        assert str(forged.pk) in _history(client)
        assert _by_id(client, forged) == {
            "conversation": 200,
            "message": 403,
            "attachment": 403,
            "mark_read": 403,
        }
        conversation = client.get(
            f"{API}widget_conversation/", {"ticket_id": str(forged.pk)}
        )
        assert conversation.data["read_only"] is True
        assert not forged.messages.exists()

    def test_an_email_ticket_replying_elsewhere_is_read_only(self, org, holder):
        ticket = _email_ticket(org, holder)
        Ticket.objects.filter(pk=ticket.pk).update(requester_email="other@x.io")
        client = _client(org, _session(org, holder, proven=True))

        assert _by_id(client, ticket)["message"] == 403


class TestMarkingRead:
    def test_a_history_only_reader_does_not_mark_the_openers_conversation(
        self, org, holder
    ):
        opener = _session(org, holder)
        ticket = TicketFactory(organization=org, contact=holder, widget_session=opener)
        client = _client(org, _session(org, holder, proven=True))

        res = client.post(
            f"{API}widget_mark_read/", {"ticket_id": str(ticket.pk)}, format="json"
        )

        assert res.status_code == 403
        ticket.refresh_from_db()
        assert ticket.widget_last_read_at is None


def test_a_deleted_internal_note_reaches_no_widget(org, holder, email_ticket):
    _session(org, holder, proven=True)

    groups = _sent_groups(
        notify_message_deleted,
        email_ticket,
        "m1",
        TicketMessage.MessageType.INTERNAL_NOTE,
    )

    assert groups == [f"org_{org.id}"]
