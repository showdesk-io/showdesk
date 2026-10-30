"""Tests for the widget_session POST endpoint (create/resume)."""

import hashlib
import hmac
from unittest import mock

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from tests.factories import ContactFactory, OrganizationFactory, TicketFactory

URL = "/api/v1/tickets/widget_session/"


def _hash(secret: str, external_user_id: str) -> str:
    return hmac.new(
        secret.encode(),
        external_user_id.encode(),
        hashlib.sha256,
    ).hexdigest()


@pytest.mark.django_db
class TestWidgetSessionResume:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.org = OrganizationFactory()
        self.client = APIClient()

    def _post(self, **body):
        return self.client.post(
            URL,
            data=body,
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
        )

    def test_resume_with_matching_external_user_id(self):
        """Same user resuming their own session — works as before."""
        session = WidgetSession.objects.create(
            organization=self.org, external_user_id="user-A"
        )
        response = self._post(
            session_id=str(session.id),
            external_user_id="user-A",
            user_hash=_hash(self.org.widget_secret, "user-A"),
        )
        assert response.status_code == 200
        assert response.data["session_id"] == str(session.id)

    def test_resume_falls_through_when_external_user_id_mismatches(self):
        """A different user reusing a stale session_id from localStorage
        must NOT inherit the previous user's conversation. Instead, the
        backend creates (or finds) a session for the new user."""
        owned_by_a = WidgetSession.objects.create(
            organization=self.org, external_user_id="user-A"
        )
        response = self._post(
            session_id=str(owned_by_a.id),
            external_user_id="user-B",
            user_hash=_hash(self.org.widget_secret, "user-B"),
        )
        assert response.status_code == 201
        assert response.data["session_id"] != str(owned_by_a.id)
        assert response.data["external_user_id"] == "user-B"

    def test_resume_finds_existing_session_for_user_b(self):
        """If user-B already has their own session, the mismatched stale
        session_id is dropped and user-B's real session is returned."""
        WidgetSession.objects.create(organization=self.org, external_user_id="user-A")
        owned_by_b = WidgetSession.objects.create(
            organization=self.org, external_user_id="user-B"
        )
        response = self._post(
            session_id=str(WidgetSession.objects.get(external_user_id="user-A").id),
            external_user_id="user-B",
            user_hash=_hash(self.org.widget_secret, "user-B"),
        )
        assert response.status_code == 200
        assert response.data["session_id"] == str(owned_by_b.id)

    def test_login_replaces_the_anonymous_session_with_the_identified_one(self):
        """A valid hash on an anonymous session is a login: the widget stores
        the identified session returned, and the conversation moves to it."""
        anon = WidgetSession.objects.create(organization=self.org)
        response = self._post(
            session_id=str(anon.id),
            external_user_id="user-A",
            user_hash=_hash(self.org.widget_secret, "user-A"),
        )
        assert response.status_code == 201
        assert response.data["session_id"] != str(anon.id)
        assert response.data["external_user_id"] == "user-A"
        anon.refresh_from_db()
        assert anon.external_user_id == ""


@pytest.mark.django_db
class TestLogin:
    """An anonymous session resumed with a valid user_hash."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.org = OrganizationFactory()
        self.client = APIClient()
        self.anon = WidgetSession.objects.create(organization=self.org)
        self.identity = {
            "external_user_id": "u1",
            "user_hash": _hash(self.org.widget_secret, "u1"),
        }

    def _post(self, **body):
        return self.client.post(
            URL, data=body, format="json", HTTP_X_WIDGET_TOKEN=self.org.api_token
        )

    def _login(self, **body):
        return self._post(session_id=str(self.anon.id), **self.identity, **body)

    def _ticket(self, session=None, **kwargs):
        return TicketFactory(
            organization=kwargs.pop("organization", self.org),
            widget_session=session or self.anon,
            requester=None,
            **kwargs,
        )

    def _get(self, path, session_id, **params):
        return self.client.get(
            f"/api/v1/tickets/{path}/",
            params,
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
            HTTP_X_WIDGET_SESSION=session_id,
        )

    def test_tickets_move_to_the_identified_contact(self):
        email_only = ContactFactory(organization=self.org, email="a@x.io")
        ticket = self._ticket(contact=email_only)
        contactless = self._ticket(contact=None)
        session_id = self._login().data["session_id"]
        identified = WidgetSession.objects.get(id=session_id)
        for moved in (ticket, contactless):
            moved.refresh_from_db()
            assert moved.widget_session == identified
            assert moved.external_user_id == "u1"
            assert moved.contact == identified.contact
            assert moved.contact.external_id == "u1"

    def test_messages_move_too(self):
        ticket = self._ticket()
        mine = TicketMessage.objects.create(
            ticket=ticket, widget_session=self.anon, body="Hi"
        )
        agents = TicketMessage.objects.create(ticket=ticket, body="Hello")
        session_id = self._login().data["session_id"]
        mine.refresh_from_db()
        agents.refresh_from_db()
        assert str(mine.widget_session_id) == session_id
        assert agents.widget_session is None

    def test_the_conversation_goes_on_in_the_widget(self):
        ticket = self._ticket()
        TicketMessage.objects.create(ticket=ticket, widget_session=self.anon, body="Hi")
        session_id = self._login().data["session_id"]
        history = self._get("widget_history", session_id)
        assert [row["id"] for row in history.data] == [str(ticket.id)]
        conversation = self._get(
            "widget_conversation", session_id, ticket_id=str(ticket.id)
        )
        assert conversation.status_code == 200
        assert [m["body"] for m in conversation.data["messages"]] == ["Hi"]
        reply = self.client.post(
            "/api/v1/tickets/widget_message/",
            {"body": "Still me", "ticket_id": str(ticket.id)},
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
            HTTP_X_WIDGET_SESSION=session_id,
        )
        assert reply.status_code == 201

    def test_moved_tickets_are_marked_as_written_before_the_login(self):
        ticket = self._ticket(context_metadata={"locale": "fr"})
        self._login()
        ticket.refresh_from_db()
        assert ticket.context_metadata == {"locale": "fr", "pre_login_anonymous": True}

    @pytest.mark.parametrize("metadata", [[], "text", 1])
    def test_marking_copes_with_any_stored_metadata(self, metadata):
        ticket = self._ticket()
        Ticket.objects.filter(pk=ticket.pk).update(context_metadata=metadata)
        self._login()
        ticket.refresh_from_db()
        assert ticket.context_metadata == {"pre_login_anonymous": True}

    def test_a_ticket_opened_after_the_login_isnt_marked(self):
        session_id = self._login().data["session_id"]
        res = self.client.post(
            "/api/v1/tickets/widget_message/",
            {"body": "Help"},
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
            HTTP_X_WIDGET_SESSION=session_id,
        )
        ticket = Ticket.objects.get(id=res.data["ticket_id"])
        assert "pre_login_anonymous" not in ticket.context_metadata

    def test_joins_the_session_the_user_already_has(self):
        existing = WidgetSession.objects.create(
            organization=self.org, external_user_id="u1"
        )
        own = self._ticket(session=existing)
        moved = self._ticket()
        res = self._login()
        assert res.status_code == 200
        assert res.data["session_id"] == str(existing.id)
        own.refresh_from_db()
        moved.refresh_from_db()
        assert moved.widget_session == existing
        assert own.context_metadata == {}
        assert moved.context_metadata == {"pre_login_anonymous": True}

    def test_is_idempotent(self):
        ticket = self._ticket(context_metadata={"locale": "fr"})
        first = self._login()
        ticket.refresh_from_db()
        moved = (ticket.widget_session_id, ticket.context_metadata)
        second = self._login()
        assert second.status_code == 200
        assert second.data["session_id"] == first.data["session_id"]
        ticket.refresh_from_db()
        assert (ticket.widget_session_id, ticket.context_metadata) == moved
        assert WidgetSession.objects.filter(external_user_id="u1").count() == 1

    def test_failure_moves_nothing_and_the_widget_can_retry(self):
        ticket = self._ticket()
        message = TicketMessage.objects.create(
            ticket=ticket, widget_session=self.anon, body="Hi"
        )
        with (
            mock.patch(
                "apps.tickets.views.TicketMessage.objects.filter",
                side_effect=OperationalError,
            ),
            pytest.raises(OperationalError),
        ):
            # Not swallowed: the widget must keep the id of the session to move.
            self._login()
        ticket.refresh_from_db()
        assert ticket.widget_session == self.anon
        assert ticket.context_metadata == {}
        assert self._login().status_code == 200
        ticket.refresh_from_db()
        message.refresh_from_db()
        assert ticket.widget_session.external_user_id == "u1"
        assert message.widget_session.external_user_id == "u1"

    def test_contact_that_cant_be_used_leaves_the_tickets_one_alone(self):
        email_only = ContactFactory(organization=self.org, email="a@x.io")
        ContactFactory(organization=self.org, external_id="u1", is_anonymized=True)
        ticket = self._ticket(contact=email_only)
        session_id = self._login().data["session_id"]
        ticket.refresh_from_db()
        assert str(ticket.widget_session_id) == session_id
        assert ticket.contact == email_only

    @pytest.mark.parametrize("user_hash", ["forged", None, "", ["x"], "é"])
    def test_without_a_valid_hash_the_anonymous_session_goes_on(self, user_hash):
        ticket = self._ticket()
        res = self._post(
            session_id=str(self.anon.id), external_user_id="u1", user_hash=user_hash
        )
        assert res.status_code == 200
        assert res.data["session_id"] == str(self.anon.id)
        assert res.data["external_user_id"] == ""
        ticket.refresh_from_db()
        assert ticket.widget_session == self.anon
        assert ticket.external_user_id == ""
        assert not Contact.objects.filter(external_id="u1").exists()

    def test_without_a_widget_secret_the_anonymous_session_goes_on(self):
        org = OrganizationFactory(widget_secret="")
        anon = WidgetSession.objects.create(organization=org)
        res = self.client.post(
            URL,
            {"session_id": str(anon.id), "external_user_id": "u1", "user_hash": "x"},
            format="json",
            HTTP_X_WIDGET_TOKEN=org.api_token,
        )
        assert res.status_code == 200
        assert res.data["session_id"] == str(anon.id)

    def test_a_session_of_another_organization_is_left_alone(self):
        foreign_session = WidgetSession.objects.create(
            organization=OrganizationFactory()
        )
        foreign = TicketFactory(
            organization=foreign_session.organization,
            widget_session=foreign_session,
            requester=None,
        )
        res = self._post(session_id=str(foreign_session.id), **self.identity)
        assert res.status_code == 201
        assert res.data["session_id"] != str(foreign_session.id)
        foreign.refresh_from_db()
        assert foreign.widget_session == foreign_session
        assert foreign.external_user_id == ""

    def test_a_ticket_of_another_organization_is_left_alone(self):
        other_org = OrganizationFactory()
        foreign = self._ticket(organization=other_org)
        message = TicketMessage.objects.create(
            ticket=foreign, widget_session=self.anon, body="Hi"
        )
        self._login()
        foreign.refresh_from_db()
        message.refresh_from_db()
        assert foreign.widget_session == self.anon
        assert message.widget_session == self.anon


@pytest.mark.django_db
class TestLogout:
    """A stored identified session is only resumed with a valid hash for its id."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.org = OrganizationFactory()
        self.client = APIClient()
        self.contact = ContactFactory(
            organization=self.org, external_id="u1", name="Alice", email=""
        )
        self.session = WidgetSession.objects.create(
            organization=self.org,
            external_user_id="u1",
            contact=self.contact,
            name="Alice",
            email="alice@x.io",
        )
        self.ticket = TicketFactory(
            organization=self.org,
            widget_session=self.session,
            external_user_id="u1",
            contact=self.contact,
            requester=None,
        )

    def _post(self, **body):
        return self.client.post(
            URL,
            data={"session_id": str(self.session.id), **body},
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
        )

    def _rows(self):
        session = WidgetSession.objects.filter(pk=self.session.pk).values().get()
        contact = Contact.objects.filter(pk=self.contact.pk).values().get()
        return session, contact

    def test_no_identity_starts_an_anonymous_session(self):
        before = self._rows()
        res = self._post(
            name="Mallory",
            email="mallory@x.io",
            traits={"plan": "free"},
            company={"id": "c1", "name": "Evil"},
        )
        assert res.status_code == 201
        assert res.data["session_id"] != str(self.session.id)
        assert res.data["external_user_id"] == ""
        assert self._rows() == before
        new = WidgetSession.objects.get(id=res.data["session_id"])
        assert new.contact != self.contact
        assert new.contact.email == "mallory@x.io"

    def test_no_identity_doesnt_expose_the_users_history(self):
        session_id = self._post().data["session_id"]
        history = self.client.get(
            "/api/v1/tickets/widget_history/",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
            HTTP_X_WIDGET_SESSION=session_id,
        )
        assert history.data == []
        self.ticket.refresh_from_db()
        assert self.ticket.widget_session == self.session

    @pytest.mark.parametrize("user_hash", ["forged", ["x"], 1, "é"])
    def test_wrong_hash_for_the_same_id_is_refused(self, user_hash):
        before = self._rows()
        res = self._post(external_user_id="u1", user_hash=user_hash, name="Mallory")
        assert res.status_code == 403
        assert self._rows() == before

    def test_id_without_a_hash_doesnt_resume_as_identified(self):
        before = self._rows()
        res = self._post(external_user_id="u1", name="Mallory")
        assert res.status_code == 201
        assert res.data["session_id"] != str(self.session.id)
        assert res.data["external_user_id"] == ""
        assert self._rows() == before

    def test_logged_in_page_resumes_on_every_init(self):
        identity = {
            "external_user_id": "u1",
            "user_hash": _hash(self.org.widget_secret, "u1"),
        }
        for _ in range(2):
            res = self._post(**identity)
            assert res.status_code == 200
            assert res.data["session_id"] == str(self.session.id)
        self.ticket.refresh_from_db()
        assert "pre_login_anonymous" not in self.ticket.context_metadata

    def test_logging_back_in_after_a_logout(self):
        anon_id = self._post().data["session_id"]
        res = self.client.post(
            URL,
            {
                "session_id": anon_id,
                "external_user_id": "u1",
                "user_hash": _hash(self.org.widget_secret, "u1"),
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
        )
        assert res.status_code == 200
        assert res.data["session_id"] == str(self.session.id)
