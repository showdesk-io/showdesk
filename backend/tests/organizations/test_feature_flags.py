"""Tests for the per-tenant plan + feature-flag plumbing.

Covers:
  - Organization.has_feature() resolves plan defaults
  - feature_flag_overrides flips individual flags on/off regardless of plan
  - Platform admin can PATCH the plan + override map
  - PlatformOrganizationDetailSerializer surfaces ``enabled_features``
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Plan
from tests.factories import OrganizationFactory, UserFactory


@pytest.fixture
def superuser_client():
    org = OrganizationFactory()
    su = UserFactory(organization=org, role="admin", is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=su)
    return client


@pytest.mark.django_db
class TestHasFeature:
    def test_free_plan_locks_premium_features(self):
        org = OrganizationFactory(plan=Plan.FREE)
        assert org.has_feature("bulk_actions") is False
        assert org.has_feature("sla_policies") is False

    def test_starter_plan_unlocks_starter_features(self):
        org = OrganizationFactory(plan=Plan.STARTER)
        assert org.has_feature("bulk_actions") is True
        assert org.has_feature("custom_branding") is True
        # Business+ remains gated
        assert org.has_feature("sla_policies") is False
        assert org.has_feature("audit_log") is False

    def test_business_plan_unlocks_sla_and_ai(self):
        org = OrganizationFactory(plan=Plan.BUSINESS)
        assert org.has_feature("sla_policies") is True
        assert org.has_feature("ai_categorization") is True
        # Enterprise-only remains gated
        assert org.has_feature("audit_log") is False
        assert org.has_feature("sso") is False

    def test_enterprise_unlocks_everything(self):
        org = OrganizationFactory(plan=Plan.ENTERPRISE)
        assert org.has_feature("audit_log") is True
        assert org.has_feature("sso") is True
        assert org.has_feature("sla_policies") is True

    def test_override_unlocks_for_lower_plan(self):
        org = OrganizationFactory(
            plan=Plan.FREE,
            feature_flag_overrides={"sla_policies": True},
        )
        assert org.has_feature("sla_policies") is True

    def test_override_locks_a_plan_default(self):
        """Per-tenant kill-switch: business org with sla_policies disabled."""
        org = OrganizationFactory(
            plan=Plan.BUSINESS,
            feature_flag_overrides={"sla_policies": False},
        )
        assert org.has_feature("sla_policies") is False
        # Other business defaults still on.
        assert org.has_feature("ai_categorization") is True

    def test_unknown_flag_resolves_false(self):
        org = OrganizationFactory(plan=Plan.ENTERPRISE)
        assert org.has_feature("does_not_exist") is False

    def test_enabled_features_lists_active_set(self):
        org = OrganizationFactory(
            plan=Plan.STARTER,
            feature_flag_overrides={"sla_policies": True, "custom_branding": False},
        )
        # bulk_actions kept (starter default), custom_branding disabled,
        # sla_policies added.
        assert org.enabled_features() == {"bulk_actions", "sla_policies"}


@pytest.mark.django_db
class TestPlatformAdminEditsFlags:
    def test_admin_can_patch_plan(self, superuser_client):
        org = OrganizationFactory(plan=Plan.FREE)
        response = superuser_client.patch(
            f"/api/v1/platform/organizations/{org.id}/",
            {"plan": Plan.BUSINESS},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.plan == Plan.BUSINESS

    def test_admin_can_patch_feature_flag_overrides(self, superuser_client):
        org = OrganizationFactory(plan=Plan.STARTER)
        response = superuser_client.patch(
            f"/api/v1/platform/organizations/{org.id}/",
            {"feature_flag_overrides": {"ai_categorization": True}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.feature_flag_overrides == {"ai_categorization": True}
        assert org.has_feature("ai_categorization") is True

    def test_detail_response_exposes_enabled_features(self, superuser_client):
        org = OrganizationFactory(plan=Plan.BUSINESS)
        response = superuser_client.get(f"/api/v1/platform/organizations/{org.id}/")
        assert response.status_code == status.HTTP_200_OK
        # Default business features are exposed; sorted by the serializer.
        features = response.data["enabled_features"]
        assert "sla_policies" in features
        assert "ai_categorization" in features
        assert "audit_log" not in features

    def test_non_superuser_cannot_patch_flags(self, authenticated_client):
        org = OrganizationFactory()
        response = authenticated_client.patch(
            f"/api/v1/platform/organizations/{org.id}/",
            {"plan": Plan.ENTERPRISE},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        org.refresh_from_db()
        assert org.plan != Plan.ENTERPRISE
