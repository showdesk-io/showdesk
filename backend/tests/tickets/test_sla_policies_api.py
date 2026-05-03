"""Tests for /api/v1/sla-policies/ CRUD."""

import pytest
from rest_framework import status

from apps.tickets.models import SLAPolicy
from tests.factories import OrganizationFactory, SLAPolicyFactory


URL = "/api/v1/sla-policies/"


@pytest.mark.django_db
class TestSLAPolicyAPI:
    def test_admin_lists_only_own_org_policies(
        self, admin_client, organization
    ) -> None:
        SLAPolicyFactory(organization=organization, priority="urgent")
        other_org = OrganizationFactory()
        SLAPolicyFactory(organization=other_org, priority="urgent")

        response = admin_client.get(URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    def test_agent_can_read(self, authenticated_client, organization) -> None:
        SLAPolicyFactory(organization=organization, priority="high")
        response = authenticated_client.get(URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    def test_admin_can_create(self, admin_client) -> None:
        response = admin_client.post(
            URL,
            {
                "name": "Default urgent",
                "priority": "urgent",
                "first_response_minutes": 15,
                "resolution_minutes": 240,
                "is_active": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["priority"] == "urgent"
        assert SLAPolicy.objects.count() == 1

    def test_agent_cannot_create(self, authenticated_client) -> None:
        response = authenticated_client.post(
            URL,
            {
                "name": "Sneaky",
                "priority": "low",
                "first_response_minutes": 60,
                "resolution_minutes": 1440,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert SLAPolicy.objects.count() == 0

    def test_unique_per_priority(self, admin_client, organization) -> None:
        SLAPolicyFactory(organization=organization, priority="medium")
        response = admin_client.post(
            URL,
            {
                "name": "Duplicate medium",
                "priority": "medium",
                "first_response_minutes": 30,
                "resolution_minutes": 720,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "priority" in response.data

    def test_admin_can_update(self, admin_client, organization) -> None:
        sla = SLAPolicyFactory(
            organization=organization,
            priority="high",
            first_response_minutes=60,
            resolution_minutes=480,
        )
        response = admin_client.patch(
            f"{URL}{sla.id}/",
            {"first_response_minutes": 30, "is_active": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        sla.refresh_from_db()
        assert sla.first_response_minutes == 30
        assert sla.is_active is False

    def test_agent_cannot_update(self, authenticated_client, organization) -> None:
        sla = SLAPolicyFactory(organization=organization, priority="urgent")
        response = authenticated_client.patch(
            f"{URL}{sla.id}/",
            {"first_response_minutes": 5},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_delete(self, admin_client, organization) -> None:
        sla = SLAPolicyFactory(organization=organization, priority="low")
        response = admin_client.delete(f"{URL}{sla.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert SLAPolicy.objects.count() == 0

    def test_cross_org_policy_not_visible(self, admin_client) -> None:
        other_org = OrganizationFactory()
        sla = SLAPolicyFactory(organization=other_org, priority="urgent")
        response = admin_client.get(f"{URL}{sla.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
