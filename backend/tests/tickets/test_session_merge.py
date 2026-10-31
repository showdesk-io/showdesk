"""One widget session per external user: the merge of existing duplicates."""

from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from apps.tickets.session_merge import merge_duplicate_sessions
from tests.factories import ContactFactory, OrganizationFactory, TicketFactory

MERGE_MIGRATION = "0011_one_widget_session_per_external_user"


def _drop_constraint():
    """Let a test create the duplicates that existed before the constraint."""
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX unique_widget_session_external_user_per_org")


def _session(org, age_days: int = 0, seen_days: int | None = None, **kwargs):
    """Create a session, last seen ``seen_days`` ago (by default when it was created)."""
    session = WidgetSession.objects.create(organization=org, **kwargs)
    now = timezone.now()
    WidgetSession.objects.filter(pk=session.pk).update(
        created_at=now - timedelta(days=age_days),
        last_seen_at=now - timedelta(days=age_days if seen_days is None else seen_days),
    )
    session.refresh_from_db()
    return session


@pytest.mark.django_db
class TestMergeDuplicateSessions:
    @pytest.fixture(autouse=True)
    def without_constraint(self):
        _drop_constraint()

    def test_keeps_the_oldest_and_repoints_tickets_and_messages(self):
        org = OrganizationFactory()
        newest = _session(org, age_days=1, external_user_id="u1")
        oldest = _session(org, age_days=3, external_user_id="u1")
        middle = _session(org, age_days=2, external_user_id="u1")
        ticket = TicketFactory(organization=org, widget_session=newest, requester=None)
        other_ticket = TicketFactory(
            organization=org, widget_session=middle, requester=None
        )
        message = TicketMessage.objects.create(
            ticket=ticket, widget_session=newest, body="Hi"
        )
        merge_duplicate_sessions(django_apps, None)
        assert list(WidgetSession.objects.filter(organization=org)) == [oldest]
        ticket.refresh_from_db()
        other_ticket.refresh_from_db()
        message.refresh_from_db()
        assert ticket.widget_session == oldest
        assert other_ticket.widget_session == oldest
        assert message.widget_session == oldest

    def test_kept_session_takes_the_values_of_the_most_recently_seen(self):
        org = OrganizationFactory()
        oldest = _session(
            org, age_days=3, external_user_id="u1", name="A", email="a@x.io"
        )
        proven_at = timezone.now()
        newest = _session(
            org,
            age_days=1,
            external_user_id="u1",
            name="B",
            email="b@x.io",
            email_verified_at=proven_at,
        )
        merge_duplicate_sessions(django_apps, None)
        oldest.refresh_from_db()
        assert (oldest.name, oldest.email) == ("B", "b@x.io")
        assert oldest.email_verified_at == proven_at
        assert oldest.last_seen_at == newest.last_seen_at

    def test_recency_is_about_being_seen_not_being_created(self):
        org = OrganizationFactory()
        proven_at = timezone.now()
        oldest = _session(
            org,
            age_days=3,
            seen_days=1,
            external_user_id="u1",
            name="A",
            email="a@x.io",
            email_verified_at=proven_at,
        )
        seen_at = oldest.last_seen_at
        _session(
            org,
            age_days=2,
            seen_days=2,
            external_user_id="u1",
            name="B",
            email="b@x.io",
        )
        merge_duplicate_sessions(django_apps, None)
        oldest.refresh_from_db()
        assert (oldest.name, oldest.email) == ("A", "a@x.io")
        assert oldest.email_verified_at == proven_at
        assert oldest.last_seen_at == seen_at

    def test_blank_values_of_the_most_recently_seen_dont_win(self):
        org = OrganizationFactory()
        contact = ContactFactory(organization=org)
        proven_at = timezone.now()
        oldest = _session(org, age_days=3, external_user_id="u1")
        _session(
            org,
            age_days=2,
            external_user_id="u1",
            name="Old",
            email="old@x.io",
            contact=contact,
            email_verified_at=proven_at,
        )
        newest = _session(org, age_days=1, external_user_id="u1", name="  ")
        merge_duplicate_sessions(django_apps, None)
        oldest.refresh_from_db()
        assert oldest.name == "Old"
        assert oldest.email == "old@x.io"
        assert oldest.email_verified_at == proven_at
        assert oldest.contact == contact
        assert oldest.last_seen_at == newest.last_seen_at

    def test_a_proof_doesnt_outlive_the_email_it_was_about(self):
        org = OrganizationFactory()
        oldest = _session(
            org,
            age_days=3,
            external_user_id="u1",
            email="a@x.io",
            email_verified_at=timezone.now(),
        )
        _session(org, age_days=1, external_user_id="u1", email="b@x.io")
        merge_duplicate_sessions(django_apps, None)
        oldest.refresh_from_db()
        assert oldest.email == "b@x.io"
        assert oldest.email_verified_at is None

    def test_leaves_everything_else_alone(self):
        org = OrganizationFactory()
        anonymous = [_session(org), _session(org)]
        other_user = _session(org, external_user_id="u2")
        other_org = _session(OrganizationFactory(), external_user_id="u2")
        merge_duplicate_sessions(django_apps, None)
        for session in [*anonymous, other_user, other_org]:
            assert WidgetSession.objects.filter(pk=session.pk).exists()

    def test_is_idempotent(self):
        org = OrganizationFactory()
        kept = _session(org, age_days=2, external_user_id="u1")
        _session(org, age_days=1, external_user_id="u1")
        merge_duplicate_sessions(django_apps, None)
        merge_duplicate_sessions(django_apps, None)
        assert list(WidgetSession.objects.filter(organization=org)) == [kept]


@pytest.mark.django_db
def test_two_sessions_cant_share_an_external_user():
    org = OrganizationFactory()
    WidgetSession.objects.create(organization=org, external_user_id="u1")
    with pytest.raises(IntegrityError), transaction.atomic():
        WidgetSession.objects.create(organization=org, external_user_id="u1")


@pytest.mark.django_db
def test_anonymous_sessions_and_other_organizations_arent_constrained():
    org = OrganizationFactory()
    WidgetSession.objects.create(organization=org)
    WidgetSession.objects.create(organization=org)
    WidgetSession.objects.create(organization=org, external_user_id="u1")
    WidgetSession.objects.create(
        organization=OrganizationFactory(), external_user_id="u1"
    )


@pytest.mark.django_db(transaction=True)
def test_migration_merges_then_constrains():
    # The merge leaves deferred foreign key checks pending, and Postgres refuses
    # to build an index on a table that has some: only a real migration shows it.
    executor = MigrationExecutor(connection)
    executor.migrate(
        [("tickets", "0010_ticket_contact_widgetsession_contact_and_more")]
    )
    org = OrganizationFactory()
    oldest = _session(org, age_days=2, external_user_id="u1")
    newest = _session(org, age_days=1, external_user_id="u1")
    ticket = TicketFactory(organization=org, widget_session=newest, requester=None)
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", MERGE_MIGRATION)])
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
    assert list(WidgetSession.objects.filter(organization=org)) == [oldest]
    assert Ticket.objects.get(pk=ticket.pk).widget_session_id == oldest.pk
    with pytest.raises(IntegrityError), transaction.atomic():
        WidgetSession.objects.create(organization=org, external_user_id="u1")
