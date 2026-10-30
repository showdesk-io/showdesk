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


def _session(org, age_days: int = 0, **kwargs) -> WidgetSession:
    session = WidgetSession.objects.create(organization=org, **kwargs)
    created_at = timezone.now() - timedelta(days=age_days)
    WidgetSession.objects.filter(pk=session.pk).update(created_at=created_at)
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

    def test_kept_session_takes_what_it_lacks_from_the_most_recent(self):
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
        _session(org, age_days=1, external_user_id="u1", name="New")
        merge_duplicate_sessions(django_apps, None)
        oldest.refresh_from_db()
        assert oldest.name == "New"
        assert oldest.email == "old@x.io"
        assert oldest.email_verified_at == proven_at
        assert oldest.contact == contact

    def test_kept_session_keeps_its_own_values_and_its_proof_applies_to_them(self):
        org = OrganizationFactory()
        oldest = _session(
            org, age_days=3, external_user_id="u1", name="A", email="a@x.io"
        )
        _session(
            org,
            age_days=1,
            external_user_id="u1",
            name="B",
            email="b@x.io",
            email_verified_at=timezone.now(),
        )
        merge_duplicate_sessions(django_apps, None)
        oldest.refresh_from_db()
        assert (oldest.name, oldest.email) == ("A", "a@x.io")
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
