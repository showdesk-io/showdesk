"""Back-fill of contacts from existing widget sessions and tickets."""

from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.db import OperationalError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.backfill import _analyze, backfill, clean_email
from apps.contacts.gdpr import anonymize_contact
from apps.contacts.models import Contact
from apps.contacts.services import resolve_contact_for_widget_session
from apps.organizations.models import User
from apps.tickets.models import Ticket, WidgetSession
from tests.factories import (
    AdminFactory,
    ContactFactory,
    EndUserFactory,
    OrganizationFactory,
    TicketFactory,
    UserFactory,
)

BEFORE_BACKFILL = ("contacts", "0003_contact_declared_email")
BACKFILL = ("contacts", "0004_backfill_contacts")


def _run():
    backfill(django_apps, None)


def _session(org, **kwargs) -> WidgetSession:
    return WidgetSession.objects.create(organization=org, **kwargs)


def _ticket(org, **kwargs) -> Ticket:
    kwargs.setdefault("requester_email", "")
    kwargs.setdefault("requester", None)
    return TicketFactory(organization=org, **kwargs)


def _reload(*rows):
    for row in rows:
        row.refresh_from_db()


def _dated(row, **dates):
    """Set timestamps that ``auto_now`` fields would otherwise overwrite."""
    type(row).objects.filter(pk=row.pk).update(**dates)
    row.refresh_from_db()
    return row


def _before_statement(prefix: str, action):
    """Run ``action`` once, right before the first statement starting with ``prefix``.

    It stands for a concurrent request committing between our read and our write.
    """
    state = {"done": False}

    def wrapper(execute, sql, params, many, context):
        if not state["done"] and sql.startswith(prefix):
            state["done"] = True
            action()
        return execute(sql, params, many, context)

    return wrapper


@pytest.mark.django_db
class TestIdentity:
    def test_groups_by_external_id_then_email(self):
        org = OrganizationFactory()
        s1 = _session(org, external_user_id="u1", email="A@x.io")
        t1 = _ticket(org, external_user_id="u1", requester_email="a@x.io")
        t2 = _ticket(org, requester_email="b@x.io")
        t3 = _ticket(org, requester_email="B@x.io")

        _run()

        assert Contact.objects.filter(organization=org).count() == 2
        _reload(s1, t1, t2, t3)
        assert s1.contact == t1.contact
        contact = s1.contact
        assert (contact.external_id, contact.email, contact.declared_email) == (
            "u1",
            "",
            "a@x.io",
        )
        assert contact.email_verified_at is None
        assert t2.contact == t3.contact
        assert t2.contact.email == "b@x.io"
        assert t2.contact.declared_email == ""
        assert t2.contact.email_verified_at is None

    def test_ticket_of_an_external_id_declares_its_email(self):
        org = OrganizationFactory()
        _session(org, external_user_id="u1")
        ticket = _ticket(org, external_user_id="u1", requester_email="A@x.io")
        _run()
        ticket.refresh_from_db()
        assert (ticket.contact.email, ticket.contact.declared_email) == ("", "a@x.io")

    def test_two_external_ids_can_declare_the_same_email(self):
        org = OrganizationFactory()
        _session(org, external_user_id="u1", email="d@x.io")
        _session(org, external_user_id="u2", email="d@x.io")
        _run()
        contacts = Contact.objects.filter(organization=org)
        assert sorted(contacts.values_list("email", "declared_email")) == [
            ("", "d@x.io"),
            ("", "d@x.io"),
        ]

    def test_email_of_an_anonymous_session_stays_on_an_email_only_contact(self):
        org = OrganizationFactory()
        identified = _session(org, external_user_id="u1", email="e@x.io")
        anonymous = _session(org, email="e@x.io")
        _run()
        _reload(identified, anonymous)
        assert anonymous.contact != identified.contact
        assert (anonymous.contact.email, anonymous.contact.external_id) == (
            "e@x.io",
            "",
        )
        assert anonymous.contact.email_verified_at is None

    def test_session_and_ticket_sharing_an_email_differing_by_case_are_one_contact(
        self,
    ):
        org = OrganizationFactory()
        session = _session(org, email="  A@x.io ")
        ticket = _ticket(org, requester_email="a@X.IO")
        _run()
        _reload(session, ticket)
        assert session.contact == ticket.contact
        assert session.contact.email == "a@x.io"
        assert Contact.objects.filter(organization=org).count() == 1

    def test_nothing_is_marked_verified(self):
        org = OrganizationFactory()
        session = _session(
            org, external_user_id="u1", email="a@x.io", email_verified_at=timezone.now()
        )
        _run()
        session.refresh_from_db()
        assert session.contact.email == ""
        assert session.contact.declared_email == "a@x.io"
        assert session.contact.email_verified_at is None

    def test_organizations_are_kept_apart(self):
        org, other = OrganizationFactory(), OrganizationFactory()
        rows = [
            _session(org, external_user_id="u1"),
            _session(other, external_user_id="u1"),
            _session(org, email="a@x.io"),
            _session(other, email="a@x.io"),
            _session(org, external_user_id="u2"),
            _session(other, external_user_id="u2"),
            _ticket(org, external_user_id="u2"),
            _ticket(other, external_user_id="u2"),
            _ticket(org, requester_email="b@x.io"),
            _ticket(other, requester_email="b@x.io"),
        ]
        _run()
        _reload(*rows)
        assert all(row.contact.organization_id == row.organization_id for row in rows)
        assert Contact.objects.filter(organization=org).count() == 4
        assert Contact.objects.filter(organization=other).count() == 4


@pytest.mark.django_db
class TestUnusableValues:
    def test_whitespace_email_matches_no_blank_contact(self):
        org = OrganizationFactory()
        blank = ContactFactory(organization=org, email="", external_id="u9")
        session = _session(org, email="   ")
        ticket = _ticket(org, requester_email="   ")
        _run()
        _reload(session, ticket)
        assert session.contact is None
        assert ticket.contact is None
        assert list(Contact.objects.filter(organization=org)) == [blank]

    @pytest.mark.parametrize("email", ["not an email", "a@", "@x.io", "a b@x.io"])
    def test_invalid_email_creates_nothing(self, email):
        org = OrganizationFactory()
        session = _session(org, email=email)
        ticket = _ticket(org, requester_email=email)
        _run()
        _reload(session, ticket)
        assert session.contact is None
        assert ticket.contact is None
        assert not Contact.objects.filter(organization=org).exists()

    def test_invalid_email_of_an_identified_session_is_not_declared(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1", email="not an email")
        _run()
        session.refresh_from_db()
        assert session.contact.external_id == "u1"
        assert session.contact.declared_email == ""

    def test_email_too_long_once_lowercased_is_skipped(self):
        # U+0130 takes two characters once lowercased, so a value that fits the
        # column can outgrow it after normalization.
        assert clean_email("a@" + "İ" * 200 + "." + "b" * 60 + ".io") == ""
        assert clean_email("a" * 250 + "@x.io") == ""

    def test_longest_valid_email_is_kept(self):
        email = "a" * 60 + "@" + ".".join(["b" * 60] * 3) + ".cc" + "c" * 6
        assert len(email) <= 254
        assert clean_email(email) == email

    @pytest.mark.parametrize("external_id", ["  ", " u1", "email:a@x.io", "company\nc"])
    def test_session_with_an_id_it_cant_have_claims_an_identity_and_gets_none(
        self, external_id
    ):
        # Same rule as the service: it isn't stored as is, and the session doesn't
        # fall back on its email since it claimed an identity.
        org = OrganizationFactory()
        session = _session(org, external_user_id=external_id, email="a@x.io")
        followed = _ticket(org, widget_session=session, requester_email="a@x.io")
        _run()
        _reload(session, followed)
        assert session.contact is None
        assert followed.contact is None
        assert not Contact.objects.filter(organization=org).exists()

    @pytest.mark.parametrize("external_id", [" u1", "email:a@x.io", "company\nc"])
    def test_session_with_an_id_it_cant_have_vouches_for_nothing(self, external_id):
        org = OrganizationFactory()
        _session(org, external_user_id=external_id)
        with_email = _ticket(
            org, external_user_id=external_id, requester_email="a@x.io"
        )
        without = _ticket(org, external_user_id=external_id)
        _run()
        _reload(with_email, without)
        assert (with_email.contact.email, with_email.contact.external_id) == (
            "a@x.io",
            "",
        )
        assert without.contact is None
        assert Contact.objects.filter(organization=org).count() == 1


@pytest.mark.django_db
class TestDeclaredEmailAndName:
    def test_session_email_wins_over_its_tickets(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1", email="session@x.io")
        _ticket(org, external_user_id="u1", requester_email="ticket@x.io")
        _run()
        session.refresh_from_db()
        assert session.contact.declared_email == "session@x.io"

    def test_latest_usable_ticket_email_fills_a_session_without_one(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1", email="not an email")
        now = timezone.now()
        for age, email in ((3, "old@x.io"), (2, "NEW@x.io"), (1, "not an email")):
            ticket = _ticket(org, external_user_id="u1", requester_email=email)
            _dated(ticket, created_at=now - timedelta(days=age))
        _run()
        session.refresh_from_db()
        assert session.contact.declared_email == "new@x.io"

    def test_name_comes_from_the_most_recent_session_of_the_email(self):
        org = OrganizationFactory()
        now = timezone.now()
        old = _session(org, email="a@x.io", name="Old")
        new = _session(org, email="a@x.io", name="  New ")
        blank = _session(org, email="a@x.io", name="   ")
        _dated(old, last_seen_at=now - timedelta(days=3))
        _dated(new, last_seen_at=now - timedelta(days=2))
        _dated(blank, last_seen_at=now - timedelta(days=1))
        _run()
        new.refresh_from_db()
        assert new.contact.name == "New"

    def test_name_falls_back_on_the_latest_ticket(self):
        org = OrganizationFactory()
        now = timezone.now()
        session = _session(org, external_user_id="u1")
        old = _ticket(org, external_user_id="u1", requester_name="Old")
        new = _ticket(org, external_user_id="u1", requester_name="New")
        _dated(old, created_at=now - timedelta(days=2))
        _dated(new, created_at=now - timedelta(days=1))
        _run()
        session.refresh_from_db()
        assert session.contact.name == "New"

    def test_session_name_wins_over_tickets(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1", name="Session")
        _ticket(org, external_user_id="u1", requester_name="Ticket")
        _run()
        session.refresh_from_db()
        assert session.contact.name == "Session"


@pytest.mark.django_db
class TestSeenDates:
    def test_come_from_the_rows_linked_to_the_contact(self):
        org = OrganizationFactory()
        now = timezone.now()
        session = _dated(
            _session(org, external_user_id="u1", email="a@x.io"),
            created_at=now - timedelta(days=10),
            last_seen_at=now - timedelta(days=5),
        )
        ticket = _dated(
            _ticket(org, external_user_id="u1"),
            created_at=now - timedelta(days=2),
        )
        _run()
        _reload(session, ticket)
        contact = session.contact
        assert contact == ticket.contact
        assert contact.first_seen_at == now - timedelta(days=10)
        assert contact.last_seen_at == now - timedelta(days=2)

    def test_ticket_older_than_the_session_sets_the_first_date(self):
        org = OrganizationFactory()
        now = timezone.now()
        session = _dated(
            _session(org, email="a@x.io"),
            created_at=now - timedelta(days=5),
            last_seen_at=now - timedelta(days=1),
        )
        _dated(
            _ticket(org, requester_email="a@x.io"),
            created_at=now - timedelta(days=9),
        )
        _run()
        session.refresh_from_db()
        assert session.contact.first_seen_at == now - timedelta(days=9)
        assert session.contact.last_seen_at == now - timedelta(days=1)

    def test_ticket_only_contact(self):
        org = OrganizationFactory()
        now = timezone.now()
        ticket = _dated(
            _ticket(org, requester_email="a@x.io"), created_at=now - timedelta(days=4)
        )
        _run()
        ticket.refresh_from_db()
        assert ticket.contact.first_seen_at == now - timedelta(days=4)
        assert ticket.contact.last_seen_at == now - timedelta(days=4)

    def test_linking_bumps_no_date_on_the_rows(self):
        org = OrganizationFactory()
        past = timezone.now() - timedelta(days=30)
        session = _dated(
            _session(org, email="a@x.io"), last_seen_at=past, updated_at=past
        )
        followed = _dated(
            _ticket(org, widget_session=session, requester_email="a@x.io"),
            updated_at=past,
        )
        standalone = _dated(_ticket(org, requester_email="b@x.io"), updated_at=past)
        _run()
        _reload(session, followed, standalone)
        assert session.contact_id and followed.contact_id and standalone.contact_id
        assert session.last_seen_at == past
        assert session.updated_at == past
        assert followed.updated_at == past
        assert standalone.updated_at == past


@pytest.mark.django_db
class TestSessionAndItsTickets:
    def test_ticket_follows_a_session_whatever_its_own_values(self):
        org = OrganizationFactory()
        session = _session(org, email="f@x.io")
        blank = _ticket(org, requester_email="   ", widget_session=session)
        other_email = _ticket(org, requester_email="g@x.io", widget_session=session)
        other_id = _ticket(org, external_user_id="u1", widget_session=session)
        _run()
        _reload(session, blank, other_email, other_id)
        assert session.contact.email == "f@x.io"
        assert blank.contact == session.contact
        assert other_email.contact == session.contact
        assert other_id.contact == session.contact
        assert Contact.objects.filter(organization=org).count() == 1

    def test_ticket_follows_an_identified_session(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1")
        ticket = _ticket(org, requester_email="a@x.io", widget_session=session)
        _run()
        _reload(session, ticket)
        assert ticket.contact == session.contact
        assert session.contact.external_id == "u1"
        assert session.contact.email == ""
        assert session.contact.declared_email == "a@x.io"

    def test_session_without_identity_takes_its_latest_ticket_email(self):
        org = OrganizationFactory()
        now = timezone.now()
        session = _session(org, email="not an email")
        old = _ticket(org, requester_email="old@x.io", widget_session=session)
        new = _ticket(org, requester_email="new@x.io", widget_session=session)
        _dated(old, created_at=now - timedelta(days=2))
        _dated(new, created_at=now - timedelta(days=1))
        _run()
        _reload(session, old, new)
        assert session.contact.email == "new@x.io"
        assert old.contact == session.contact
        assert new.contact == session.contact

    def test_anonymous_session_never_takes_an_external_id_from_its_tickets(self):
        # Nothing proves it, and the service wouldn't keep that link on a resume.
        org = OrganizationFactory()
        _session(org, external_user_id="u1")
        session = _session(org)
        vouched = _ticket(org, external_user_id="u1", widget_session=session)
        _run()
        _reload(session, vouched)
        assert session.contact is None
        assert vouched.contact.external_id == "u1"

    def test_ticket_with_an_email_decides_over_a_ticket_external_id(self):
        org = OrganizationFactory()
        _session(org, external_user_id="u1")
        session = _session(org)
        vouched = _ticket(org, external_user_id="u1", widget_session=session)
        emailed = _ticket(org, requester_email="a@x.io", widget_session=session)
        _run()
        _reload(session, vouched, emailed)
        assert session.contact.email == "a@x.io"
        assert emailed.contact == session.contact
        assert vouched.contact == session.contact

    def test_session_and_ticket_without_identity_stay_unlinked(self):
        org = OrganizationFactory()
        session = _session(org)
        ticket = _ticket(org, widget_session=session)
        _run()
        _reload(session, ticket)
        assert session.contact is None
        assert ticket.contact is None

    def test_ticket_doesnt_follow_a_session_of_another_organization(self):
        org, other = OrganizationFactory(), OrganizationFactory()
        session = _session(other, email="a@x.io")
        ticket = _ticket(org, requester_email="a@x.io", widget_session=session)
        _run()
        _reload(session, ticket)
        assert session.contact.organization == other
        assert ticket.contact.organization == org

    def test_session_doesnt_take_an_identity_from_a_ticket_of_another_organization(
        self,
    ):
        org, other = OrganizationFactory(), OrganizationFactory()
        session = _session(other)
        ticket = _ticket(org, requester_email="a@x.io", widget_session=session)
        _run()
        _reload(session, ticket)
        assert session.contact is None
        assert ticket.contact.organization == org


@pytest.mark.django_db
class TestExistingRows:
    def test_is_idempotent(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1", email="a@x.io")
        ticket = _ticket(org, requester_email="c@x.io")
        _run()
        _reload(session, ticket)
        contact_ids = (session.contact_id, ticket.contact_id)
        snapshot = list(Contact.objects.order_by("pk").values())
        _run()
        _reload(session, ticket)
        assert (session.contact_id, ticket.contact_id) == contact_ids
        assert list(Contact.objects.order_by("pk").values()) == snapshot

    def test_second_run_links_new_rows_to_existing_contacts_without_writing_them(self):
        org = OrganizationFactory()
        _ticket(org, requester_email="a@x.io")
        _run()
        snapshot = list(Contact.objects.order_by("pk").values())
        later = _ticket(org, requester_email="a@x.io", requester_name="Named")
        _run()
        later.refresh_from_db()
        assert later.contact.email == "a@x.io"
        assert list(Contact.objects.order_by("pk").values()) == snapshot

    def test_existing_contacts_are_reused_and_not_written(self):
        org = OrganizationFactory()
        by_id = ContactFactory(organization=org, email="", external_id="u1", name="")
        by_email = ContactFactory(organization=org, email="a@x.io", name="")
        snapshot = list(Contact.objects.order_by("pk").values())
        session = _session(org, external_user_id="u1", email="x@x.io", name="Forged")
        ticket = _ticket(org, requester_email="A@x.io", requester_name="Forged")
        _run()
        _reload(session, ticket)
        assert session.contact == by_id
        assert ticket.contact == by_email
        assert list(Contact.objects.order_by("pk").values()) == snapshot

    def test_linked_rows_are_left_alone(self):
        org = OrganizationFactory()
        chosen = ContactFactory(organization=org)
        session = _session(org, email="a@x.io", contact=chosen)
        ticket = _ticket(org, requester_email="b@x.io", contact=chosen)
        _run()
        _reload(session, ticket)
        assert session.contact == chosen
        assert ticket.contact == chosen
        assert list(Contact.objects.filter(organization=org)) == [chosen]

    def test_ticket_follows_a_session_linked_before(self):
        org = OrganizationFactory()
        chosen = ContactFactory(organization=org)
        session = _session(org, contact=chosen)
        ticket = _ticket(org, requester_email="b@x.io", widget_session=session)
        _run()
        ticket.refresh_from_db()
        assert ticket.contact == chosen

    def test_ticket_doesnt_follow_a_session_linked_to_another_organization(self):
        org = OrganizationFactory()
        foreign = ContactFactory(organization=OrganizationFactory())
        session = _session(org, contact=foreign)
        ticket = _ticket(org, widget_session=session)
        _run()
        ticket.refresh_from_db()
        assert ticket.contact is None

    def test_anonymized_contact_is_neither_linked_nor_written(self):
        org = OrganizationFactory()
        gone = ContactFactory(
            organization=org, email="", external_id="u1", name="", is_anonymized=True
        )
        snapshot = list(Contact.objects.filter(pk=gone.pk).values())
        session = _session(org, external_user_id="u1", email="a@x.io", name="Back")
        followed = _ticket(org, requester_email="b@x.io", widget_session=session)
        standalone = _ticket(org, external_user_id="u1")
        _run()
        _reload(session, followed, standalone)
        assert session.contact is None
        assert followed.contact is None
        assert standalone.contact is None
        assert list(Contact.objects.filter(pk=gone.pk).values()) == snapshot
        assert list(Contact.objects.filter(organization=org)) == [gone]

    def test_contact_created_concurrently_wins_the_conflict(self):
        org = OrganizationFactory()
        by_id = {}
        session = _session(org, external_user_id="u1", email="a@x.io")
        ticket = _ticket(org, requester_email="b@x.io")

        def race():
            by_id["u1"] = ContactFactory(
                organization=org, email="", external_id="u1", name="Winner"
            )
            by_id["b"] = ContactFactory(organization=org, email="b@x.io", name="Winner")

        wrapper = _before_statement('INSERT INTO "contacts_contact"', race)
        with connection.execute_wrapper(wrapper):
            _run()
        _reload(session, ticket)
        assert session.contact == by_id["u1"]
        assert session.contact.name == "Winner"
        assert session.contact.declared_email == ""
        assert session.contact.first_seen_at is None
        assert ticket.contact == by_id["b"]

    def test_row_linked_concurrently_is_left_alone(self):
        org = OrganizationFactory()
        winner = ContactFactory(organization=org)
        session = _session(org, email="a@x.io")

        def race():
            WidgetSession.objects.filter(pk=session.pk).update(contact=winner)

        wrapper = _before_statement('UPDATE "tickets_widgetsession"', race)
        with connection.execute_wrapper(wrapper):
            _run()
        session.refresh_from_db()
        assert session.contact == winner


@pytest.mark.django_db
class TestUnsignedIdentity:
    """``widget_submit`` takes any external id: only a session proves one."""

    def test_unvouched_ticket_falls_through_to_its_email(self):
        org = OrganizationFactory()
        ticket = _ticket(
            org,
            external_user_id="victim",
            requester_email="A@x.io",
            requester_name="Forged",
        )
        _run()
        ticket.refresh_from_db()
        contact = ticket.contact
        assert (contact.external_id, contact.email) == ("", "a@x.io")
        assert contact.declared_email == ""
        assert contact.name == ""

    def test_unvouched_ticket_without_an_email_stays_unlinked(self):
        org = OrganizationFactory()
        ticket = _ticket(org, external_user_id="victim", requester_name="Forged")
        _run()
        ticket.refresh_from_db()
        assert ticket.contact is None
        assert not Contact.objects.filter(organization=org).exists()

    def test_unvouched_ticket_doesnt_reach_an_existing_contact_of_that_id(self):
        org = OrganizationFactory()
        victim = ContactFactory(organization=org, email="", external_id="victim")
        ticket = _ticket(org, external_user_id="victim")
        _run()
        ticket.refresh_from_db()
        assert ticket.contact is None
        assert list(Contact.objects.filter(organization=org)) == [victim]

    def test_session_of_another_organization_vouches_for_nothing(self):
        org = OrganizationFactory()
        _session(OrganizationFactory(), external_user_id="u1")
        ticket = _ticket(org, external_user_id="u1", requester_email="a@x.io")
        _run()
        ticket.refresh_from_db()
        assert (ticket.contact.external_id, ticket.contact.email) == ("", "a@x.io")

    def test_vouched_ticket_reaches_the_contact_of_the_session(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1")
        ticket = _ticket(org, external_user_id="u1", requester_name="Ann")
        _run()
        _reload(session, ticket)
        assert ticket.contact == session.contact
        assert session.contact.name == "Ann"

    def test_unvouched_ticket_gives_a_followed_session_no_name_nor_email(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1")
        ticket = _ticket(
            org,
            widget_session=session,
            external_user_id="victim",
            requester_name="Forged",
            requester_email="forged@x.io",
        )
        _run()
        _reload(session, ticket)
        assert ticket.contact == session.contact
        assert session.contact.name == ""
        assert session.contact.declared_email == ""

    def test_unvouched_ticket_keeps_seen_dates_and_a_signed_one_gives_the_name(self):
        org = OrganizationFactory()
        now = timezone.now()
        session = _dated(
            _session(org, external_user_id="u1"), last_seen_at=now - timedelta(days=9)
        )
        signed = _ticket(org, external_user_id="u1", requester_name="Ann")
        forged = _ticket(
            org, widget_session=session, external_user_id="x", requester_name="Forged"
        )
        _dated(signed, created_at=now - timedelta(days=2))
        _dated(forged, created_at=now - timedelta(days=1))
        _run()
        session.refresh_from_db()
        assert session.contact.name == "Ann"
        assert session.contact.last_seen_at == forged.created_at

    def test_ticket_without_an_external_id_still_names_an_email_contact(self):
        org = OrganizationFactory()
        ticket = _ticket(org, requester_email="a@x.io", requester_name="Bea")
        _run()
        ticket.refresh_from_db()
        assert ticket.contact.name == "Bea"


@pytest.mark.django_db
class TestResumeOfASessionLinkedThroughItsTickets:
    """The back-fill and the service must agree on what identifies a session."""

    def _linked(self, org, **kwargs):
        session = _session(org, **kwargs)
        _ticket(org, widget_session=session, requester_email="A@x.io")
        _run()
        session.refresh_from_db()
        assert session.contact.email == "a@x.io"
        return session

    @pytest.mark.parametrize("email", ["", "not an email", "   "])
    def test_takes_the_email_that_identified_it(self, email):
        session = self._linked(OrganizationFactory(), email=email)
        assert session.email == "a@x.io"

    def test_the_email_it_takes_proves_nothing(self):
        session = self._linked(
            OrganizationFactory(), email="", email_verified_at=timezone.now()
        )
        assert session.email_verified_at is None
        assert session.contact.email_verified_at is None

    def test_taking_the_email_bumps_no_date(self):
        org = OrganizationFactory()
        past = timezone.now() - timedelta(days=30)
        session = _dated(_session(org), last_seen_at=past, updated_at=past)
        _ticket(org, widget_session=session, requester_email="a@x.io")
        _run()
        session.refresh_from_db()
        assert (session.last_seen_at, session.updated_at) == (past, past)

    def test_keeps_its_contact_through_the_service(self):
        session = self._linked(OrganizationFactory())
        contact_id = session.contact_id
        assert resolve_contact_for_widget_session(session).pk == contact_id
        session.refresh_from_db()
        assert session.contact_id == contact_id

    def test_keeps_its_contact_on_resume_and_new_tickets_get_it(self):
        org = OrganizationFactory()
        session = self._linked(org)
        contact_id = session.contact_id
        client = APIClient()
        headers = {"HTTP_X_WIDGET_TOKEN": org.api_token}
        resume = client.post(
            "/api/v1/tickets/widget_session/",
            {"session_id": str(session.id)},
            format="json",
            **headers,
        )
        assert resume.status_code == 200
        assert resume.data["session_id"] == str(session.id)
        session.refresh_from_db()
        assert session.contact_id == contact_id
        message = client.post(
            "/api/v1/tickets/widget_message/",
            {"body": "Hello again"},
            format="json",
            HTTP_X_WIDGET_SESSION=str(session.id),
            **headers,
        )
        assert message.status_code == 201
        assert Ticket.objects.get(id=message.data["ticket_id"]).contact_id == contact_id

    def test_session_whose_ticket_email_is_anonymized_is_left_as_it_was(self):
        org = OrganizationFactory()
        ContactFactory(organization=org, email="a@x.io", is_anonymized=True)
        session = _session(org, email="not an email")
        ticket = _ticket(org, widget_session=session, requester_email="a@x.io")
        _run()
        _reload(session, ticket)
        assert session.contact is None
        assert session.email == "not an email"
        assert ticket.contact is None

    def test_email_written_concurrently_is_left_alone(self):
        org = OrganizationFactory()
        winner = ContactFactory(organization=org)
        session = _session(org)
        _ticket(org, widget_session=session, requester_email="a@x.io")

        def race():
            WidgetSession.objects.filter(pk=session.pk).update(
                contact=winner, email="winner@x.io"
            )

        wrapper = _before_statement('UPDATE "tickets_widgetsession"', race)
        with connection.execute_wrapper(wrapper):
            _run()
        session.refresh_from_db()
        assert (session.contact, session.email) == (winner, "winner@x.io")


def _nameless_rows(count, prefix):
    org = OrganizationFactory()
    for n in range(count):
        session = _session(org, email=f"{prefix}{n}@x.io")
        _ticket(org, widget_session=session)
        identified = _session(org, external_user_id=f"{prefix}{n}")
        _ticket(org, external_user_id=f"{prefix}{n}", requester_email="t@x.io")
        _ticket(org, widget_session=identified, requester_email="u@x.io")
        _ticket(org, requester_email=f"{prefix}t{n}@x.io")


@pytest.mark.django_db
class TestRequesterAccount:
    """Tickets saying nothing of their sender, but for an end-user account."""

    def _customer(self, org, **kwargs):
        kwargs.setdefault("email", "Jane@Customer.example")
        kwargs.setdefault("first_name", "Jane")
        kwargs.setdefault("last_name", "Doe")
        return EndUserFactory(organization=org, **kwargs)

    @pytest.mark.parametrize(
        "cleared", [{"contact": None}, {"contact": None, "requester_email": ""}]
    )
    def test_not_from_the_former_requester_of_an_anonymized_ticket(self, cleared):
        org = OrganizationFactory()
        account = self._customer(org)
        contact = ContactFactory(organization=org, email=account.email)
        ticket = _ticket(org, contact=contact, requester=account)
        anonymize_contact(contact)
        # An agent clears the contact: the ticket is back among those it would link.
        Ticket.objects.filter(pk=ticket.pk).update(**cleared)

        _run()

        ticket.refresh_from_db()
        assert ticket.contact is None
        assert list(Contact.objects.all()) == [contact]

    def test_links_to_a_declared_contact_with_the_account_name(self):
        org = OrganizationFactory()
        ticket = _ticket(org, requester=self._customer(org))

        _run()

        _reload(ticket)
        contact = ticket.contact
        assert contact.organization == org
        assert (contact.email, contact.name) == ("jane@customer.example", "Jane Doe")
        assert contact.declared_email == ""
        assert contact.external_id == ""
        assert contact.email_verified_at is None
        assert contact.first_seen_at == ticket.created_at
        assert contact.last_seen_at == ticket.created_at

    def test_tickets_of_one_account_share_a_contact(self):
        org = OrganizationFactory()
        customer = self._customer(org)
        tickets = [_ticket(org, requester=customer) for _ in range(3)]

        _run()

        _reload(*tickets)
        assert len({ticket.contact_id for ticket in tickets}) == 1
        assert Contact.objects.filter(organization=org).count() == 1

    def test_links_to_an_existing_contact_without_writing_on_it(self):
        org = OrganizationFactory()
        existing = ContactFactory(
            organization=org, email="jane@customer.example", name="J."
        )
        before = existing.updated_at
        ticket = _ticket(org, requester=self._customer(org))

        assert backfill(django_apps, None) == 0

        _reload(ticket, existing)
        assert ticket.contact == existing
        assert existing.name == "J."
        assert existing.updated_at == before

    @pytest.mark.parametrize("factory", [UserFactory, AdminFactory])
    def test_an_agent_or_admin_doesnt_become_a_contact(self, factory):
        org = OrganizationFactory()
        ticket = _ticket(org, requester=factory(organization=org))

        _run()

        _reload(ticket)
        assert ticket.contact is None
        assert not Contact.objects.exists()

    @pytest.mark.parametrize("factory", [UserFactory, AdminFactory])
    def test_the_own_email_of_an_agent_or_admin_makes_no_contact(self, factory):
        org = OrganizationFactory()
        staff = factory(organization=org, email="staff@x.io")
        ticket = _ticket(org, requester=staff, requester_email="Staff@X.io")

        _run()

        _reload(ticket)
        assert ticket.contact is None
        assert not Contact.objects.exists()

    def test_an_agent_filing_for_a_customer_still_makes_a_contact(self):
        org = OrganizationFactory()
        staff = UserFactory(organization=org, email="staff@x.io")
        ticket = _ticket(org, requester=staff, requester_email="cid@x.io")

        _run()

        _reload(ticket)
        assert ticket.contact.email == "cid@x.io"

    @pytest.mark.parametrize("own_email", [False, True])
    def test_a_superuser_counts_as_staff_whatever_the_role(self, own_email):
        org = OrganizationFactory()
        superuser = EndUserFactory(
            organization=org, email="root@x.io", is_superuser=True
        )
        ticket = _ticket(
            org,
            requester=superuser,
            requester_email="root@x.io" if own_email else "",
        )

        _run()

        _reload(ticket)
        assert ticket.contact is None
        assert not Contact.objects.exists()

    def test_a_session_doesnt_take_the_email_an_agent_filed_with(self):
        org = OrganizationFactory()
        staff = UserFactory(organization=org, email="staff@x.io")
        session = _session(org)
        ticket = _ticket(
            org, widget_session=session, requester=staff, requester_email="staff@x.io"
        )

        _run()

        _reload(session, ticket)
        assert session.email == ""
        assert session.contact is None
        assert ticket.contact is None
        assert not Contact.objects.exists()

    def test_a_session_skips_the_email_of_an_agent_for_an_older_usable_one(self):
        org = OrganizationFactory()
        staff = UserFactory(organization=org, email="staff@x.io")
        session = _session(org)
        older = _ticket(org, widget_session=session, requester_email="cid@x.io")
        _dated(older, created_at=timezone.now() - timedelta(days=1))
        _ticket(
            org, widget_session=session, requester=staff, requester_email="staff@x.io"
        )

        _run()

        _reload(session)
        assert session.email == "cid@x.io"

    def test_an_identified_contact_declares_no_email_of_an_agent(self):
        org = OrganizationFactory()
        _session(org, external_user_id="u1")
        staff = UserFactory(organization=org, email="staff@x.io")
        ticket = _ticket(
            org,
            requester=staff,
            requester_email="staff@x.io",
            requester_name="Staff",
            external_user_id="u1",
        )

        _run()

        _reload(ticket)
        assert ticket.contact.external_id == "u1"
        assert ticket.contact.declared_email == ""
        assert ticket.contact.name == ""

    def test_an_account_of_another_organization_doesnt_become_a_contact(self):
        org = OrganizationFactory()
        ticket = _ticket(org, requester=self._customer(OrganizationFactory()))

        _run()

        _reload(ticket)
        assert ticket.contact is None
        assert not Contact.objects.exists()

    def test_an_account_with_no_organization_does(self):
        org = OrganizationFactory()
        ticket = _ticket(org, requester=self._customer(None))

        _run()

        _reload(ticket)
        assert ticket.contact.email == "jane@customer.example"

    def test_the_tickets_own_email_wins(self):
        org = OrganizationFactory()
        ticket = _ticket(
            org,
            requester=self._customer(org),
            requester_email="other@x.io",
            requester_name="Other",
        )

        _run()

        _reload(ticket)
        assert (ticket.contact.email, ticket.contact.name) == ("other@x.io", "Other")

    def test_an_unusable_email_falls_back_on_the_account(self):
        org = OrganizationFactory()
        ticket = _ticket(
            org, requester=self._customer(org), requester_email="not an email"
        )

        _run()

        _reload(ticket)
        assert ticket.contact.email == "jane@customer.example"

    def test_the_account_doesnt_name_a_contact_of_another_address(self):
        org = OrganizationFactory()
        ticket = _ticket(
            org, requester=self._customer(org), requester_email="other@x.io"
        )

        _run()

        _reload(ticket)
        assert (ticket.contact.email, ticket.contact.name) == ("other@x.io", "")

    def test_a_vouched_external_id_wins(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1")
        ticket = _ticket(org, requester=self._customer(org), external_user_id="u1")

        _run()

        _reload(ticket, session)
        assert ticket.contact == session.contact
        assert ticket.contact.email == ""
        assert ticket.contact.name == ""

    def test_an_unvouched_external_id_is_no_identity(self):
        org = OrganizationFactory()
        ticket = _ticket(org, requester=self._customer(org), external_user_id="forged")

        _run()

        _reload(ticket)
        assert ticket.contact.external_id == ""
        assert ticket.contact.email == "jane@customer.example"
        assert ticket.contact.name == "Jane Doe"

    def test_a_widget_session_keeps_deciding(self):
        org = OrganizationFactory()
        ticket = _ticket(
            org, requester=self._customer(org), widget_session=_session(org)
        )

        _run()

        _reload(ticket)
        assert ticket.contact is None
        assert not Contact.objects.exists()

    def test_an_anonymized_contact_isnt_linked(self):
        org = OrganizationFactory()
        ContactFactory(
            organization=org, email="jane@customer.example", is_anonymized=True
        )
        ticket = _ticket(org, requester=self._customer(org))

        _run()

        _reload(ticket)
        assert ticket.contact is None

    def test_an_unusable_account_email_stays_unlinked(self):
        org = OrganizationFactory()
        ticket = _ticket(org, requester=self._customer(org, email="not an email"))

        _run()

        _reload(ticket)
        assert ticket.contact is None

    def test_a_name_longer_than_a_contact_takes_is_cut(self):
        org = OrganizationFactory()
        customer = self._customer(org, first_name="a" * 150, last_name="b" * 150)
        ticket = _ticket(org, requester=customer)

        _run()

        _reload(ticket)
        assert len(ticket.contact.name) == 255

    def test_is_idempotent(self):
        org = OrganizationFactory()
        ticket = _ticket(org, requester=self._customer(org))

        _run()
        _reload(ticket)
        contact_id = ticket.contact_id

        assert backfill(django_apps, None) == 0
        _reload(ticket)
        assert ticket.contact_id == contact_id

    def test_links_the_tickets_of_the_seed(self):
        call_command("seed", stdout=StringIO())
        Ticket.objects.update(contact=None)
        Contact.objects.all().delete()
        assert User.objects.filter(role=User.Role.END_USER).count() == 3

        _run()

        assert Ticket.objects.count() == 7
        assert not Ticket.objects.filter(contact__isnull=True).exists()
        assert Contact.objects.count() == 3

    def test_query_count_doesnt_grow_with_the_tickets(self):
        org = OrganizationFactory()
        _ticket(org, requester=self._customer(org))
        with CaptureQueriesContext(connection) as few:
            _run()
        for n in range(30):
            _ticket(
                org,
                requester=self._customer(org, email=f"c{n}@customer.example"),
            )
        with CaptureQueriesContext(connection) as many:
            _run()
        assert Contact.objects.count() == 31
        assert len(many) == len(few)


@pytest.mark.django_db
class TestCost:
    def test_query_count_doesnt_grow_with_the_contacts(self):
        _nameless_rows(2, "few")
        with CaptureQueriesContext(connection) as few:
            _run()
        _nameless_rows(40, "many")
        with CaptureQueriesContext(connection) as many:
            _run()
        assert Contact.objects.count() > 120
        assert len(many) == len(few)

    def test_contacts_are_filled_without_reading_rows_for_each_of_them(self):
        # A correlated subquery is one statement and one scan per contact: the query
        # count can't see it.
        _nameless_rows(3, "a")
        with CaptureQueriesContext(connection) as queries:
            _run()
        fills = [
            q["sql"]
            for q in queries
            if q["sql"].startswith('UPDATE "contacts_contact"')
        ]
        assert fills
        assert not [sql for sql in fills if "SELECT" in sql]

    def test_statistics_are_refreshed_before_the_statements_relying_on_them(self):
        _nameless_rows(1, "a")
        with CaptureQueriesContext(connection) as queries:
            _run()
        statements = [q["sql"] for q in queries]

        def first(prefix):
            return next(n for n, sql in enumerate(statements) if sql.startswith(prefix))

        analyze_sessions = first('ANALYZE "tickets_widgetsession"')
        analyze_tickets = first('ANALYZE "tickets_ticket"')
        assert first('UPDATE "tickets_widgetsession"') < analyze_sessions
        assert analyze_sessions < first('UPDATE "tickets_ticket"')
        assert first('UPDATE "tickets_ticket"') < analyze_tickets
        assert analyze_tickets < first('UPDATE "contacts_contact"')

    def test_no_statistics_are_refreshed_on_another_database(self):
        schema_editor = mock.Mock()
        schema_editor.connection.vendor = "sqlite"
        with mock.patch("apps.contacts.backfill.connections") as fallback:
            _analyze(schema_editor, "tickets_ticket")
        schema_editor.connection.cursor.assert_not_called()
        fallback.__getitem__.assert_not_called()


@pytest.mark.django_db
def test_batches_cover_every_row(monkeypatch):
    monkeypatch.setattr("apps.contacts.backfill.BATCH_SIZE", 2)
    org = OrganizationFactory()
    sessions = [_session(org, email=f"s{n}@x.io") for n in range(5)]
    tickets = [_ticket(org, requester_email=f"t{n}@x.io") for n in range(5)]
    _run()
    _reload(*sessions, *tickets)
    assert all(row.contact_id for row in [*sessions, *tickets])
    assert Contact.objects.filter(organization=org).count() == 10


@pytest.mark.django_db
class TestCommand:
    def _call(self):
        out = StringIO()
        call_command("backfill_contacts", stdout=out)
        return out.getvalue()

    def test_links_what_old_pods_wrote_after_the_migration(self):
        org = OrganizationFactory()
        session = _session(org, external_user_id="u1", email="a@x.io")
        _run()
        session.refresh_from_db()
        later = _ticket(org, widget_session=session)
        standalone = _ticket(org, requester_email="b@x.io")
        assert "1 contact" in self._call()
        _reload(later, standalone)
        assert later.contact == session.contact
        assert standalone.contact.email == "b@x.io"

    def test_is_idempotent_and_writes_no_existing_contact(self):
        org = OrganizationFactory()
        _ticket(org, requester_email="a@x.io")
        self._call()
        snapshot = list(Contact.objects.order_by("pk").values())
        assert "0 contact" in self._call()
        assert list(Contact.objects.order_by("pk").values()) == snapshot

    def test_a_failure_leaves_nothing_behind(self):
        org = OrganizationFactory()
        _ticket(org, requester_email="a@x.io")
        with (
            mock.patch(
                "apps.contacts.backfill._fill_new_contacts",
                side_effect=OperationalError,
            ),
            pytest.raises(OperationalError),
        ):
            self._call()
        assert not Contact.objects.filter(organization=org).exists()


@pytest.mark.django_db(transaction=True)
def test_migration_on_the_historical_state_then_noop_reverse():
    # Historical models have no custom ``save()`` nor properties, so only a real
    # migration shows that the back-fill doesn't depend on them.
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_BACKFILL])
    try:
        org = OrganizationFactory()
        now = timezone.now()
        session = _dated(
            _session(org, external_user_id="u1", email="A@x.io", name="Ann"),
            created_at=now - timedelta(days=3),
            last_seen_at=now - timedelta(days=2),
        )
        followed = _ticket(org, requester_email="a@x.io", widget_session=session)
        _dated(followed, created_at=now - timedelta(days=1))
        anonymous = _session(org, email="B@x.io")
        standalone = _ticket(org, requester_email="b@X.io", requester_name="Bea")
        invalid = _session(org, email="not an email")
        from_account = _ticket(
            org,
            requester=EndUserFactory(
                organization=org,
                email="Cid@x.io",
                first_name="Cid",
                last_name="Campeador",
            ),
        )
        from_agent = _ticket(org, requester=UserFactory(organization=org))

        executor = MigrationExecutor(connection)
        executor.migrate([BACKFILL])

        _reload(session, followed, anonymous, standalone, invalid)
        _reload(from_account, from_agent)
        assert from_account.contact.email == "cid@x.io"
        assert from_account.contact.name == "Cid Campeador"
        assert from_account.contact.email_verified_at is None
        assert from_agent.contact is None
        assert session.contact.external_id == "u1"
        assert session.contact.email == ""
        assert session.contact.declared_email == "a@x.io"
        assert session.contact.name == "Ann"
        assert session.contact.email_verified_at is None
        assert session.contact.first_seen_at == now - timedelta(days=3)
        assert session.contact.last_seen_at == now - timedelta(days=1)
        assert followed.contact == session.contact
        assert anonymous.contact == standalone.contact
        assert anonymous.contact.email == "b@x.io"
        assert anonymous.contact.name == "Bea"
        assert invalid.contact is None

        contact_id = session.contact_id
        count = Contact.objects.count()
        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE_BACKFILL])
        session.refresh_from_db()
        assert session.contact_id == contact_id

        executor = MigrationExecutor(connection)
        executor.migrate([BACKFILL])
        session.refresh_from_db()
        assert session.contact_id == contact_id
        assert Contact.objects.count() == count
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
