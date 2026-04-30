"""API tests for organization endpoints."""

import pytest
from rest_framework import status

from apps.organizations.models import User
from tests.factories import UserFactory


@pytest.mark.django_db
class TestOrganizationAPI:
    """Tests for the /api/v1/organizations/ endpoint."""

    def test_list_organizations_authenticated(
        self, authenticated_client, organization
    ) -> None:
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

    def test_retrieve_organization_has_api_token(
        self, authenticated_client, organization
    ) -> None:
        """Organization response includes api_token."""
        response = authenticated_client.get(f"/api/v1/organizations/{organization.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert "api_token" in response.data

    def test_regenerate_token_as_admin(self, admin_client, organization) -> None:
        """Admins can regenerate the API token."""
        old_token = str(organization.api_token)
        response = admin_client.post(
            f"/api/v1/organizations/{organization.id}/regenerate_token/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["api_token"] != old_token

    def test_regenerate_token_as_agent_forbidden(
        self, authenticated_client, organization
    ) -> None:
        """Non-admin agents cannot regenerate the API token."""
        response = authenticated_client.post(
            f"/api/v1/organizations/{organization.id}/regenerate_token/"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestUserAPI:
    """Tests for the /api/v1/users/ endpoint."""

    def test_list_users(self, authenticated_client, agent) -> None:
        """Agents can list users in their organization."""
        response = authenticated_client.get("/api/v1/users/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] >= 1

    def test_me_endpoint(self, authenticated_client, agent) -> None:
        """Agents can get their own profile via /me/."""
        response = authenticated_client.get("/api/v1/users/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == agent.email

    def test_filter_users_by_role(self, admin_client, organization) -> None:
        """Users can be filtered by role."""
        UserFactory(organization=organization, role=User.Role.AGENT)
        UserFactory(organization=organization, role=User.Role.END_USER)
        response = admin_client.get("/api/v1/users/?role=end_user")
        assert response.status_code == status.HTTP_200_OK
        for user in response.data["results"]:
            assert user["role"] == "end_user"

    def test_invite_agent_as_admin(self, admin_client, organization) -> None:
        """Admins can invite new agents via the invite endpoint."""
        response = admin_client.post(
            "/api/v1/users/invite/",
            {
                "email": "newagent@test.example",
                "first_name": "New",
                "last_name": "Agent",
                "role": "agent",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["email"] == "newagent@test.example"
        # Verify user has unusable password (OTP auth)
        user = User.objects.get(email="newagent@test.example")
        assert not user.has_usable_password()

    def test_invite_agent_as_agent_forbidden(self, authenticated_client) -> None:
        """Non-admin agents cannot invite users."""
        response = authenticated_client.post(
            "/api/v1/users/invite/",
            {
                "email": "blocked@test.example",
                "first_name": "Blocked",
                "last_name": "User",
            },
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_invite_duplicate_email_rejected(self, admin_client, agent) -> None:
        """Inviting an existing email returns 409 with explicit code."""
        response = admin_client.post(
            "/api/v1/users/invite/",
            {
                "email": agent.email,
                "first_name": "Dup",
                "last_name": "Agent",
            },
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "email_taken"

    def test_toggle_active_as_admin(
        self, admin_client, organization, admin_user
    ) -> None:
        """Admins can deactivate another user."""
        target = UserFactory(
            organization=organization, role=User.Role.AGENT, is_active=True
        )
        response = admin_client.post(f"/api/v1/users/{target.id}/toggle_active/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_active"] is False
        # Toggle back
        response = admin_client.post(f"/api/v1/users/{target.id}/toggle_active/")
        assert response.data["is_active"] is True

    def test_toggle_active_self_forbidden(self, admin_client, admin_user) -> None:
        """Admins cannot deactivate themselves."""
        response = admin_client.post(f"/api/v1/users/{admin_user.id}/toggle_active/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_toggle_active_as_agent_forbidden(
        self, authenticated_client, organization
    ) -> None:
        """Non-admin agents cannot toggle user status."""
        target = UserFactory(organization=organization, role=User.Role.AGENT)
        response = authenticated_client.post(
            f"/api/v1/users/{target.id}/toggle_active/"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
