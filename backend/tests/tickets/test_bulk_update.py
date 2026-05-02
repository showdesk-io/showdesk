"""Tests for the ``/api/v1/tickets/bulk_update/`` action.

Lets agents apply a single update (status, priority, assigned agent) to
many tickets at once. The action is org-scoped: any IDs not belonging
to the active organization are silently dropped.
"""

import pytest
from rest_framework import status

from apps.tickets.models import Ticket
from tests.factories import OrganizationFactory, TicketFactory, UserFactory


URL = "/api/v1/tickets/bulk_update/"


@pytest.mark.django_db
class TestBulkUpdate:
    def test_resolves_a_batch_of_tickets(
        self, authenticated_client, organization
    ) -> None:
        tickets = TicketFactory.create_batch(
            3, organization=organization, status=Ticket.Status.IN_PROGRESS
        )
        response = authenticated_client.post(
            URL,
            {"ids": [str(t.id) for t in tickets], "status": "resolved"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["updated"] == 3
        for ticket in tickets:
            ticket.refresh_from_db()
            assert ticket.status == "resolved"
            assert ticket.resolved_at is not None

    def test_assigns_a_batch_to_an_agent(
        self, authenticated_client, organization
    ) -> None:
        tickets = TicketFactory.create_batch(2, organization=organization)
        agent = UserFactory(organization=organization, role="agent")

        response = authenticated_client.post(
            URL,
            {
                "ids": [str(t.id) for t in tickets],
                "assigned_agent_id": str(agent.id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        for ticket in tickets:
            ticket.refresh_from_db()
            assert ticket.assigned_agent_id == agent.id
            assert ticket.first_response_at is not None

    def test_explicit_null_agent_unassigns(
        self, authenticated_client, organization
    ) -> None:
        agent = UserFactory(organization=organization, role="agent")
        tickets = TicketFactory.create_batch(
            2, organization=organization, assigned_agent=agent
        )

        response = authenticated_client.post(
            URL,
            {
                "ids": [str(t.id) for t in tickets],
                "assigned_agent_id": None,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        for ticket in tickets:
            ticket.refresh_from_db()
            assert ticket.assigned_agent_id is None

    def test_silently_drops_ids_from_other_orgs(
        self, authenticated_client, organization
    ) -> None:
        mine = TicketFactory(organization=organization, status=Ticket.Status.OPEN)
        other_org = OrganizationFactory()
        theirs = TicketFactory(organization=other_org, status=Ticket.Status.OPEN)

        response = authenticated_client.post(
            URL,
            {"ids": [str(mine.id), str(theirs.id)], "status": "resolved"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["updated"] == 1

        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert mine.status == "resolved"
        assert theirs.status == "open"  # untouched

    def test_changing_priority_only_does_not_touch_status(
        self, authenticated_client, organization
    ) -> None:
        tickets = TicketFactory.create_batch(
            2, organization=organization, status=Ticket.Status.IN_PROGRESS
        )

        response = authenticated_client.post(
            URL,
            {"ids": [str(t.id) for t in tickets], "priority": "urgent"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        for ticket in tickets:
            ticket.refresh_from_db()
            assert ticket.priority == "urgent"
            assert ticket.status == "in_progress"

    def test_reopening_clears_lifecycle_timestamps(
        self, authenticated_client, organization
    ) -> None:
        tickets = TicketFactory.create_batch(
            2,
            organization=organization,
            status=Ticket.Status.RESOLVED,
        )
        # Backfill resolved_at so the reopen path has something to clear.
        for t in tickets:
            t.resolved_at = "2026-01-01T00:00:00Z"
            t.save(update_fields=["resolved_at"])

        response = authenticated_client.post(
            URL,
            {"ids": [str(t.id) for t in tickets], "status": "open"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        for ticket in tickets:
            ticket.refresh_from_db()
            assert ticket.status == "open"
            assert ticket.resolved_at is None
            assert ticket.closed_at is None

    def test_empty_ids_returns_400(self, authenticated_client) -> None:
        response = authenticated_client.post(
            URL, {"ids": [], "status": "resolved"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_update_fields_returns_400(
        self, authenticated_client, organization
    ) -> None:
        ticket = TicketFactory(organization=organization)
        response = authenticated_client.post(
            URL, {"ids": [str(ticket.id)]}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_status_returns_400(
        self, authenticated_client, organization
    ) -> None:
        ticket = TicketFactory(organization=organization)
        response = authenticated_client.post(
            URL,
            {"ids": [str(ticket.id)], "status": "not_a_status"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cross_org_agent_returns_400(
        self, authenticated_client, organization
    ) -> None:
        ticket = TicketFactory(organization=organization)
        other_org = OrganizationFactory()
        agent = UserFactory(organization=other_org, role="agent")

        response = authenticated_client.post(
            URL,
            {
                "ids": [str(ticket.id)],
                "assigned_agent_id": str(agent.id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
