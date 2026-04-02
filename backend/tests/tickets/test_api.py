"""API tests for ticket endpoints."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status

from apps.tickets.models import Ticket
from apps.tickets.models import PriorityLevel
from tests.factories import (
    OrganizationFactory,
    PriorityLevelFactory,
    TagFactory,
    TicketFactory,
    UserFactory,
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

    def test_list_tickets_filters_by_organization(
        self, authenticated_client, organization
    ) -> None:
        """Agents only see tickets from their own organization."""
        TicketFactory.create_batch(2, organization=organization)
        other_org = OrganizationFactory()
        TicketFactory.create_batch(3, organization=other_org)
        response = authenticated_client.get("/api/v1/tickets/")
        assert response.data["count"] == 2

    def test_list_tickets_filter_by_status(
        self, authenticated_client, organization
    ) -> None:
        """Tickets can be filtered by status."""
        TicketFactory(organization=organization, status=Ticket.Status.OPEN)
        TicketFactory(organization=organization, status=Ticket.Status.RESOLVED)
        response = authenticated_client.get("/api/v1/tickets/?status=open")
        assert response.data["count"] == 1

    def test_list_tickets_filter_by_priority(
        self, authenticated_client, organization
    ) -> None:
        """Tickets can be filtered by priority."""
        TicketFactory(organization=organization, priority=Ticket.Priority.URGENT)
        TicketFactory(organization=organization, priority=Ticket.Priority.LOW)
        response = authenticated_client.get("/api/v1/tickets/?priority=urgent")
        assert response.data["count"] == 1

    def test_create_ticket(self, authenticated_client, organization) -> None:
        """Agents can create tickets."""
        response = authenticated_client.post(
            "/api/v1/tickets/",
            {
                "organization": str(organization.id),
                "title": "New test ticket",
                "description": "Testing ticket creation",
                "priority": "high",
            },
        )
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
        ticket = TicketFactory(
            organization=organization, status=Ticket.Status.IN_PROGRESS
        )
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

    def test_reopen_ticket(self, authenticated_client, organization) -> None:
        """Agents can reopen a resolved ticket."""
        ticket = TicketFactory(organization=organization, status=Ticket.Status.RESOLVED)
        response = authenticated_client.post(f"/api/v1/tickets/{ticket.id}/reopen/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "open"
        assert response.data["resolved_at"] is None
        assert response.data["closed_at"] is None

    def test_reopen_closed_ticket(self, authenticated_client, organization) -> None:
        """Agents can reopen a closed ticket."""
        ticket = TicketFactory(organization=organization, status=Ticket.Status.CLOSED)
        response = authenticated_client.post(f"/api/v1/tickets/{ticket.id}/reopen/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "open"

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
        response = authenticated_client.post(
            "/api/v1/messages/",
            {
                "ticket": str(ticket.id),
                "body": "Looking into this now.",
                "message_type": "reply",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["body"] == "Looking into this now."
        assert str(response.data["author"]) == str(agent.id)

    def test_create_internal_note(self, authenticated_client, organization) -> None:
        """Agents can create internal notes."""
        ticket = TicketFactory(organization=organization)
        response = authenticated_client.post(
            "/api/v1/messages/",
            {
                "ticket": str(ticket.id),
                "body": "This is a known issue from v2.1.",
                "message_type": "internal_note",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["message_type"] == "internal_note"


@pytest.mark.django_db
class TestTagAPI:
    """Tests for the /api/v1/tags/ endpoint."""

    def test_list_tags(self, authenticated_client, organization) -> None:
        """Agents can list tags in their organization."""
        TagFactory.create_batch(3, organization=organization)
        response = authenticated_client.get("/api/v1/tags/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 3

    def test_list_tags_filters_by_organization(
        self, authenticated_client, organization
    ) -> None:
        """Agents only see tags from their own organization."""
        TagFactory.create_batch(2, organization=organization)
        other_org = OrganizationFactory()
        TagFactory.create_batch(3, organization=other_org)
        response = authenticated_client.get("/api/v1/tags/")
        assert response.data["count"] == 2

    def test_create_tag(self, authenticated_client, organization) -> None:
        """Agents can create tags (org is auto-set)."""
        response = authenticated_client.post(
            "/api/v1/tags/",
            {
                "name": "Bug",
                "color": "#EF4444",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Bug"
        assert response.data["color"] == "#EF4444"
        assert str(response.data["organization"]) == str(organization.id)

    def test_update_tag(self, authenticated_client, organization) -> None:
        """Agents can update a tag."""
        tag = TagFactory(organization=organization, name="Old Name")
        response = authenticated_client.patch(
            f"/api/v1/tags/{tag.id}/",
            {"name": "New Name"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "New Name"

    def test_delete_tag(self, authenticated_client, organization) -> None:
        """Agents can delete a tag."""
        tag = TagFactory(organization=organization)
        response = authenticated_client.delete(f"/api/v1/tags/{tag.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_set_tags_on_ticket(self, authenticated_client, organization) -> None:
        """Agents can set tags on a ticket."""
        ticket = TicketFactory(organization=organization)
        tag1 = TagFactory(organization=organization, name="Bug")
        tag2 = TagFactory(organization=organization, name="Urgent")
        response = authenticated_client.post(
            f"/api/v1/tickets/{ticket.id}/set_tags/",
            {"tag_ids": [str(tag1.id), str(tag2.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        tag_names = [t["name"] for t in response.data["tags_detail"]]
        assert "Bug" in tag_names
        assert "Urgent" in tag_names

    def test_set_tags_replaces_existing(
        self, authenticated_client, organization
    ) -> None:
        """Setting tags replaces any existing tags."""
        tag1 = TagFactory(organization=organization, name="Old")
        tag2 = TagFactory(organization=organization, name="New")
        ticket = TicketFactory(organization=organization)
        ticket.tags.add(tag1)

        response = authenticated_client.post(
            f"/api/v1/tickets/{ticket.id}/set_tags/",
            {"tag_ids": [str(tag2.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        tag_names = [t["name"] for t in response.data["tags_detail"]]
        assert tag_names == ["New"]

    def test_filter_tickets_by_tag(self, authenticated_client, organization) -> None:
        """Tickets can be filtered by tag."""
        tag = TagFactory(organization=organization, name="Bug")
        ticket1 = TicketFactory(organization=organization)
        ticket1.tags.add(tag)
        TicketFactory(organization=organization)

        response = authenticated_client.get(f"/api/v1/tickets/?tags={tag.id}")
        assert response.data["count"] == 1


@pytest.mark.django_db
class TestAttachmentValidation:
    """Tests for file upload validation."""

    def test_reject_executable_file(self, authenticated_client, organization) -> None:
        """Executable files are rejected."""
        ticket = TicketFactory(organization=organization)
        exe_file = SimpleUploadedFile(
            "malware.exe", b"MZ\x90\x00", content_type="application/x-msdownload"
        )
        response = authenticated_client.post(
            "/api/v1/attachments/",
            {
                "ticket": str(ticket.id),
                "file": exe_file,
                "filename": "malware.exe",
                "content_type": "application/x-msdownload",
                "file_size": 4,
            },
            format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not allowed" in str(response.data).lower()

    def test_reject_oversized_file(
        self, authenticated_client, organization, monkeypatch
    ) -> None:
        """Files exceeding 20 MB are rejected."""
        from apps.tickets.serializers import TicketAttachmentSerializer

        # Lower the limit temporarily to avoid allocating 21 MB
        monkeypatch.setattr(TicketAttachmentSerializer, "MAX_FILE_SIZE", 10)

        ticket = TicketFactory(organization=organization)
        small_file = SimpleUploadedFile(
            "large.pdf", b"x" * 20, content_type="application/pdf"
        )

        response = authenticated_client.post(
            "/api/v1/attachments/",
            {
                "ticket": str(ticket.id),
                "file": small_file,
                "filename": "large.pdf",
                "content_type": "application/pdf",
                "file_size": 20,
            },
            format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit" in str(response.data).lower()

    @pytest.mark.django_db
    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_accept_valid_file(self, authenticated_client, organization) -> None:
        """Valid files are accepted."""
        ticket = TicketFactory(organization=organization)
        pdf_file = SimpleUploadedFile(
            "report.pdf", b"%PDF-1.4 test content", content_type="application/pdf"
        )
        response = authenticated_client.post(
            "/api/v1/attachments/",
            {
                "ticket": str(ticket.id),
                "file": pdf_file,
                "filename": "report.pdf",
                "content_type": "application/pdf",
                "file_size": pdf_file.size,
            },
            format="multipart",
        )
        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestPriorityLevelAPI:
    """Tests for the /api/v1/priorities/ endpoint."""

    def test_list_default_priorities(self, authenticated_client, organization) -> None:
        """Default priorities are seeded when an organization is created."""
        response = authenticated_client.get("/api/v1/priorities/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 4
        slugs = [p["slug"] for p in response.data["results"]]
        assert "low" in slugs
        assert "medium" in slugs
        assert "high" in slugs
        assert "urgent" in slugs

    def test_create_custom_priority(self, authenticated_client, organization) -> None:
        """Agents can create custom priority levels."""
        response = authenticated_client.post(
            "/api/v1/priorities/",
            {
                "name": "Blocker",
                "slug": "blocker",
                "color": "#DC2626",
                "position": 4,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Blocker"
        assert response.data["slug"] == "blocker"
        assert response.data["color"] == "#DC2626"
        assert str(response.data["organization"]) == str(organization.id)

    def test_update_priority_color(self, authenticated_client, organization) -> None:
        """Agents can update a priority level's color."""
        priority = PriorityLevel.objects.get(
            organization=organization,
            slug="high",
        )
        response = authenticated_client.patch(
            f"/api/v1/priorities/{priority.id}/",
            {"color": "#FF0000"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["color"] == "#FF0000"

    def test_delete_custom_priority(self, authenticated_client, organization) -> None:
        """Agents can delete a priority level."""
        priority = PriorityLevelFactory(
            organization=organization,
            name="Temporary",
            slug="temporary",
        )
        response = authenticated_client.delete(f"/api/v1/priorities/{priority.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_priorities_filtered_by_organization(
        self, authenticated_client, organization
    ) -> None:
        """Agents only see priorities from their own organization."""
        other_org = OrganizationFactory()
        PriorityLevelFactory(organization=other_org, slug="other-priority")
        response = authenticated_client.get("/api/v1/priorities/")
        # Only the 4 defaults from authenticated user's org
        assert response.data["count"] == 4

    def test_ticket_uses_custom_priority(
        self, authenticated_client, organization
    ) -> None:
        """Tickets can use custom priority slugs."""
        PriorityLevelFactory(
            organization=organization,
            name="Blocker",
            slug="blocker",
            position=4,
        )
        ticket = TicketFactory(organization=organization, priority="blocker")
        response = authenticated_client.get(f"/api/v1/tickets/{ticket.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["priority"] == "blocker"
