"""Tests for the widget_session POST endpoint (create/resume)."""

import hashlib
import hmac
import json
import logging
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from tests.factories import (
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
    UserFactory,
)

URL = "/api/v1/tickets/widget_session/"


def _hash(secret: str, external_user_id: str) -> str:
    return hmac.new(
        secret.encode(),
        external_user_id.encode(),
        hashlib.sha256,
    ).hexdigest()


def _digest(session_id) -> str:
    return hashlib.sha256(str(session_id).encode()).hexdigest()


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
        assert ticket.context_metadata == {
            "locale": "fr",
            "pre_login_anonymous": True,
            "pre_login_session_hash": _digest(self.anon.id),
        }

    @pytest.mark.parametrize("metadata", [[], "text", 1])
    def test_marking_copes_with_any_stored_metadata(self, metadata):
        ticket = self._ticket()
        Ticket.objects.filter(pk=ticket.pk).update(context_metadata=metadata)
        self._login()
        ticket.refresh_from_db()
        assert ticket.context_metadata == {
            "pre_login_anonymous": True,
            "pre_login_session_hash": _digest(self.anon.id),
        }

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

    def test_the_move_is_logged_without_personal_data(self, caplog):
        ticket = self._ticket(requester_email="ann@x.io", requester_name="Ann Doe")
        TicketMessage.objects.create(ticket=ticket, widget_session=self.anon, body="Hi")
        with caplog.at_level(logging.INFO, logger="apps.tickets.views"):
            session_id = self._login(email="ann@x.io", name="Ann Doe").data[
                "session_id"
            ]
        moves = [r.getMessage() for r in caplog.records if "at login" in r.getMessage()]
        assert len(moves) == 1
        assert "1 ticket(s)" in moves[0]
        assert "1 message(s)" in moves[0]
        assert str(self.anon.id) not in caplog.text
        assert session_id not in caplog.text
        assert _digest(self.anon.id) in moves[0]
        assert _digest(session_id) in moves[0]
        assert "ann@x.io" not in caplog.text
        assert "Ann Doe" not in caplog.text
        assert "u1" not in moves[0]

    def test_agents_cant_read_the_origin_session_id(self):
        """A session id is a bearer token: the ticket API must not hand it out."""
        ticket = self._ticket()
        self._login()
        agent = APIClient()
        agent.force_authenticate(UserFactory(organization=self.org, role="agent"))
        res = agent.get(f"/api/v1/tickets/{ticket.id}/")
        assert res.status_code == 200
        assert str(self.anon.id) not in json.dumps(res.data, default=str)
        assert res.data["context_metadata"]["pre_login_session_hash"] == _digest(
            self.anon.id
        )

    def test_a_login_moving_nothing_logs_nothing(self, caplog):
        with caplog.at_level(logging.INFO, logger="apps.tickets.views"):
            self._login()
        assert "at login" not in caplog.text

    def _post_during_the_login(self, path, ticket, format, **body):
        """Post with the anonymous session, the login landing right after its lookup."""
        state = {"done": False}

        def login_once(execute, sql, params, many, context):
            if not state["done"] and "FOR NO KEY UPDATE" in sql:
                state["done"] = True
                self._login()
            return execute(sql, params, many, context)

        with connection.execute_wrapper(login_once):
            res = self.client.post(
                f"/api/v1/tickets/{path}/",
                {"ticket_id": str(ticket.id), **body},
                format=format,
                HTTP_X_WIDGET_TOKEN=self.org.api_token,
                HTTP_X_WIDGET_SESSION=str(self.anon.id),
            )
        assert state["done"]
        return res

    def test_a_message_in_flight_follows_its_ticket(self):
        ticket = self._ticket()
        res = self._post_during_the_login(
            "widget_message", ticket, "json", body="Sent while logging in"
        )
        assert res.status_code == 201
        ticket.refresh_from_db()
        message = TicketMessage.objects.get(id=res.data["message_id"])
        assert ticket.widget_session.external_user_id == "u1"
        assert message.widget_session == ticket.widget_session

    def test_an_attachment_in_flight_follows_its_ticket(self, settings):
        settings.STORAGES = {
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        }
        ticket = self._ticket()
        res = self._post_during_the_login(
            "widget_message_attachment",
            ticket,
            "multipart",
            file=SimpleUploadedFile("a.png", b"x", content_type="image/png"),
        )
        assert res.status_code == 201
        ticket.refresh_from_db()
        message = TicketMessage.objects.get(id=res.data["message_id"])
        assert ticket.widget_session.external_user_id == "u1"
        assert message.widget_session == ticket.widget_session

    def test_a_message_keeps_the_session_of_a_ticket_that_didnt_move(self):
        ticket = self._ticket()
        res = self.client.post(
            "/api/v1/tickets/widget_message/",
            {"ticket_id": str(ticket.id), "body": "Hi"},
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
            HTTP_X_WIDGET_SESSION=str(self.anon.id),
        )
        assert res.status_code == 201
        message = TicketMessage.objects.get(id=res.data["message_id"])
        assert message.widget_session == self.anon

    def _patch(self, session_id, **body):
        return self.client.patch(
            URL,
            data=body,
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
            HTTP_X_WIDGET_SESSION=session_id,
        )

    def test_patch_keeps_the_original_requester_of_a_moved_ticket(self):
        moved = self._ticket(requester_name="", requester_email="anon@x.io")
        session_id = self._login().data["session_id"]
        own = self._ticket(
            session=WidgetSession.objects.get(id=session_id),
            requester_name="",
            requester_email="",
        )
        assert self._patch(session_id, name="Ann", email="ann@x.io").status_code == 200
        moved.refresh_from_db()
        own.refresh_from_db()
        assert (moved.requester_name, moved.requester_email) == ("", "anon@x.io")
        assert (own.requester_name, own.requester_email) == ("Ann", "ann@x.io")

    def test_patch_leaves_a_ticket_of_another_organization_alone(self):
        foreign = TicketFactory(
            organization=OrganizationFactory(),
            widget_session=self.anon,
            requester=None,
            requester_name="",
            requester_email="",
        )
        res = self._patch(str(self.anon.id), name="Ann", email="ann@x.io")
        assert res.status_code == 200
        foreign.refresh_from_db()
        assert (foreign.requester_name, foreign.requester_email) == ("", "")

    def test_patch_copes_with_metadata_that_isnt_an_object(self):
        ticket = self._ticket(requester_name="", requester_email="")
        Ticket.objects.filter(pk=ticket.pk).update(context_metadata=[])
        assert self._patch(str(self.anon.id), name="Ann").status_code == 200
        ticket.refresh_from_db()
        assert ticket.requester_name == "Ann"

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
        assert moved.context_metadata == {
            "pre_login_anonymous": True,
            "pre_login_session_hash": _digest(self.anon.id),
        }

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


@pytest.mark.django_db
class TestWidgetMessageContext:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = APIClient()
        self.org = OrganizationFactory()
        self.session = WidgetSession.objects.create(organization=self.org)

    def _ticket(self, context) -> Ticket:
        res = self.client.post(
            "/api/v1/tickets/widget_message/",
            # Dumped here: the test client's renderer can't encode a lone surrogate.
            json.dumps({"body": "Help", "context": context}),
            content_type="application/json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
            HTTP_X_WIDGET_SESSION=str(self.session.id),
        )
        assert res.status_code == 201, res.content
        return Ticket.objects.get(id=res.data["ticket_id"])

    def test_keeps_what_it_can_store(self):
        ticket = self._ticket(
            {
                "url": "https://app.example/page",
                "user_agent": "Mozilla/5.0",
                "os": "macOS",
                "browser": "Firefox",
                "screen_resolution": "1920x1080",
                "language": "fr",
                "viewport": {"width": 800},
            }
        )
        assert ticket.context_url == "https://app.example/page"
        assert ticket.context_user_agent == "Mozilla/5.0"
        assert ticket.context_os == "macOS"
        assert ticket.context_browser == "Firefox"
        assert ticket.context_screen_resolution == "1920x1080"
        assert ticket.context_metadata == {
            "language": "fr",
            "viewport": {"width": 800},
        }

    @pytest.mark.parametrize(
        "value",
        [None, 1, 1.5, True, [], ["macOS"], {"name": "macOS"}, "ma\x00cOS", "\ud800"],
    )
    @pytest.mark.parametrize(
        ("key", "field"),
        [
            ("url", "context_url"),
            ("user_agent", "context_user_agent"),
            ("os", "context_os"),
            ("browser", "context_browser"),
            ("screen_resolution", "context_screen_resolution"),
        ],
    )
    def test_ignores_what_it_cant_store(self, key, field, value):
        ticket = self._ticket({key: value})
        assert getattr(ticket, field) == ""
        assert key not in ticket.context_metadata

    @pytest.mark.parametrize(
        ("key", "field", "limit"),
        [
            ("url", "context_url", 2048),
            ("os", "context_os", 100),
            ("browser", "context_browser", 100),
            ("screen_resolution", "context_screen_resolution", 20),
        ],
    )
    def test_truncates_what_is_too_long(self, key, field, limit):
        ticket = self._ticket({key: "x" * (limit + 1)})
        assert getattr(ticket, field) == "x" * limit

    @pytest.mark.parametrize(
        "value",
        [
            "a\x00b",
            "\ud800",
            ["a\x00b"],
            {"nested": {"deep": "a\x00b"}},
            {"a\x00b": 1},
        ],
    )
    def test_metadata_leaves_out_what_it_cant_store(self, value):
        ticket = self._ticket({"bad": value, "good": "kept"})
        assert ticket.context_metadata == {"good": "kept"}

    def test_metadata_leaves_out_a_key_it_cant_store(self):
        ticket = self._ticket({"a\x00b": 1, "good": "kept"})
        assert ticket.context_metadata == {"good": "kept"}

    @pytest.mark.parametrize("context", [[], ["os"], "macOS", 1, True])
    def test_a_context_that_isnt_an_object_counts_as_none(self, context):
        ticket = self._ticket(context)
        assert ticket.context_os == ""
        assert ticket.context_metadata == {}
