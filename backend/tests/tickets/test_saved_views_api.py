"""API tests for saved views endpoints."""

import pytest
from rest_framework import status

from tests.factories import OrganizationFactory, SavedViewFactory, UserFactory


@pytest.mark.django_db
class TestSavedViewAPI:
    """Tests for the /api/v1/saved-views/ endpoint."""

    def test_create_saved_view(self, authenticated_client, organization, agent) -> None:
        """Agents can create a personal saved view."""
        response = authenticated_client.post(
            "/api/v1/saved-views/",
            {
                "name": "My Open Tickets",
                "filters": {"status": "open", "assigned_agent": str(agent.id)},
                "is_shared": False,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "My Open Tickets"
        assert response.data["filters"]["status"] == "open"
        assert response.data["is_shared"] is False
        assert str(response.data["created_by"]) == str(agent.id)

    def test_create_shared_view(self, authenticated_client, organization) -> None:
        """Agents can create a shared view visible to the org."""
        response = authenticated_client.post(
            "/api/v1/saved-views/",
            {
                "name": "Urgent Team Queue",
                "filters": {"priority": "urgent"},
                "is_shared": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["is_shared"] is True

    def test_list_own_views(self, authenticated_client, organization, agent) -> None:
        """Agents see their own personal views."""
        SavedViewFactory(organization=organization, created_by=agent, name="My View")
        response = authenticated_client.get("/api/v1/saved-views/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["name"] == "My View"

    def test_list_includes_shared_views(self, authenticated_client, organization, agent) -> None:
        """Agents see shared views from other agents in the same org."""
        other_agent = UserFactory(organization=organization)
        SavedViewFactory(
            organization=organization,
            created_by=other_agent,
            name="Shared Queue",
            is_shared=True,
        )
        response = authenticated_client.get("/api/v1/saved-views/")
        assert response.data["count"] == 1
        assert response.data["results"][0]["name"] == "Shared Queue"

    def test_list_excludes_other_agents_personal_views(
        self, authenticated_client, organization
    ) -> None:
        """Agents do NOT see other agents' personal views."""
        other_agent = UserFactory(organization=organization)
        SavedViewFactory(
            organization=organization,
            created_by=other_agent,
            name="Secret View",
            is_shared=False,
        )
        response = authenticated_client.get("/api/v1/saved-views/")
        assert response.data["count"] == 0

    def test_list_excludes_other_org_views(
        self, authenticated_client, organization
    ) -> None:
        """Agents don't see views from other organizations."""
        other_org = OrganizationFactory()
        other_agent = UserFactory(organization=other_org)
        SavedViewFactory(
            organization=other_org,
            created_by=other_agent,
            is_shared=True,
        )
        response = authenticated_client.get("/api/v1/saved-views/")
        assert response.data["count"] == 0

    def test_delete_own_view(self, authenticated_client, organization, agent) -> None:
        """Agents can delete their own views."""
        view = SavedViewFactory(organization=organization, created_by=agent)
        response = authenticated_client.delete(f"/api/v1/saved-views/{view.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_cannot_delete_other_agents_shared_view(
        self, authenticated_client, organization
    ) -> None:
        """Agents cannot delete shared views created by others."""
        other_agent = UserFactory(organization=organization)
        view = SavedViewFactory(
            organization=organization,
            created_by=other_agent,
            is_shared=True,
        )
        response = authenticated_client.delete(f"/api/v1/saved-views/{view.id}/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_update_own_view(self, authenticated_client, organization, agent) -> None:
        """Agents can update their own views."""
        view = SavedViewFactory(
            organization=organization,
            created_by=agent,
            name="Old Name",
        )
        response = authenticated_client.patch(
            f"/api/v1/saved-views/{view.id}/",
            {"name": "New Name"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "New Name"

    def test_cannot_update_other_agents_view(
        self, authenticated_client, organization
    ) -> None:
        """Agents cannot update views created by others."""
        other_agent = UserFactory(organization=organization)
        view = SavedViewFactory(
            organization=organization,
            created_by=other_agent,
            is_shared=True,
        )
        response = authenticated_client.patch(
            f"/api/v1/saved-views/{view.id}/",
            {"name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_duplicate_name_rejected(
        self, authenticated_client, organization, agent
    ) -> None:
        """Two views with the same name in the same org are rejected."""
        SavedViewFactory(
            organization=organization,
            created_by=agent,
            name="Duplicate",
        )
        response = authenticated_client.post(
            "/api/v1/saved-views/",
            {"name": "Duplicate", "filters": {"status": "open"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
