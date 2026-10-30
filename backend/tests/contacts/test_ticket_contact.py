"""The contact on tickets: what agents see, what nobody else does."""

import hashlib
import hmac
import json
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.gdpr import anonymize_contact
from apps.contacts.models import Contact
from apps.notifications.signals import (
    notify_message_deleted,
    notify_new_message,
    notify_new_ticket,
    notify_ticket_update,
)
from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from tests.factories import (
    CompanyFactory,
    ContactFactory,
    EndUserFactory,
    OrganizationFactory,
    TagFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
TICKETS = "/api/v1/tickets/"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
CONTACT_KEYS = {"contact", "contact_detail", "sender_verified", "declared_email"}


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _url(ticket) -> str:
    return f"{TICKETS}{ticket.id}/"


def _ticket(organization, **fields) -> Ticket:
    return TicketFactory(
        organization=organization,
        **{"requester": None, "requester_email": "", **fields},
    )


def _session(organization, contact=None, **fields) -> WidgetSession:
    return WidgetSession.objects.create(
        organization=organization, contact=contact, **fields
    )


def _verified_session(organization, contact) -> WidgetSession:
    return _session(
        organization,
        contact,
        email=contact.email,
        email_verified_at=timezone.now(),
    )


def _sender_verified(client, ticket):
    """What agents read, on the detail and on the list, which have to agree."""
    detail = client.get(_url(ticket)).data["sender_verified"]
    rows = client.get(TICKETS).data["results"]
    assert [r["sender_verified"] for r in rows if r["id"] == str(ticket.id)] == [detail]
    return detail


class TestContactFields:
    def test_detail_exposes_the_contact(self, authenticated_client, organization):
        company = CompanyFactory(organization=organization, name="Acme")
        contact = ContactFactory(
            organization=organization,
            name="Alice",
            email="alice@x.io",
            declared_email="other@x.io",
            email_verified_at=timezone.now(),
            company=company,
        )
        ticket = _ticket(organization, contact=contact)

        data = authenticated_client.get(_url(ticket)).data

        assert data["contact"] == contact.id
        detail = data["contact_detail"]
        assert detail["id"] == str(contact.id)
        assert detail["display_name"] == "Alice"
        assert detail["email"] == "alice@x.io"
        assert detail["email_verified"] is True
        assert detail["declared_email"] == "other@x.io"
        assert detail["company_detail"]["id"] == str(company.id)
        assert detail["company_detail"]["name"] == "Acme"

    def test_says_whether_the_contact_is_anonymized(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        # A visitor can declare this address: only the flag means anonymized.
        lookalike = ContactFactory(
            organization=organization, email="visitor@example.invalid"
        )
        anonymized = ContactFactory(organization=organization)
        tickets = [
            _ticket(organization, contact=c) for c in (contact, lookalike, anonymized)
        ]
        anonymize_contact(anonymized)

        flags = [
            authenticated_client.get(_url(ticket)).data["contact_detail"][
                "is_anonymized"
            ]
            for ticket in tickets
        ]
        rows = authenticated_client.get(TICKETS).data["results"]

        assert flags == [False, False, True]
        assert sorted(row["contact_detail"]["is_anonymized"] for row in rows) == [
            False,
            False,
            True,
        ]

    def test_list_exposes_the_contact(self, authenticated_client, organization):
        contact = ContactFactory(organization=organization)
        _ticket(organization, contact=contact)

        row = authenticated_client.get(TICKETS).data["results"][0]

        assert row["contact"] == contact.id
        assert row["contact_detail"]["id"] == str(contact.id)
        assert "sender_verified" in row

    def test_a_ticket_without_contact(self, authenticated_client, organization):
        ticket = _ticket(organization)
        data = authenticated_client.get(_url(ticket)).data
        assert data["contact"] is None
        assert data["contact_detail"] is None


class TestSenderVerified:
    def test_true_for_a_session_that_proved_the_contacts_email(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization, email="alice@x.io")
        session = _session(
            organization,
            contact,
            email=" Alice@X.io",
            email_verified_at=timezone.now(),
        )
        ticket = _ticket(organization, contact=contact, widget_session=session)
        assert _sender_verified(authenticated_client, ticket) is True

    def test_true_for_an_identified_session(self, authenticated_client, organization):
        contact = ContactFactory(organization=organization, external_id="u1")
        session = _session(organization, contact, external_user_id="u1")
        ticket = _ticket(organization, contact=contact, widget_session=session)
        assert _sender_verified(authenticated_client, ticket) is True

    def test_an_agent_changing_the_email_voids_the_proof_of_the_old_one(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(
            organization=organization,
            email="alice@x.io",
            email_verified_at=timezone.now(),
        )
        session = _verified_session(organization, contact)
        ticket = _ticket(organization, contact=contact, widget_session=session)
        assert _sender_verified(authenticated_client, ticket) is True

        res = authenticated_client.patch(
            f"/api/v1/contacts/{contact.id}/", {"email": "bob@x.io"}, format="json"
        )

        assert res.status_code == 200
        session.refresh_from_db()
        assert session.email_verified_at is not None  # The stale part.
        assert _sender_verified(authenticated_client, ticket) is False

    def test_an_agent_changing_the_email_leaves_a_signed_id_proven(
        self, authenticated_client, organization
    ):
        """The signature is about the external id, which the email doesn't change."""
        contact = ContactFactory(
            organization=organization, email="alice@x.io", external_id="u1"
        )
        session = _session(
            organization,
            contact,
            external_user_id="u1",
            email="alice@x.io",
            email_verified_at=timezone.now(),
        )
        ticket = _ticket(organization, contact=contact, widget_session=session)

        authenticated_client.patch(
            f"/api/v1/contacts/{contact.id}/", {"email": "bob@x.io"}, format="json"
        )

        assert _sender_verified(authenticated_client, ticket) is True

    def test_a_blank_email_proves_nothing(self, authenticated_client, organization):
        contact = ContactFactory(organization=organization, email="")
        session = _session(organization, contact, email_verified_at=timezone.now())
        ticket = _ticket(organization, contact=contact, widget_session=session)
        assert _sender_verified(authenticated_client, ticket) is False

    def test_false_for_an_unverified_anonymous_session(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization, email="alice@x.io")
        session = _session(organization, contact, email="alice@x.io")
        ticket = _ticket(organization, contact=contact, widget_session=session)
        assert _sender_verified(authenticated_client, ticket) is False

    def test_false_for_a_session_of_another_contact(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        session = _verified_session(
            organization, ContactFactory(organization=organization)
        )
        ticket = _ticket(organization, contact=contact, widget_session=session)
        assert _sender_verified(authenticated_client, ticket) is False

    def test_false_without_a_contact(self, authenticated_client, organization):
        contact = ContactFactory(organization=organization)
        session = _verified_session(organization, contact)
        ticket = _ticket(organization, widget_session=session)
        assert _sender_verified(authenticated_client, ticket) is False

    def test_false_for_a_declared_address_of_a_verified_contact(
        self, api_client, authenticated_client, organization
    ):
        contact = ContactFactory(
            organization=organization,
            email="alice@x.io",
            email_verified_at=timezone.now(),
        )
        res = api_client.post(
            f"{TICKETS}widget_submit/",
            {"title": "Forged", "description": "x", "requester_email": "alice@x.io"},
            format="json",
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )
        ticket = Ticket.objects.get(pk=res.data["id"])
        assert ticket.contact_id == contact.id
        assert _sender_verified(authenticated_client, ticket) is False

    def test_false_for_an_email_with_no_session(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization, email="alice@x.io")
        ticket = _ticket(
            organization,
            contact=contact,
            source=Ticket.Source.EMAIL,
            requester_email="alice@x.io",
        )
        assert _sender_verified(authenticated_client, ticket) is False

    @pytest.mark.parametrize("identified", [True, False])
    def test_false_for_good_on_a_ticket_written_before_a_login(
        self, authenticated_client, organization, identified
    ):
        contact = ContactFactory(organization=organization, external_id="u1")
        session = (
            _session(organization, contact, external_user_id="u1")
            if identified
            else _verified_session(organization, contact)
        )
        ticket = _ticket(
            organization,
            contact=contact,
            widget_session=session,
            context_metadata={"pre_login_anonymous": True},
        )
        assert _sender_verified(authenticated_client, ticket) is False

    def test_false_after_a_real_login_moved_the_ticket(
        self, api_client, authenticated_client
    ):
        organization = OrganizationFactory(widget_secret="s3cret")
        authenticated_client.force_authenticate(
            UserFactory(organization=organization, role="agent")
        )
        anonymous = _session(organization)
        ticket = _ticket(organization, widget_session=anonymous)

        res = api_client.post(
            f"{TICKETS}widget_session/",
            {
                "session_id": str(anonymous.id),
                "external_user_id": "u1",
                "user_hash": _sign("s3cret", "u1"),
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )

        assert res.status_code == 201
        ticket.refresh_from_db()
        assert ticket.widget_session.external_user_id == "u1"
        assert ticket.contact_id == ticket.widget_session.contact_id is not None
        assert _sender_verified(authenticated_client, ticket) is False

    def test_false_once_anonymized(self, authenticated_client, organization):
        contact = ContactFactory(organization=organization, external_id="u1")
        session = _session(organization, contact, external_user_id="u1")
        ticket = _ticket(
            organization,
            contact=contact,
            widget_session=session,
            requester_email=contact.email,
        )
        anonymize_contact(contact)
        assert _sender_verified(authenticated_client, ticket) is False

    def test_a_metadata_that_isnt_an_object_is_no_mark(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization, external_id="u1")
        session = _session(organization, contact, external_user_id="u1")
        ticket = _ticket(
            organization,
            contact=contact,
            widget_session=session,
            context_metadata=["pre_login_anonymous"],
        )
        assert _sender_verified(authenticated_client, ticket) is True

    @pytest.mark.parametrize("source", [Ticket.Source.AGENT, Ticket.Source.API])
    def test_null_on_a_ticket_with_no_outside_sender(
        self, authenticated_client, organization, source
    ):
        contact = ContactFactory(organization=organization)
        ticket = _ticket(
            organization,
            source=source,
            contact=contact,
            requester_email=contact.email,
            widget_session=_verified_session(organization, contact),
        )
        assert _sender_verified(authenticated_client, ticket) is None

    def test_null_with_no_session_and_no_requester_email(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        ticket = _ticket(organization, contact=contact)
        assert _sender_verified(authenticated_client, ticket) is None

    def test_read_only(self, authenticated_client, organization):
        ticket = _ticket(organization, requester_email="a@x.io")
        res = authenticated_client.patch(
            _url(ticket), {"sender_verified": True}, format="json"
        )
        assert res.status_code == 200
        assert res.data["sender_verified"] is False


class TestWritingTheContact:
    def test_patch_links_a_contact_of_the_organization(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        ticket = _ticket(organization)

        res = authenticated_client.patch(
            _url(ticket), {"contact": str(contact.id)}, format="json"
        )

        assert res.status_code == 200
        assert res.data["contact_detail"]["id"] == str(contact.id)
        ticket.refresh_from_db()
        assert ticket.contact_id == contact.id

    def test_another_organizations_contact_reads_as_an_unknown_one(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=OrganizationFactory())
        ticket = _ticket(organization)

        other = authenticated_client.patch(
            _url(ticket), {"contact": str(contact.id)}, format="json"
        )
        unknown = authenticated_client.patch(
            _url(ticket), {"contact": UNKNOWN_ID}, format="json"
        )

        assert other.status_code == unknown.status_code == 400
        assert (
            other.data["contact"][0].replace(str(contact.id), UNKNOWN_ID)
            == unknown.data["contact"][0]
        )
        assert other.data["contact"][0].code == unknown.data["contact"][0].code
        ticket.refresh_from_db()
        assert ticket.contact_id is None

    @pytest.mark.parametrize("value", ["not-a-uuid", True, ["x"], {"a": 1}, 1])
    def test_a_value_that_cant_be_an_id_is_a_400(
        self, authenticated_client, organization, value
    ):
        ticket = _ticket(organization)
        res = authenticated_client.patch(
            _url(ticket), {"contact": value}, format="json"
        )
        assert res.status_code == 400
        assert "contact" in res.data

    def test_null_clears_it(self, authenticated_client, organization):
        contact = ContactFactory(organization=organization)
        session = _verified_session(organization, contact)
        ticket = _ticket(organization, contact=contact, widget_session=session)

        res = authenticated_client.patch(_url(ticket), {"contact": None}, format="json")

        assert res.status_code == 200
        assert res.data["contact"] is None
        assert res.data["contact_detail"] is None
        assert res.data["sender_verified"] is False
        ticket.refresh_from_db()
        assert ticket.contact_id is None

    def test_an_anonymized_contact_cant_take_tickets(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        anonymize_contact(contact)
        ticket = _ticket(organization)
        res = authenticated_client.patch(
            _url(ticket), {"contact": str(contact.id)}, format="json"
        )
        assert res.status_code == 400
        assert res.data["contact"][0].code == "does_not_exist"

    def test_a_ticket_can_be_sent_back_with_its_anonymized_contact(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        ticket = _ticket(organization, contact=contact)
        anonymize_contact(contact)
        res = authenticated_client.patch(
            _url(ticket), {"contact": str(contact.id)}, format="json"
        )
        assert res.status_code == 200

    def test_the_tickets_organization_decides_under_impersonation(self, organization):
        """Not the organization the superuser belongs to."""
        superuser = UserFactory(organization=OrganizationFactory(), is_superuser=True)
        client = APIClient()
        client.force_authenticate(superuser)
        ticket = _ticket(organization)
        header = {"HTTP_X_SHOWDESK_ORG": str(organization.id)}

        res = client.patch(
            _url(ticket),
            {"contact": str(ContactFactory(organization=superuser.organization).id)},
            format="json",
            **header,
        )
        assert res.status_code == 400

        res = client.patch(
            _url(ticket),
            {"contact": str(ContactFactory(organization=organization).id)},
            format="json",
            **header,
        )
        assert res.status_code == 200

    def test_post_takes_a_contact_of_the_active_organization(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        res = authenticated_client.post(
            TICKETS, {"title": "x", "contact": str(contact.id)}, format="json"
        )
        assert res.status_code == 201
        assert res.data["contact"] == contact.id

    def test_post_refuses_another_organizations_contact(self, authenticated_client):
        contact = ContactFactory(organization=OrganizationFactory())
        res = authenticated_client.post(
            TICKETS, {"title": "x", "contact": str(contact.id)}, format="json"
        )
        assert res.status_code == 400
        assert res.data["contact"][0].code == "does_not_exist"

    def test_patch_cant_move_a_ticket_away_from_its_contacts_organization(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization)
        ticket = _ticket(organization, contact=contact)
        res = authenticated_client.patch(
            _url(ticket),
            {"organization": str(OrganizationFactory().id)},
            format="json",
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        assert ticket.organization_id == organization.id


class TestCreateResolvesTheContact:
    def _post(self, client, **data):
        res = client.post(TICKETS, {"title": "x", **data}, format="json")
        assert res.status_code == 201, res.data
        return res, Ticket.objects.get(pk=res.data["id"])

    def test_from_the_requester_email(self, authenticated_client, organization):
        res, ticket = self._post(
            authenticated_client,
            requester_email="Jane@Customer.example",
            requester_name="Jane",
        )
        assert ticket.contact.organization == organization
        assert ticket.contact.email == "jane@customer.example"
        assert ticket.contact.name == "Jane"
        assert ticket.contact.email_verified_at is None
        assert res.data["contact"] == ticket.contact_id
        assert res.data["contact_detail"]["display_name"] == "Jane"
        assert res.data["sender_verified"] is None

    def test_from_an_end_user_requester(self, authenticated_client, organization):
        account = EndUserFactory(
            organization=organization,
            email="jane@customer.example",
            first_name="Jane",
            last_name="Doe",
        )
        _, ticket = self._post(authenticated_client, requester=str(account.id))
        assert ticket.contact.email == "jane@customer.example"
        assert ticket.contact.name == "Jane Doe"
        assert ticket.contact.email_verified_at is None

    def test_the_existing_contact_of_that_address(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(organization=organization, email="a@x.io", name="A")
        _, ticket = self._post(
            authenticated_client, requester_email="a@x.io", requester_name="Other"
        )
        assert ticket.contact == contact
        contact.refresh_from_db()
        assert contact.name == "A"

    def test_the_tickets_email_wins_over_the_requester(
        self, authenticated_client, organization
    ):
        account = EndUserFactory(organization=organization, email="a@x.io")
        _, ticket = self._post(
            authenticated_client, requester=str(account.id), requester_email="b@x.io"
        )
        assert ticket.contact.email == "b@x.io"
        assert ticket.contact.name == ""

    def test_not_from_an_agent_or_admin_requester(
        self, authenticated_client, agent, admin_user
    ):
        for user in (agent, admin_user):
            _, ticket = self._post(authenticated_client, requester=str(user.id))
            assert ticket.contact is None
        assert not Contact.objects.exists()

    def test_not_from_the_address_of_an_agent(self, authenticated_client, agent):
        _, requested = self._post(
            authenticated_client,
            requester=str(agent.id),
            requester_email=agent.email,
        )
        _, named = self._post(authenticated_client, requester_email=agent.email.upper())
        assert requested.contact is None
        assert named.contact is None
        assert not Contact.objects.exists()

    def test_an_agent_can_file_for_a_customer(self, authenticated_client, agent):
        _, ticket = self._post(
            authenticated_client, requester=str(agent.id), requester_email="c@x.io"
        )
        assert ticket.contact.email == "c@x.io"
        assert ticket.contact.name == ""

    def test_not_from_an_account_of_another_organization(self, authenticated_client):
        account = EndUserFactory(organization=OrganizationFactory())
        res = authenticated_client.post(
            TICKETS, {"title": "x", "requester": str(account.id)}, format="json"
        )
        assert res.status_code == 400
        assert "requester" in res.data
        assert not Ticket.objects.exists()
        assert not Contact.objects.exists()

    def test_nothing_to_go_by(self, authenticated_client):
        _, ticket = self._post(authenticated_client, requester_email="")
        assert ticket.contact is None

    def test_a_contact_given_is_kept(self, authenticated_client, organization):
        contact = ContactFactory(organization=organization, email="a@x.io")
        _, ticket = self._post(
            authenticated_client, contact=str(contact.id), requester_email="b@x.io"
        )
        assert ticket.contact == contact
        assert not Contact.objects.filter(email="b@x.io").exists()

    def test_an_explicit_null_is_kept(self, authenticated_client):
        _, ticket = self._post(
            authenticated_client, contact=None, requester_email="b@x.io"
        )
        assert ticket.contact is None
        assert not Contact.objects.exists()

    def test_an_anonymized_contact_isnt_linked(
        self, authenticated_client, organization
    ):
        ContactFactory(organization=organization, email="a@x.io", is_anonymized=True)
        _, ticket = self._post(authenticated_client, requester_email="a@x.io")
        assert ticket.contact is None

    def test_a_database_error_doesnt_lose_the_ticket(self, authenticated_client):
        with mock.patch(
            "apps.tickets.views.resolve_contact_for_ticket",
            side_effect=DatabaseError,
        ):
            _, ticket = self._post(authenticated_client, requester_email="a@x.io")
        assert ticket.contact is None


class TestSenderOfAnAccount:
    def test_a_requester_account_is_an_unverified_sender(
        self, authenticated_client, organization
    ):
        ticket = _ticket(
            organization,
            source=Ticket.Source.WIDGET,
            requester=EndUserFactory(organization=organization),
            contact=ContactFactory(organization=organization),
        )
        assert _sender_verified(authenticated_client, ticket) is False

    def test_an_api_ticket_has_no_outside_sender(
        self, authenticated_client, organization
    ):
        ticket = _ticket(
            organization,
            source=Ticket.Source.API,
            requester=EndUserFactory(organization=organization),
            contact=ContactFactory(organization=organization),
        )
        assert _sender_verified(authenticated_client, ticket) is None


class TestCreateSource:
    def test_defaults_to_agent(self, authenticated_client):
        res = authenticated_client.post(TICKETS, {"title": "x"}, format="json")
        assert res.status_code == 201
        assert res.data["source"] == "agent"
        assert Ticket.objects.get(pk=res.data["id"]).source == Ticket.Source.AGENT
        assert res.data["sender_verified"] is None

    def test_keeps_a_named_source(self, authenticated_client):
        res = authenticated_client.post(
            TICKETS, {"title": "x", "source": "api"}, format="json"
        )
        assert res.status_code == 201
        assert res.data["source"] == "api"

    def test_the_frontends_payload_is_accepted(self, authenticated_client, agent):
        """It names no organization: the active one is the only possible one."""
        res = authenticated_client.post(
            TICKETS,
            {
                "title": "x",
                "description": "y",
                "priority": "high",
                "requester_name": "A",
                "requester_email": "a@x.io",
                "source": "agent",
            },
            format="json",
        )
        assert res.status_code == 201
        assert res.data["organization"] == agent.organization_id

    def test_an_organization_in_the_body_is_ignored(
        self, authenticated_client, organization
    ):
        res = authenticated_client.post(
            TICKETS,
            {"title": "x", "organization": str(OrganizationFactory().id)},
            format="json",
        )
        assert res.status_code == 201
        assert res.data["organization"] == organization.id

    def test_without_an_active_organization(self):
        client = APIClient()
        client.force_authenticate(UserFactory(organization=None, is_superuser=True))
        res = client.post(TICKETS, {"title": "x"}, format="json")
        assert res.status_code == 400


class TestEndUsers:
    @pytest.fixture
    def end_user(self, organization):
        return EndUserFactory(organization=organization)

    @pytest.fixture
    def client(self, end_user):
        client = APIClient()
        client.force_authenticate(end_user)
        return client

    @pytest.fixture
    def ticket(self, organization, end_user):
        contact = ContactFactory(organization=organization)
        return TicketFactory(
            organization=organization, requester=end_user, contact=contact
        )

    def test_cant_list(self, client, ticket):
        res = client.get(TICKETS)
        assert res.status_code == 403
        assert ticket.contact.email not in res.content.decode()

    def test_cant_retrieve_even_as_requester(self, client, ticket):
        res = client.get(_url(ticket))
        assert res.status_code == 403
        assert ticket.contact.email not in res.content.decode()

    def test_cant_read_the_stats(self, client, ticket):
        assert client.get(f"{TICKETS}stats/").status_code == 403

    def test_cant_create(self, client):
        res = client.post(TICKETS, {"title": "x"}, format="json")
        assert res.status_code == 403

    def test_cant_write(self, client, ticket):
        res = client.patch(_url(ticket), {"title": "x"}, format="json")
        assert res.status_code == 403
        assert client.delete(_url(ticket)).status_code == 403

    @pytest.mark.parametrize("action", ["resolve", "close", "reopen", "assign"])
    def test_cant_act(self, client, ticket, action):
        assert client.post(f"{_url(ticket)}{action}/").status_code == 403

    def test_cant_bulk_update(self, client, ticket):
        """This action has its own ``permission_classes``."""
        res = client.post(
            f"{TICKETS}bulk_update/",
            {"ids": [str(ticket.id)], "status": "closed"},
            format="json",
        )
        assert res.status_code == 403
        ticket.refresh_from_db()
        assert ticket.status != Ticket.Status.CLOSED

    def test_a_superuser_is_let_in_whatever_the_role(self, organization, ticket):
        """The role defaults to end user, ``createsuperuser`` doesn't change it."""
        client = APIClient()
        client.force_authenticate(
            UserFactory(organization=organization, role="end_user", is_superuser=True)
        )
        assert client.get(_url(ticket)).status_code == 200

    def test_the_widget_endpoints_stay_open(self, client, organization):
        """Its token is what identifies a widget, whoever is signed in on that page."""
        res = client.post(
            f"{TICKETS}widget_session/",
            {},
            format="json",
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )
        assert res.status_code == 201


class TestListQueries:
    def _row(self, organization, n: int) -> Ticket:
        contact = ContactFactory(
            organization=organization,
            company=CompanyFactory(organization=organization),
        )
        ticket = TicketFactory(
            organization=organization,
            contact=contact,
            assigned_agent=UserFactory(organization=organization),
            widget_session=_verified_session(organization, contact),
        )
        ticket.tags.add(TagFactory(organization=organization))
        for _ in range(n):
            TicketMessageFactory(ticket=ticket, author=None)
        return ticket

    def _count(self, client, url: str) -> tuple[int, dict]:
        with CaptureQueriesContext(connection) as queries:
            res = client.get(url)
        assert res.status_code == 200
        return len(queries), res.data

    def test_the_list_doesnt_grow_with_its_rows(
        self, authenticated_client, organization
    ):
        self._row(organization, 1)
        before, _ = self._count(authenticated_client, TICKETS)

        for n in range(5):
            self._row(organization, n)
        after, data = self._count(authenticated_client, TICKETS)

        assert data["count"] == 6
        assert after == before

    def test_a_contacts_timeline_doesnt_grow_with_its_rows(
        self, authenticated_client, organization
    ):
        contact = ContactFactory(
            organization=organization,
            company=CompanyFactory(organization=organization),
        )
        url = f"/api/v1/contacts/{contact.id}/tickets/"

        def add_row():
            ticket = self._row(organization, 1)
            ticket.contact = contact
            ticket.widget_session = _verified_session(organization, contact)
            ticket.save()

        add_row()
        before, _ = self._count(authenticated_client, url)
        for _ in range(5):
            add_row()
        after, data = self._count(authenticated_client, url)

        assert len(data) == 6
        assert after == before

    def test_message_count(self, authenticated_client, organization):
        ticket = self._row(organization, 3)
        empty = _ticket(organization)
        rows = authenticated_client.get(TICKETS).data["results"]
        counts = {row["id"]: row["message_count"] for row in rows}
        assert counts == {str(ticket.id): 3, str(empty.id): 0}

    def test_filtering_on_two_tags_doesnt_inflate_it(
        self, authenticated_client, organization
    ):
        """That filter joins the tags, one row per tag matched."""
        ticket = self._row(organization, 3)
        first, second = (TagFactory(organization=organization) for _ in range(2))
        ticket.tags.add(first, second)

        res = authenticated_client.get(f"{TICKETS}?tags={first.id}&tags={second.id}")

        assert res.data["count"] == 1
        assert [row["message_count"] for row in res.data["results"]] == [3]

    def test_the_stats_are_unaffected(self, authenticated_client, organization):
        """A GROUP BY of their own, which an annotated queryset would break."""
        self._row(organization, 3)
        res = authenticated_client.get(f"{TICKETS}stats/")
        assert res.status_code == 200
        assert res.data["total"] == 1
        assert res.data["by_status"] == {"open": 1}


def _keys(value) -> set:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


class TestWidgetResponses:
    """A widget's token is public, and so is the address it can name."""

    SECRET_EMAIL = "hidden.declared@x.io"
    SECRET_COMPANY = "Hidden Company"

    @pytest.fixture(autouse=True)
    def media(self, settings, tmp_path):
        settings.STORAGES = {
            **settings.STORAGES,
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": str(tmp_path)},
            },
        }

    @pytest.fixture
    def contact(self, organization):
        return ContactFactory(
            organization=organization,
            email="alice@x.io",
            email_verified_at=timezone.now(),
            declared_email=self.SECRET_EMAIL,
            company=CompanyFactory(organization=organization, name=self.SECRET_COMPANY),
        )

    @pytest.fixture
    def session(self, organization, contact):
        return _verified_session(organization, contact)

    @pytest.fixture
    def ticket(self, organization, contact, session):
        return _ticket(
            organization,
            contact=contact,
            widget_session=session,
            requester_email=contact.email,
        )

    @pytest.fixture
    def headers(self, organization, session):
        return {
            "HTTP_X_WIDGET_TOKEN": str(organization.api_token),
            "HTTP_X_WIDGET_SESSION": str(session.id),
        }

    def _assert_clean(self, res, status: int = 200) -> None:
        assert res.status_code == status, res.data
        assert not _keys(res.data) & CONTACT_KEYS
        content = res.content.decode()
        assert self.SECRET_EMAIL not in content
        assert self.SECRET_COMPANY not in content

    def test_submit_naming_a_contacts_address(self, api_client, organization, contact):
        res = api_client.post(
            f"{TICKETS}widget_submit/",
            {"title": "x", "description": "y", "requester_email": contact.email},
            format="json",
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )
        self._assert_clean(res, 201)
        assert Ticket.objects.get(pk=res.data["id"]).contact_id == contact.id
        assert res.data["reference"].startswith("SD-")

    def test_submit_cant_write_the_contact(self, api_client, organization, contact):
        res = api_client.post(
            f"{TICKETS}widget_submit/",
            {"title": "x", "description": "y", "contact": str(contact.id)},
            format="json",
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )
        self._assert_clean(res, 201)
        assert Ticket.objects.get(pk=res.data["id"]).contact_id is None

    def test_session_post(self, api_client, headers, session):
        res = api_client.post(
            f"{TICKETS}widget_session/",
            {"session_id": str(session.id)},
            format="json",
            **headers,
        )
        self._assert_clean(res, 201)  # Unsigned, so a logout from its proven email.

    def test_session_post_resuming(self, api_client, headers, organization):
        session = WidgetSession.objects.create(organization=organization)
        res = api_client.post(
            f"{TICKETS}widget_session/",
            {"session_id": str(session.id)},
            format="json",
            **headers,
        )
        self._assert_clean(res)

    def test_session_patch(self, api_client, headers):
        res = api_client.patch(
            f"{TICKETS}widget_session/", {"name": "A"}, format="json", **headers
        )
        self._assert_clean(res)

    def test_history(self, api_client, headers, ticket):
        res = api_client.get(f"{TICKETS}widget_history/", **headers)
        self._assert_clean(res)
        assert [row["id"] for row in res.data] == [str(ticket.id)]

    def test_conversation(self, api_client, headers, ticket):
        TicketMessageFactory(ticket=ticket, author=None)
        res = api_client.get(
            f"{TICKETS}widget_conversation/?ticket_id={ticket.id}", **headers
        )
        self._assert_clean(res)
        assert len(res.data["messages"]) == 1

    def test_message(self, api_client, headers, ticket):
        res = api_client.post(
            f"{TICKETS}widget_message/",
            {"ticket_id": str(ticket.id), "body": "hello"},
            format="json",
            **headers,
        )
        self._assert_clean(res, 201)

    def test_message_attachment(self, api_client, headers, ticket):
        res = api_client.post(
            f"{TICKETS}widget_message_attachment/",
            {
                "ticket_id": str(ticket.id),
                "file": SimpleUploadedFile("a.png", b"x", content_type="image/png"),
            },
            format="multipart",
            **headers,
        )
        self._assert_clean(res, 201)

    def test_upload_attachment(self, api_client, headers, ticket):
        res = api_client.post(
            f"{TICKETS}widget_upload_attachment/",
            {
                "ticket": str(ticket.id),
                "file": SimpleUploadedFile("a.png", b"x", content_type="image/png"),
            },
            format="multipart",
            **headers,
        )
        self._assert_clean(res, 201)

    def test_tickets_of_a_user(self, api_client):
        organization = OrganizationFactory(widget_secret="s3cret")
        contact = ContactFactory(
            organization=organization,
            external_id="u1",
            declared_email=self.SECRET_EMAIL,
        )
        _ticket(organization, contact=contact, external_user_id="u1")
        res = api_client.get(
            f"{TICKETS}widget_tickets/",
            {
                "external_user_id": "u1",
                "user_hash": _sign("s3cret", "u1"),
            },
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )
        self._assert_clean(res)
        assert len(res.data) == 1

    def test_video_upload(self, api_client, headers, ticket):
        with mock.patch("apps.videos.views.process_video"):
            res = api_client.post(
                "/api/v1/videos/widget_upload/",
                {
                    "ticket": str(ticket.id),
                    "original_file": SimpleUploadedFile(
                        "a.webm", b"x", content_type="video/webm"
                    ),
                    "mime_type": "video/webm",
                },
                format="multipart",
                **headers,
            )
        self._assert_clean(res, 201)


class TestWebSocketPayloads:
    """None uses ``TicketSerializer``: each lists its own fields."""

    SECRET = "hidden.declared@x.io"

    def test_no_group_gets_contact_data(self, organization):
        contact = ContactFactory(
            organization=organization,
            name="Hidden Name",
            email="hidden.email@x.io",
            declared_email=self.SECRET,
            company=CompanyFactory(organization=organization, name="Hidden Company"),
        )
        session = _session(
            organization, contact, external_user_id="u1", name="Own Name"
        )
        ticket = _ticket(organization, contact=contact, widget_session=session)
        message = TicketMessageFactory(
            ticket=ticket,
            author=None,
            widget_session=session,
            sender_type=TicketMessage.SenderType.USER,
        )
        sent = []

        async def group_send(group, event):
            sent.append((group, event))

        with mock.patch("apps.notifications.signals.get_channel_layer") as layer:
            layer.return_value.group_send = group_send
            notify_new_ticket(ticket)
            notify_ticket_update(ticket)
            notify_new_message(message)
            notify_message_deleted(ticket, str(message.id))

        groups = {group for group, _ in sent}
        assert groups == {
            f"org_{organization.id}",
            f"widget_session_{session.id}",
        }
        for _, event in sent:
            assert not _keys(event) & CONTACT_KEYS
            payload = json.dumps(event)
            for value in (contact.name, contact.email, self.SECRET, "Hidden Company"):
                assert value not in payload
