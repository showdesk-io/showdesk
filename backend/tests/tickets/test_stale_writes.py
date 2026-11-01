"""A write only saves what it changed, so it can't restore what it read before.

An anonymization between reading a ticket and saving it would otherwise be undone.
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.contacts.gdpr import REMOVED_BODY, REMOVED_TITLE, anonymize_contact
from apps.tickets.models import Ticket
from apps.tickets.views import TicketViewSet
from tests.factories import ContactFactory, TagFactory, TeamFactory, TicketFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/tickets/"
BULK_URL = f"{URL}bulk_update/"


@pytest.fixture
def ticket(organization):
    contact = ContactFactory(organization=organization, name="Alice")
    row = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        title="Alice's invoice",
        description="My card is 4242",
        requester_email="alice@x.io",
        requester_name="Alice",
    )
    Ticket.objects.filter(pk=row.pk).update(
        updated_at=timezone.now() - timedelta(days=1)
    )
    row.refresh_from_db()
    return row


@pytest.fixture
def anonymized_after_load(monkeypatch):
    """Anonymize the ticket's contact right after the view read the ticket."""
    get_object = TicketViewSet.get_object

    def load_then_anonymize(view):
        row = get_object(view)
        anonymize_contact(row.contact)
        return row

    monkeypatch.setattr(TicketViewSet, "get_object", load_then_anonymize)


def _assert_still_scrubbed(ticket) -> None:
    assert ticket.title == REMOVED_TITLE
    assert ticket.description == REMOVED_BODY
    assert ticket.requester_name == "Anonymized contact"
    assert ticket.requester_email.endswith("@example.invalid")


@pytest.mark.usefixtures("anonymized_after_load")
class TestActionsDontRestoreData:
    def test_assign(self, authenticated_client, ticket, agent):
        team = TeamFactory(organization=ticket.organization)
        res = authenticated_client.post(
            f"{URL}{ticket.id}/assign/",
            {"agent_id": str(agent.id), "team_id": str(team.id)},
            format="json",
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        _assert_still_scrubbed(ticket)
        assert ticket.status == Ticket.Status.IN_PROGRESS
        assert ticket.assigned_agent == agent
        assert ticket.assigned_team == team
        assert ticket.first_response_at is not None

    def test_assign_with_an_explicit_null(self, authenticated_client, ticket, agent):
        team = TeamFactory(organization=ticket.organization)
        Ticket.objects.filter(pk=ticket.pk).update(
            assigned_agent=agent, assigned_team=team, status=Ticket.Status.WAITING
        )
        res = authenticated_client.post(
            f"{URL}{ticket.id}/assign/", {"agent_id": None}, format="json"
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        _assert_still_scrubbed(ticket)
        assert ticket.assigned_agent is None
        assert ticket.assigned_team == team
        assert ticket.status == Ticket.Status.WAITING

    def test_assign_to_a_team_alone(self, authenticated_client, ticket):
        team = TeamFactory(organization=ticket.organization)
        res = authenticated_client.post(
            f"{URL}{ticket.id}/assign/", {"team_id": str(team.id)}, format="json"
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        _assert_still_scrubbed(ticket)
        assert ticket.assigned_team == team
        assert ticket.status == Ticket.Status.IN_PROGRESS
        assert ticket.first_response_at is None

    def test_resolve(self, authenticated_client, ticket):
        res = authenticated_client.post(f"{URL}{ticket.id}/resolve/")
        assert res.status_code == 200
        ticket.refresh_from_db()
        _assert_still_scrubbed(ticket)
        assert ticket.status == Ticket.Status.RESOLVED
        assert ticket.resolved_at is not None

    def test_close(self, authenticated_client, ticket):
        res = authenticated_client.post(f"{URL}{ticket.id}/close/")
        assert res.status_code == 200
        ticket.refresh_from_db()
        _assert_still_scrubbed(ticket)
        assert ticket.status == Ticket.Status.CLOSED
        assert ticket.closed_at is not None

    def test_reopen(self, authenticated_client, ticket):
        now = timezone.now()
        Ticket.objects.filter(pk=ticket.pk).update(
            status=Ticket.Status.CLOSED, resolved_at=now, closed_at=now
        )
        res = authenticated_client.post(f"{URL}{ticket.id}/reopen/")
        assert res.status_code == 200
        ticket.refresh_from_db()
        _assert_still_scrubbed(ticket)
        assert ticket.status == Ticket.Status.OPEN
        assert ticket.resolved_at is None
        assert ticket.closed_at is None

    def test_patch(self, authenticated_client, ticket, agent):
        tag = TagFactory(organization=ticket.organization)
        res = authenticated_client.patch(
            f"{URL}{ticket.id}/",
            {
                "status": "waiting",
                "priority": "high",
                "assigned_agent": str(agent.id),
                "tag_ids": [str(tag.id)],
            },
            format="json",
        )
        assert res.status_code == 200, res.data
        ticket.refresh_from_db()
        _assert_still_scrubbed(ticket)
        assert ticket.status == "waiting"
        assert ticket.priority == "high"
        assert ticket.assigned_agent == agent
        assert list(ticket.tags.all()) == [tag]


class TestWritesStillBumpUpdatedAt:
    @pytest.mark.parametrize(
        ("action", "body"),
        [
            ("assign", {}),
            ("resolve", {}),
            ("close", {}),
            ("reopen", {}),
        ],
    )
    def test_actions(self, authenticated_client, ticket, action, body):
        before = ticket.updated_at
        res = authenticated_client.post(
            f"{URL}{ticket.id}/{action}/", body, format="json"
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        assert ticket.updated_at > before

    def test_patch(self, authenticated_client, ticket):
        before = ticket.updated_at
        res = authenticated_client.patch(
            f"{URL}{ticket.id}/", {"priority": "high"}, format="json"
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        assert ticket.priority == "high"
        assert ticket.updated_at > before

    def test_patch_of_tags_only(self, authenticated_client, ticket):
        before = ticket.updated_at
        tag = TagFactory(organization=ticket.organization)
        res = authenticated_client.patch(
            f"{URL}{ticket.id}/", {"tag_ids": [str(tag.id)]}, format="json"
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        assert list(ticket.tags.all()) == [tag]
        assert ticket.updated_at > before

    def test_put(self, authenticated_client, ticket):
        res = authenticated_client.put(
            f"{URL}{ticket.id}/",
            {"title": "Renamed", "priority": "low", "status": "waiting"},
            format="json",
        )
        assert res.status_code == 200, res.data
        ticket.refresh_from_db()
        assert (ticket.title, ticket.priority, ticket.status) == (
            "Renamed",
            "low",
            "waiting",
        )

    def test_patch_tells_the_client_what_it_saved(self, authenticated_client, ticket):
        tag = TagFactory(organization=ticket.organization)
        res = authenticated_client.patch(
            f"{URL}{ticket.id}/",
            {"title": "Renamed", "tag_ids": [str(tag.id)]},
            format="json",
        )
        assert res.data["title"] == "Renamed"
        assert [row["id"] for row in res.data["tags_detail"]] == [str(tag.id)]


def _ticket_updates(queries) -> list[str]:
    return [
        query["sql"].split(" WHERE ")[0]
        for query in queries
        if query["sql"].startswith('UPDATE "tickets_ticket"')
    ]


class TestBulkUpdate:
    def _bulk(self, client, ticket, **body):
        with CaptureQueriesContext(connection) as queries:
            res = client.post(
                BULK_URL, {"ids": [str(ticket.id)], **body}, format="json"
            )
        assert res.status_code == 200, res.data
        ticket.refresh_from_db()
        updates = _ticket_updates(queries)
        assert len(updates) == 1
        for field in ("title", "description", "requester_email", "requester_name"):
            assert f'"{field}"' not in updates[0], updates[0]
        return updates[0]

    def test_priority(self, authenticated_client, ticket):
        before = ticket.updated_at
        update = self._bulk(authenticated_client, ticket, priority="high")
        assert ticket.priority == "high"
        assert ticket.updated_at > before
        assert '"status"' not in update

    def test_status_resolved(self, authenticated_client, ticket):
        self._bulk(authenticated_client, ticket, status="resolved")
        assert ticket.status == "resolved"
        assert ticket.resolved_at is not None

    def test_status_closed(self, authenticated_client, ticket):
        self._bulk(authenticated_client, ticket, status="closed")
        assert ticket.status == "closed"
        assert ticket.closed_at is not None

    def test_status_open_clears_the_dates(self, authenticated_client, ticket):
        now = timezone.now()
        Ticket.objects.filter(pk=ticket.pk).update(resolved_at=now, closed_at=now)
        self._bulk(authenticated_client, ticket, status="open")
        assert ticket.status == "open"
        assert ticket.resolved_at is None
        assert ticket.closed_at is None

    def test_assigning(self, authenticated_client, ticket, agent):
        update = self._bulk(
            authenticated_client, ticket, assigned_agent_id=str(agent.id)
        )
        assert ticket.assigned_agent == agent
        assert ticket.first_response_at is not None
        assert '"status"' not in update

    def test_unassigning(self, authenticated_client, ticket, agent):
        Ticket.objects.filter(pk=ticket.pk).update(assigned_agent=agent)
        self._bulk(authenticated_client, ticket, assigned_agent_id=None)
        assert ticket.assigned_agent is None
