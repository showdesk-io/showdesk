"""Back-fill of contacts from existing widget sessions and tickets."""

from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.contacts.backfill import backfill, clean_email
from apps.contacts.models import Contact
from apps.tickets.models import Ticket, WidgetSession
from tests.factories import ContactFactory, OrganizationFactory, TicketFactory

BEFORE_BACKFILL = ("contacts", "0003_contact_declared_email")
BACKFILL = ("contacts", "0004_backfill_contacts")


def _run():
    backfill(django_apps, None)


def _session(org, **kwargs) -> WidgetSession:
    return WidgetSession.objects.create(organization=org, **kwargs)


def _ticket(org, **kwargs) -> Ticket:
    kwargs.setdefault("requester_email", "")
    return TicketFactory(organization=org, requester=None, **kwargs)


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

    def test_blank_padded_external_id_claims_an_identity_it_cant_have(self):
        # Same rule as the service: it isn't stored as is, and the session doesn't
        # fall back on its email since it claimed an identity.
        org = OrganizationFactory()
        session = _session(org, external_user_id="  ", email="a@x.io")
        ticket = _ticket(org, external_user_id=" u1", requester_email="a@x.io")
        _run()
        _reload(session, ticket)
        assert session.contact is None
        assert ticket.contact is None
        assert not Contact.objects.filter(organization=org).exists()


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

    def test_session_without_identity_prefers_a_ticket_external_id(self):
        org = OrganizationFactory()
        now = timezone.now()
        session = _session(org)
        old = _ticket(org, external_user_id="u1", widget_session=session)
        new = _ticket(org, requester_email="a@x.io", widget_session=session)
        _dated(old, created_at=now - timedelta(days=2))
        _dated(new, created_at=now - timedelta(days=1))
        _run()
        _reload(session, old, new)
        assert session.contact.external_id == "u1"
        assert old.contact == session.contact
        assert new.contact == session.contact

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
def test_query_count_doesnt_grow_with_the_rows():
    def rows(count, prefix):
        org = OrganizationFactory()
        for n in range(count):
            session = _session(org, email=f"{prefix}{n}@x.io")
            _ticket(org, widget_session=session)
            _session(org, external_user_id=f"{prefix}{n}")
            _ticket(org, external_user_id=f"{prefix}t{n}", requester_email="t@x.io")
            _ticket(org, requester_email=f"{prefix}t{n}@x.io")

    rows(2, "few")
    with CaptureQueriesContext(connection) as few:
        _run()
    rows(40, "many")
    with CaptureQueriesContext(connection) as many:
        _run()
    assert len(many) == len(few)


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

        executor = MigrationExecutor(connection)
        executor.migrate([BACKFILL])

        _reload(session, followed, anonymous, standalone, invalid)
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
