"""API tests for canned response endpoints."""

import pytest
from rest_framework import status

from tests.factories import (
    CannedResponseFactory,
    OrganizationFactory,
    UserFactory,
)


@pytest.mark.django_db
class TestCannedResponseAPI:
    """Tests for the /api/v1/canned-responses/ endpoint."""

    def test_create_personal_template(
        self, authenticated_client, organization, agent
    ) -> None:
        response = authenticated_client.post(
            "/api/v1/canned-responses/",
            {
                "name": "Greeting",
                "shortcut": "hello",
                "body": "Hi {{requester_name}}, thanks for reaching out!",
                "is_shared": False,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Greeting"
        assert response.data["shortcut"] == "hello"
        assert response.data["is_shared"] is False
        assert str(response.data["created_by"]) == str(agent.id)

    def test_create_shared_template(self, authenticated_client, organization) -> None:
        response = authenticated_client.post(
            "/api/v1/canned-responses/",
            {
                "name": "Resolved",
                "body": "We've fixed the issue.",
                "is_shared": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["is_shared"] is True

    def test_list_includes_shared_from_other_agents(
        self, authenticated_client, organization
    ) -> None:
        other_agent = UserFactory(organization=organization)
        CannedResponseFactory(
            organization=organization,
            created_by=other_agent,
            name="Shared Reply",
            is_shared=True,
        )
        response = authenticated_client.get("/api/v1/canned-responses/")
        assert response.data["count"] == 1
        assert response.data["results"][0]["name"] == "Shared Reply"

    def test_list_excludes_other_agents_personal_templates(
        self, authenticated_client, organization
    ) -> None:
        other_agent = UserFactory(organization=organization)
        CannedResponseFactory(
            organization=organization,
            created_by=other_agent,
            is_shared=False,
        )
        response = authenticated_client.get("/api/v1/canned-responses/")
        assert response.data["count"] == 0

    def test_list_excludes_other_org_templates(
        self, authenticated_client, organization
    ) -> None:
        other_org = OrganizationFactory()
        other_agent = UserFactory(organization=other_org)
        CannedResponseFactory(
            organization=other_org,
            created_by=other_agent,
            is_shared=True,
        )
        response = authenticated_client.get("/api/v1/canned-responses/")
        assert response.data["count"] == 0

    def test_update_own_template(
        self, authenticated_client, organization, agent
    ) -> None:
        tpl = CannedResponseFactory(
            organization=organization, created_by=agent, name="Old"
        )
        response = authenticated_client.patch(
            f"/api/v1/canned-responses/{tpl.id}/",
            {"name": "New"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "New"

    def test_cannot_update_other_agents_template(
        self, authenticated_client, organization
    ) -> None:
        other_agent = UserFactory(organization=organization)
        tpl = CannedResponseFactory(
            organization=organization,
            created_by=other_agent,
            is_shared=True,
        )
        response = authenticated_client.patch(
            f"/api/v1/canned-responses/{tpl.id}/",
            {"name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_own_template(
        self, authenticated_client, organization, agent
    ) -> None:
        tpl = CannedResponseFactory(organization=organization, created_by=agent)
        response = authenticated_client.delete(f"/api/v1/canned-responses/{tpl.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_duplicate_name_rejected(
        self, authenticated_client, organization, agent
    ) -> None:
        CannedResponseFactory(organization=organization, created_by=agent, name="Dup")
        response = authenticated_client.post(
            "/api/v1/canned-responses/",
            {"name": "Dup", "body": "..."},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_record_use_increments_counter(
        self, authenticated_client, organization, agent
    ) -> None:
        tpl = CannedResponseFactory(
            organization=organization, created_by=agent, body="Hi"
        )
        assert tpl.usage_count == 0
        response = authenticated_client.post(
            f"/api/v1/canned-responses/{tpl.id}/record-use/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["usage_count"] == 1
        response = authenticated_client.post(
            f"/api/v1/canned-responses/{tpl.id}/record-use/"
        )
        assert response.data["usage_count"] == 2

    def test_search_filters_by_name(
        self, authenticated_client, organization, agent
    ) -> None:
        CannedResponseFactory(
            organization=organization, created_by=agent, name="Greeting"
        )
        CannedResponseFactory(
            organization=organization, created_by=agent, name="Closing"
        )
        response = authenticated_client.get("/api/v1/canned-responses/?search=greet")
        assert response.data["count"] == 1
        assert response.data["results"][0]["name"] == "Greeting"
