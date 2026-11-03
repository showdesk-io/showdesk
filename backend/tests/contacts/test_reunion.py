"""Reuniting an email-only contact's history on proof (Contacts design §3 rule 1, §8).

An identified contact with no email that proves an address held by an email-only
contact takes that contact's tickets, sessions and notes, and then its email.
"""

import pytest
from rest_framework.test import APIClient

from apps.contacts.models import Contact, ContactNote
from apps.contacts.services import resolve_contact_for_widget_session
from apps.tickets.models import Ticket, WidgetSession
from tests.contacts.test_contacts_api_concurrency import _race
from tests.factories import (
    ContactFactory,
    ContactNoteFactory,
    OrganizationFactory,
    TicketFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return OrganizationFactory()


def _session(org, **kwargs):
    return WidgetSession.objects.create(organization=org, **kwargs)


def _email_only(org, **kwargs):
    return ContactFactory(organization=org, email="a@x.io", external_id="", **kwargs)


def _identified(org, **kwargs):
    return ContactFactory(organization=org, email="", external_id="u1", **kwargs)


def _prove(org, email="a@x.io"):
    session = _session(org, external_user_id="u1", email=email)
    return session, resolve_contact_for_widget_session(session, email_verified=True)


def _email_ticket(org, contact):
    return TicketFactory(
        organization=org,
        contact=contact,
        source=Ticket.Source.EMAIL,
        requester=None,
        requester_email=contact.email,
    )


class TestReunion:
    def test_tickets_sessions_and_notes_move_with_the_email(self, org):
        other = _email_only(org, name="Alice", phone="+33", attributes={"plan": "pro"})
        contact = _identified(org, name="", job_title="CTO", attributes={"seat": 3})
        ticket = _email_ticket(org, other)
        anonymous = _session(org, email="a@x.io", contact=other)
        note = ContactNoteFactory(contact=other)

        session, result = _prove(org)

        assert result == contact
        assert not Contact.objects.filter(pk=other.pk).exists()
        contact.refresh_from_db()
        session.refresh_from_db()
        assert (contact.email, contact.declared_email) == ("a@x.io", "")
        assert contact.email_verified_at is not None
        assert session.email_verified_at is not None
        assert (contact.name, contact.phone, contact.job_title) == (
            "Alice",
            "+33",
            "CTO",
        )
        assert contact.attributes == {"plan": "pro", "seat": 3}
        assert Ticket.objects.get(pk=ticket.pk).contact_id == contact.pk
        assert WidgetSession.objects.get(pk=anonymous.pk).contact_id == contact.pk
        assert ContactNote.objects.get(pk=note.pk).contact_id == contact.pk

    def test_moved_tickets_stay_unverified(self, org):
        other = _email_only(org)
        _identified(org)
        anonymous = _session(org, email="a@x.io", contact=other)
        by_widget = TicketFactory(
            organization=org, contact=other, widget_session=anonymous, requester=None
        )
        by_email = _email_ticket(org, other)

        _prove(org)

        for ticket in (by_widget, by_email):
            ticket = Ticket.objects.get(pk=ticket.pk)
            assert ticket.contact.email_verified_at is not None
            assert ticket.sender_verified is False

    def test_an_unsubscription_survives(self, org):
        _email_only(org, is_unsubscribed=True)
        contact = _identified(org)

        _prove(org)

        contact.refresh_from_db()
        assert contact.is_unsubscribed is True

    def test_an_unproven_email_moves_nothing(self, org):
        other = _email_only(org)
        contact = _identified(org)
        ticket = _email_ticket(org, other)
        session = _session(org, external_user_id="u1", email="a@x.io")

        resolve_contact_for_widget_session(session)

        contact.refresh_from_db()
        assert Contact.objects.filter(pk=other.pk).exists()
        assert (contact.email, contact.declared_email) == ("", "a@x.io")
        assert Ticket.objects.get(pk=ticket.pk).contact_id == other.pk

    def test_an_identified_holder_keeps_everything(self, org):
        holder = ContactFactory(organization=org, email="a@x.io", external_id="u2")
        contact = _identified(org)
        ticket = _email_ticket(org, holder)

        session, _ = _prove(org)

        contact.refresh_from_db()
        session.refresh_from_db()
        assert (contact.email, contact.email_verified_at) == ("", None)
        assert session.email_verified_at is None
        assert Ticket.objects.get(pk=ticket.pk).contact_id == holder.pk

    def test_an_anonymized_holder_keeps_everything(self, org):
        holder = _email_only(org, is_anonymized=True)
        contact = _identified(org)
        ticket = _email_ticket(org, holder)

        _prove(org)

        contact.refresh_from_db()
        assert contact.email == ""
        assert Ticket.objects.get(pk=ticket.pk).contact_id == holder.pk

    def test_a_contact_holding_another_email_moves_nothing(self, org):
        other = _email_only(org)
        contact = ContactFactory(organization=org, email="b@x.io", external_id="u1")
        ticket = _email_ticket(org, other)

        _prove(org)

        contact.refresh_from_db()
        assert contact.email == "b@x.io"
        assert Contact.objects.filter(pk=other.pk).exists()
        assert Ticket.objects.get(pk=ticket.pk).contact_id == other.pk

    def test_a_moved_session_opens_no_history_without_its_own_proof(self, org):
        other = _email_only(org)
        _identified(org)
        anonymous = _session(org, email="a@x.io", contact=other)
        own = TicketFactory(organization=org, contact=other, widget_session=anonymous)
        _email_ticket(org, other)

        _prove(org)

        client = APIClient()
        res = client.get(
            "/api/v1/tickets/widget_history/",
            HTTP_X_WIDGET_TOKEN=org.api_token,
            HTTP_X_WIDGET_SESSION=str(anonymous.pk),
        )
        assert res.status_code == 200
        assert [row["id"] for row in res.data] == [str(own.pk)]


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_proofs_leave_one_contact(org):
    """The second proof waits for the first, and finds the email-only row gone."""
    other = _email_only(org)
    first = _identified(org)
    second = ContactFactory(organization=org, email="", external_id="u2")
    ticket = _email_ticket(org, other)
    waiting = _session(org, external_user_id="u2", email="a@x.io")

    def prove_first():
        session = _session(org, external_user_id="u1", email="a@x.io")
        resolve_contact_for_widget_session(session, email_verified=True)

    result = _race(
        prove_first,
        lambda: resolve_contact_for_widget_session(waiting, email_verified=True),
    )

    assert result == second
    assert list(
        Contact.objects.filter(organization=org, email="a@x.io").values_list(
            "pk", flat=True
        )
    ) == [first.pk]
    assert Ticket.objects.get(pk=ticket.pk).contact_id == first.pk
    waiting.refresh_from_db()
    assert waiting.email_verified_at is None
    second.refresh_from_db()
    assert (second.email, second.email_verified_at) == ("", None)
