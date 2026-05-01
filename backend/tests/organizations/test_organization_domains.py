"""Tests for OrganizationDomain model + CRUD API.

Verification flow (DNS challenge, admin_email auto-verify, ownership
transfer) is covered separately in PR 3 — these tests only check the
data model invariants and the basic CRUD endpoints exposed in PR 2.
"""

import pytest
from django.db import IntegrityError, transaction
from rest_framework import status

from apps.organizations.models import OrganizationDomain
from tests.factories import AdminFactory, OrganizationFactory


@pytest.mark.django_db
class TestOrganizationDomainModel:
    def test_at_least_one_purpose_required(self, organization) -> None:
        """The CHECK constraint forbids rows with neither purpose set."""
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OrganizationDomain.objects.create(
                    organization=organization,
                    domain="acme.com",
                    is_branding=False,
                    is_email_routing=False,
                )

    def test_unique_per_org(self, organization) -> None:
        OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OrganizationDomain.objects.create(
                    organization=organization,
                    domain="acme.com",
                    is_branding=True,
                )

    def test_one_verified_per_domain_globally(self) -> None:
        """At most one verified row exists per domain across all orgs."""
        org_a = OrganizationFactory(slug="a")
        org_b = OrganizationFactory(slug="b")
        OrganizationDomain.objects.create(
            organization=org_a,
            domain="shared.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.VERIFIED,
            verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OrganizationDomain.objects.create(
                    organization=org_b,
                    domain="shared.com",
                    is_email_routing=True,
                    status=OrganizationDomain.Status.VERIFIED,
                    verification_method=OrganizationDomain.VerificationMethod.DNS_TXT,
                )

    def test_pending_can_coexist_across_orgs(self) -> None:
        """Pending rows for the same domain can exist on multiple orgs —
        that's how Org B starts a DNS challenge while Org A still holds it."""
        org_a = OrganizationFactory(slug="a")
        org_b = OrganizationFactory(slug="b")
        OrganizationDomain.objects.create(
            organization=org_a,
            domain="contested.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.VERIFIED,
            verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
        )
        # Org B opens a pending claim — should succeed.
        OrganizationDomain.objects.create(
            organization=org_b,
            domain="contested.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.PENDING,
            verification_method=OrganizationDomain.VerificationMethod.DNS_TXT,
        )
        assert (
            OrganizationDomain.objects.filter(domain="contested.com").count() == 2
        )

    def test_txt_record_helpers(self, organization) -> None:
        domain = OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
            verification_token="abc123",
        )
        assert domain.txt_record_name == "_showdesk.acme.com"
        assert domain.txt_record_value == "showdesk-verification=abc123"

    def test_generate_token_unique(self) -> None:
        tokens = {OrganizationDomain.generate_token() for _ in range(20)}
        assert len(tokens) == 20  # extremely high probability — sanity check
        for t in tokens:
            assert len(t) == 32
            assert all(c in "0123456789abcdef" for c in t)


@pytest.mark.django_db
class TestOrganizationDomainAPI:
    def test_admin_lists_own_org_domains(
        self, admin_client, organization
    ) -> None:
        OrganizationDomain.objects.create(
            organization=organization,
            domain="mine.com",
            is_email_routing=True,
        )
        other_org = OrganizationFactory(slug="other")
        OrganizationDomain.objects.create(
            organization=other_org,
            domain="leak.com",
            is_email_routing=True,
        )
        response = admin_client.get("/api/v1/organization-domains/")
        assert response.status_code == status.HTTP_200_OK
        domains = [r["domain"] for r in response.data["results"]]
        assert "mine.com" in domains
        assert "leak.com" not in domains

    def test_admin_creates_branding_domain(
        self, admin_client, organization
    ) -> None:
        response = admin_client.post(
            "/api/v1/organization-domains/",
            {"domain": "ACME.COM", "is_branding": True},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["domain"] == "acme.com"  # lowercased
        assert response.data["status"] == "pending"
        domain = OrganizationDomain.objects.get(domain="acme.com")
        assert domain.organization == organization

    def test_create_requires_at_least_one_purpose(
        self, admin_client
    ) -> None:
        response = admin_client.post(
            "/api/v1/organization-domains/",
            {"domain": "acme.com"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_rejects_invalid_domain(self, admin_client) -> None:
        response = admin_client.post(
            "/api/v1/organization-domains/",
            {"domain": "not a domain", "is_branding": True},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "domain" in response.data

    def test_agent_cannot_create(
        self, authenticated_client, organization
    ) -> None:
        response = authenticated_client.post(
            "/api/v1/organization-domains/",
            {"domain": "acme.com", "is_branding": True},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_toggle_purposes(
        self, admin_client, organization
    ) -> None:
        d = OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        response = admin_client.patch(
            f"/api/v1/organization-domains/{d.id}/",
            {"is_branding": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        d.refresh_from_db()
        assert d.is_branding is True
        assert d.is_email_routing is True

    def test_domain_field_is_immutable(
        self, admin_client, organization
    ) -> None:
        d = OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        response = admin_client.patch(
            f"/api/v1/organization-domains/{d.id}/",
            {"domain": "different.com"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_status_and_token_are_read_only(
        self, admin_client, organization
    ) -> None:
        """The client cannot set status=verified or pick a token."""
        response = admin_client.post(
            "/api/v1/organization-domains/",
            {
                "domain": "acme.com",
                "is_branding": True,
                "status": "verified",
                "verification_token": "ZZZ",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        d = OrganizationDomain.objects.get(domain="acme.com")
        assert d.status == "pending"
        assert d.verification_token == ""

    def test_admin_can_delete(self, admin_client, organization) -> None:
        d = OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        response = admin_client.delete(
            f"/api/v1/organization-domains/{d.id}/"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not OrganizationDomain.objects.filter(id=d.id).exists()

    def test_unauthenticated_cannot_list(self, api_client) -> None:
        response = api_client.get("/api/v1/organization-domains/")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_create_response_includes_txt_record_helpers(
        self, admin_client
    ) -> None:
        response = admin_client.post(
            "/api/v1/organization-domains/",
            {"domain": "acme.com", "is_branding": True},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["txt_record_name"] == "_showdesk.acme.com"
        # Token is empty until DNS verification is requested (PR 3).
        assert response.data["txt_record_value"] == "showdesk-verification="


@pytest.mark.django_db
class TestSuperuserAccess:
    def test_superuser_with_org_can_manage_domains(self) -> None:
        from rest_framework.test import APIClient
        from apps.organizations.models import User

        org = OrganizationFactory(slug="su-org")
        su = AdminFactory(organization=org, is_superuser=True, role=User.Role.AGENT)
        client = APIClient()
        client.force_authenticate(user=su)
        response = client.post(
            "/api/v1/organization-domains/",
            {"domain": "acme.com", "is_branding": True},
            format="json",
        )
        # Superusers bypass the admin role check.
        assert response.status_code == status.HTTP_201_CREATED, response.data
