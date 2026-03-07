"""API tests for organization endpoints."""

import pytest
from rest_framework import status

from tests.factories import OrganizationFactory, UserFactory


@pytest.mark.django_db
class TestOrganizationAPI:
    """Tests for the /api/v1/organizations/ endpoint."""

    def test_list_organizations_authenticated(self, authenticated_client, organization) -> None:
        """Authenticated agents can list their organization."""
        response = authenticated_client.get("/api/v1/organizations/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    def test_list_organizations_unauthenticated(self, api_client) -> None:
        """Unauthenticated requests are rejected."""
        response = api_client.get("/api/v1/organizations/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_retrieve_organization(self, authenticated_client, organization) -> None:
        """Agents can retrieve their own organization."""
        response = authenticated_client.get(f"/api/v1/organizations/{organization.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == organization.name


@pytest.mark.django_db
class TestUserAPI:
    """Tests for the /api/v1/users/ endpoint."""

    def test_list_users(self, authenticated_client, agent) -> None:
        """Agents can list users in their organization."""
        response = authenticated_client.get("/api/v1/users/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] >= 1

    def test_create_user(self, admin_client, organization) -> None:
        """Admins can create new users."""
        response = admin_client.post("/api/v1/users/", {
            "email": "newagent@test.example",
            "password": "securepass123",
            "first_name": "New",
            "last_name": "Agent",
            "organization": str(organization.id),
            "role": "agent",
        })
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["email"] == "newagent@test.example"
