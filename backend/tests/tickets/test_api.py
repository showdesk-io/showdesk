"""API tests for ticket endpoints."""

import pytest
from rest_framework import status

from apps.tickets.models import Ticket
from tests.factories import (
    OrganizationFactory,
    TicketFactory,
    UserFactory,
    EndUserFactory,
)


@pytest.mark.django_db
class TestTicketAPI:
    """Tests for the /api/v1/tickets/ endpoint."""

    def test_list_tickets(self, authenticated_client, organization) -> None:
        """Agents can list tickets in their organization."""
        TicketFactory.create_batch(3, organization=organization)
        response = authenticated_client.get("/api/v1/tickets/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 3

    def test_list_tickets_filters_by_organization(self, authenticated_client, organization) -> None:
        """Agents only see tickets from their own organization."""
        TicketFactory.create_batch(2, organization=organization)
        other_org = OrganizationFactory()
        TicketFactory.create_batch(3, organization=other_org)
        response = authenticated_client.get("/api/v1/tickets/")
        assert response.data["count"] == 2

    def test_list_tickets_filter_by_status(self, authenticated_client, organization) -> None:
        """Tickets can be filtered by status."""
        TicketFactory(organization=organization, status=Ticket.Status.OPEN)
        TicketFactory(organization=organization, status=Ticket.Status.RESOLVED)
        response = authenticated_client.get("/api/v1/tickets/?status=open")
        assert response.data["count"] == 1

    def test_list_tickets_filter_by_priority(self, authenticated_client, organization) -> None:
        """Tickets can be filtered by priority."""
        TicketFactory(organization=organization, priority=Ticket.Priority.URGENT)
        TicketFactory(organization=organization, priority=Ticket.Priority.LOW)
        response = authenticated_client.get("/api/v1/tickets/?priority=urgent")
        assert response.data["count"] == 1

    def test_create_ticket(self, authenticated_client, organization) -> None:
        """Agents can create tickets."""
        response = authenticated_client.post("/api/v1/tickets/", {
            "organization": str(organization.id),
            "title": "New test ticket",
            "description": "Testing ticket creation",
            "priority": "high",
        })
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["title"] == "New test ticket"
        assert response.data["reference"].startswith("SD-")

    def test_retrieve_ticket(self, authenticated_client, organization) -> None:
        """Agents can retrieve a ticket by ID."""
        ticket = TicketFactory(organization=organization)
        response = authenticated_client.get(f"/api/v1/tickets/{ticket.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["reference"] == ticket.reference

    def test_search_tickets(self, authenticated_client, organization) -> None:
        """Tickets can be searched by title."""
        TicketFactory(organization=organization, title="Login page broken")
        TicketFactory(organization=organization, title="Payment issue")
        response = authenticated_client.get("/api/v1/tickets/?search=login")
        assert response.data["count"] == 1

    def test_resolve_ticket(self, authenticated_client, organization) -> None:
        """Agents can resolve a ticket."""
        ticket = TicketFactory(organization=organization, status=Ticket.Status.IN_PROGRESS)
        response = authenticated_client.post(f"/api/v1/tickets/{ticket.id}/resolve/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "resolved"
        assert response.data["resolved_at"] is not None

    def test_close_ticket(self, authenticated_client, organization) -> None:
        """Agents can close a ticket."""
        ticket = TicketFactory(organization=organization, status=Ticket.Status.RESOLVED)
        response = authenticated_client.post(f"/api/v1/tickets/{ticket.id}/close/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "closed"
        assert response.data["closed_at"] is not None

    def test_assign_ticket(self, authenticated_client, organization) -> None:
        """Agents can assign a ticket."""
        ticket = TicketFactory(organization=organization)
        agent = UserFactory(organization=organization, role="agent")
        response = authenticated_client.post(
            f"/api/v1/tickets/{ticket.id}/assign/",
            {"agent_id": str(agent.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "in_progress"

    def test_unauthenticated_access_denied(self, api_client) -> None:
        """Unauthenticated requests are rejected."""
        response = api_client.get("/api/v1/tickets/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestWidgetSubmit:
    """Tests for the widget ticket submission endpoint."""

    def test_widget_submit_success(self, api_client, organization) -> None:
        """Widget can submit a ticket with a valid token."""
        response = api_client.post(
            "/api/v1/tickets/widget_submit/",
            {
                "title": "Button does not work",
                "description": "The submit button is unresponsive on mobile.",
                "requester_name": "Jane Doe",
                "requester_email": "jane@customer.example",
                "priority": "high",
                "context_url": "https://app.example.com/form",
                "context_browser": "Safari",
                "context_os": "iOS",
                "context_screen_resolution": "375x812",
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["reference"].startswith("SD-")
        assert response.data["source"] == "widget"
        assert response.data["requester_email"] == "jane@customer.example"

    def test_widget_submit_missing_token(self, api_client) -> None:
        """Widget submit fails without a token."""
        response = api_client.post(
            "/api/v1/tickets/widget_submit/",
            {"title": "Test"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_widget_submit_invalid_token(self, api_client) -> None:
        """Widget submit fails with an invalid token."""
        response = api_client.post(
            "/api/v1/tickets/widget_submit/",
            {"title": "Test"},
            format="json",
            HTTP_X_WIDGET_TOKEN="00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_widget_submit_inactive_org(self, api_client) -> None:
        """Widget submit fails for inactive organizations."""
        org = OrganizationFactory(is_active=False)
        response = api_client.post(
            "/api/v1/tickets/widget_submit/",
            {"title": "Test", "requester_name": "X", "requester_email": "x@x.com"},
            format="json",
            HTTP_X_WIDGET_TOKEN=str(org.api_token),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestTicketMessageAPI:
    """Tests for the /api/v1/messages/ endpoint."""

    def test_create_reply(self, authenticated_client, organization, agent) -> None:
        """Agents can reply to a ticket."""
        ticket = TicketFactory(organization=organization)
        response = authenticated_client.post("/api/v1/messages/", {
            "ticket": str(ticket.id),
            "body": "Looking into this now.",
            "message_type": "reply",
        })
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["body"] == "Looking into this now."
        assert response.data["author"] == str(agent.id)

    def test_create_internal_note(self, authenticated_client, organization) -> None:
        """Agents can create internal notes."""
        ticket = TicketFactory(organization=organization)
        response = authenticated_client.post("/api/v1/messages/", {
            "ticket": str(ticket.id),
            "body": "This is a known issue from v2.1.",
            "message_type": "internal_note",
        })
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["message_type"] == "internal_note"
