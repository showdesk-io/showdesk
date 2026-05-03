"""Verifies that the live feature flags actually gate the endpoints
that depend on them. Pairs with ``test_feature_flags.py`` (which only
tests the resolver in isolation).

Each gate is exercised both ways: an org without the flag gets 403, an
org with the flag (via plan default OR per-tenant override) gets 200.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Plan
from tests.factories import (
    AdminFactory,
    OrganizationFactory,
    TicketFactory,
    UserFactory,
)


def _client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ── sla_policies (Cloud Business+) ──────────────────────────────────────


@pytest.mark.django_db
class TestSLAPolicyGate:
    URL = "/api/v1/sla-policies/"

    def test_free_plan_cannot_list(self):
        org = OrganizationFactory(plan=Plan.FREE)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).get(self.URL)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_business_plan_can_list(self):
        org = OrganizationFactory(plan=Plan.BUSINESS)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).get(self.URL)
        assert response.status_code == status.HTTP_200_OK

    def test_override_unlocks_for_free_plan(self):
        org = OrganizationFactory(
            plan=Plan.FREE, feature_flag_overrides={"sla_policies": True}
        )
        admin = AdminFactory(organization=org)
        response = _client_for(admin).get(self.URL)
        assert response.status_code == status.HTTP_200_OK

    def test_starter_plan_cannot_create(self):
        org = OrganizationFactory(plan=Plan.STARTER)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).post(
            self.URL,
            {
                "name": "Default urgent",
                "priority": "urgent",
                "first_response_minutes": 15,
                "resolution_minutes": 240,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ── bulk_actions (Cloud Starter+) ──────────────────────────────────────


@pytest.mark.django_db
class TestBulkActionsGate:
    URL = "/api/v1/tickets/bulk_update/"

    def test_free_plan_cannot_bulk_update(self):
        org = OrganizationFactory(plan=Plan.FREE)
        agent = UserFactory(organization=org, role="agent")
        ticket = TicketFactory(organization=org)
        response = _client_for(agent).post(
            self.URL,
            {"ids": [str(ticket.id)], "status": "resolved"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        ticket.refresh_from_db()
        assert ticket.status != "resolved"

    def test_starter_plan_can_bulk_update(self):
        org = OrganizationFactory(plan=Plan.STARTER)
        agent = UserFactory(organization=org, role="agent")
        tickets = TicketFactory.create_batch(2, organization=org)
        response = _client_for(agent).post(
            self.URL,
            {"ids": [str(t.id) for t in tickets], "status": "resolved"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["updated"] == 2


# ── custom_branding (Cloud Starter+) ────────────────────────────────────


@pytest.mark.django_db
class TestCustomBrandingGate:
    def _url(self, org_id) -> str:
        return f"/api/v1/organizations/{org_id}/"

    def test_free_plan_cannot_set_primary_color(self):
        org = OrganizationFactory(plan=Plan.FREE)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).patch(
            self._url(org.id),
            {"primary_color": "#FF00AA"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        org.refresh_from_db()
        assert org.primary_color == ""

    def test_free_plan_cannot_set_email_from_name(self):
        org = OrganizationFactory(plan=Plan.FREE)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).patch(
            self._url(org.id),
            {"email_from_name": "Acme Support"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_free_plan_can_still_edit_non_branding_fields(self):
        """Non-branding edits (e.g. widget_color) keep working on free."""
        org = OrganizationFactory(plan=Plan.FREE)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).patch(
            self._url(org.id),
            {"widget_color": "#123456"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.widget_color == "#123456"

    def test_starter_plan_can_set_primary_color(self):
        org = OrganizationFactory(plan=Plan.STARTER)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).patch(
            self._url(org.id),
            {"primary_color": "#FF00AA"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.primary_color == "#FF00AA"


# ── enabled_features lands on /organizations/ for the frontend gate ─────


@pytest.mark.django_db
class TestOrganizationSerializerExposesFeatures:
    def test_starter_plan_lists_enabled_features(self):
        org = OrganizationFactory(plan=Plan.STARTER)
        admin = AdminFactory(organization=org)
        response = _client_for(admin).get("/api/v1/organizations/")
        assert response.status_code == status.HTTP_200_OK
        row = response.data["results"][0]
        assert "bulk_actions" in row["enabled_features"]
        assert "custom_branding" in row["enabled_features"]
        assert "sla_policies" not in row["enabled_features"]
        assert row["plan"] == Plan.STARTER
