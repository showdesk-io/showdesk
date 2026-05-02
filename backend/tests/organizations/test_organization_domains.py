"""Tests for OrganizationDomain model + CRUD + verification API.

Covers:
  - model invariants (constraints, helpers)
  - basic CRUD endpoints (admin gating, tenant scoping)
  - admin_email auto-verify path at create time
  - DNS challenge: token generation, verify endpoint, regenerate-token
  - ownership transfer when a competing org wins the DNS challenge

DNS lookups are mocked at the `query_txt_records` boundary — never
hit the network from tests.
"""

from unittest.mock import patch

import pytest
from django.core import mail
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import OrganizationDomain, User
from apps.organizations import services
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
        assert OrganizationDomain.objects.filter(domain="contested.com").count() == 2

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
    def test_admin_lists_own_org_domains(self, admin_client, organization) -> None:
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

    def test_admin_creates_branding_domain(self, admin_client, organization) -> None:
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

    def test_create_requires_at_least_one_purpose(self, admin_client) -> None:
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

    def test_agent_cannot_create(self, authenticated_client, organization) -> None:
        response = authenticated_client.post(
            "/api/v1/organization-domains/",
            {"domain": "acme.com", "is_branding": True},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_toggle_purposes(self, admin_client, organization) -> None:
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

    def test_domain_field_is_immutable(self, admin_client, organization) -> None:
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

    def test_status_and_token_are_read_only(self, admin_client, organization) -> None:
        """The client cannot set status=verified or pick a token directly."""
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
        # Default DNS challenge: status pending, server-generated token.
        assert d.status == "pending"
        assert d.verification_token != ""
        assert d.verification_token != "ZZZ"

    def test_admin_can_delete(self, admin_client, organization) -> None:
        d = OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        response = admin_client.delete(f"/api/v1/organization-domains/{d.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not OrganizationDomain.objects.filter(id=d.id).exists()

    def test_unauthenticated_cannot_list(self, api_client) -> None:
        response = api_client.get("/api/v1/organization-domains/")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_create_response_includes_txt_record_helpers(self, admin_client) -> None:
        response = admin_client.post(
            "/api/v1/organization-domains/",
            {"domain": "acme.com", "is_branding": True},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["txt_record_name"] == "_showdesk.acme.com"
        # Default-DNS create generates a token immediately.
        token = response.data["verification_token"]
        assert token
        assert response.data["txt_record_value"] == f"showdesk-verification={token}"


@pytest.mark.django_db
class TestSuperuserAccess:
    def test_superuser_with_org_can_manage_domains(self) -> None:
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


@pytest.mark.django_db
class TestAdminEmailAutoVerify:
    def test_create_with_admin_email_succeeds_for_matching_admin(
        self, organization
    ) -> None:
        admin = AdminFactory(
            organization=organization,
            email="founder@acme.com",
            is_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            "/api/v1/organization-domains/",
            {
                "domain": "acme.com",
                "is_email_routing": True,
                "verification_method": "admin_email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["status"] == "verified"
        assert response.data["verification_method"] == "admin_email"
        d = OrganizationDomain.objects.get(domain="acme.com")
        assert d.verified_at is not None

    def test_admin_email_refused_when_no_eligible_admin(self, organization) -> None:
        admin = AdminFactory(
            organization=organization,
            email="founder@other.com",
            is_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            "/api/v1/organization-domains/",
            {
                "domain": "acme.com",
                "is_email_routing": True,
                "verification_method": "admin_email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "cannot_autoverify"

    def test_admin_email_refused_when_admin_not_yet_verified(
        self, organization
    ) -> None:
        admin = AdminFactory(
            organization=organization,
            email="founder@acme.com",
            is_verified=False,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            "/api/v1/organization-domains/",
            {
                "domain": "acme.com",
                "is_email_routing": True,
                "verification_method": "admin_email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "cannot_autoverify"

    def test_admin_email_refused_when_already_verified_elsewhere(
        self, organization
    ) -> None:
        other = OrganizationFactory(slug="other")
        OrganizationDomain.objects.create(
            organization=other,
            domain="acme.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.VERIFIED,
            verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
        )
        admin = AdminFactory(
            organization=organization,
            email="founder@acme.com",
            is_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            "/api/v1/organization-domains/",
            {
                "domain": "acme.com",
                "is_email_routing": True,
                "verification_method": "admin_email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert response.data.get("code") == "use_dns_instead", response.data

    def test_admin_email_refused_for_public_webmail(self, organization) -> None:
        admin = AdminFactory(
            organization=organization,
            email="founder@gmail.com",
            is_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            "/api/v1/organization-domains/",
            {
                "domain": "gmail.com",
                "is_email_routing": True,
                "verification_method": "admin_email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "cannot_autoverify"


@pytest.mark.django_db
class TestDNSVerification:
    def test_create_with_dns_method_generates_token(self, admin_client) -> None:
        response = admin_client.post(
            "/api/v1/organization-domains/",
            {
                "domain": "acme.com",
                "is_branding": True,
                "verification_method": "dns_txt",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        token = response.data["verification_token"]
        assert token and len(token) == 32

    def test_verify_promotes_pending_to_verified_on_dns_hit(
        self, admin_client, organization
    ) -> None:
        d = services.start_dns_challenge(
            organization=organization,
            domain="acme.com",
            is_branding=True,
        )
        with patch(
            "apps.organizations.services.verify_domain_dns",
            return_value=True,
        ):
            response = admin_client.post(f"/api/v1/organization-domains/{d.id}/verify/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "verified"
        d.refresh_from_db()
        assert d.verified_at is not None
        assert d.last_check_at is not None

    def test_verify_returns_still_pending_when_txt_missing(
        self, admin_client, organization
    ) -> None:
        d = services.start_dns_challenge(
            organization=organization,
            domain="acme.com",
            is_branding=True,
        )
        with patch(
            "apps.organizations.services.verify_domain_dns",
            return_value=False,
        ):
            response = admin_client.post(f"/api/v1/organization-domains/{d.id}/verify/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data["code"] == "still_pending"
        d.refresh_from_db()
        assert d.status == OrganizationDomain.Status.PENDING
        assert d.last_check_at is not None

    def test_verify_idempotent_on_already_verified(
        self, admin_client, organization
    ) -> None:
        d = OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.VERIFIED,
            verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
        )
        response = admin_client.post(f"/api/v1/organization-domains/{d.id}/verify/")
        assert response.status_code == status.HTTP_200_OK

    def test_regenerate_token_resets_to_pending(
        self, admin_client, organization
    ) -> None:
        d = services.start_dns_challenge(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        old_token = d.verification_token
        response = admin_client.post(
            f"/api/v1/organization-domains/{d.id}/regenerate-token/"
        )
        assert response.status_code == status.HTTP_200_OK
        d.refresh_from_db()
        assert d.verification_token != old_token
        assert d.status == OrganizationDomain.Status.PENDING

    def test_regenerate_refused_on_verified_row(
        self, admin_client, organization
    ) -> None:
        d = OrganizationDomain.objects.create(
            organization=organization,
            domain="acme.com",
            is_branding=True,
            status=OrganizationDomain.Status.VERIFIED,
            verification_method=OrganizationDomain.VerificationMethod.DNS_TXT,
            verification_token="oldtoken",
        )
        response = admin_client.post(
            f"/api/v1/organization-domains/{d.id}/regenerate-token/"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "already_verified"

    def test_agent_cannot_verify(self, authenticated_client, organization) -> None:
        d = services.start_dns_challenge(
            organization=organization,
            domain="acme.com",
            is_branding=True,
        )
        response = authenticated_client.post(
            f"/api/v1/organization-domains/{d.id}/verify/"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestOwnershipTransfer:
    def test_dns_win_transfers_ownership_and_notifies_loser(self) -> None:
        loser_org = OrganizationFactory(slug="incumbent")
        loser_admin = AdminFactory(organization=loser_org, email="boss@contested.com")
        # Make sure send_branded_email picks up an admin recipient.
        AdminFactory(organization=loser_org, email="watcher@contested.com")

        winner_org = OrganizationFactory(slug="challenger")
        winner_admin = AdminFactory(organization=winner_org)

        OrganizationDomain.objects.create(
            organization=loser_org,
            domain="contested.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.VERIFIED,
            verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
        )
        challenger_row = services.start_dns_challenge(
            organization=winner_org,
            domain="contested.com",
            is_email_routing=True,
        )

        client = APIClient()
        client.force_authenticate(user=winner_admin)
        with patch(
            "apps.organizations.services.verify_domain_dns",
            return_value=True,
        ):
            mail.outbox.clear()
            response = client.post(
                f"/api/v1/organization-domains/{challenger_row.id}/verify/"
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "verified"

        loser_row = OrganizationDomain.objects.get(
            organization=loser_org, domain="contested.com"
        )
        assert loser_row.status == OrganizationDomain.Status.FAILED

        challenger_row.refresh_from_db()
        assert challenger_row.status == OrganizationDomain.Status.VERIFIED

        # Loser admins were emailed about the loss.
        recipients = [r for m in mail.outbox for r in m.to]
        assert loser_admin.email in recipients

        # Sanity: still only one verified row per domain globally.
        assert (
            OrganizationDomain.objects.filter(
                domain="contested.com",
                status=OrganizationDomain.Status.VERIFIED,
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestPendingPollerTask:
    def test_promotes_pending_when_txt_is_published(self, organization) -> None:
        from apps.organizations.tasks import recheck_dns_pending_domains

        d = services.start_dns_challenge(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        with patch(
            "apps.organizations.services.verify_domain_dns",
            return_value=True,
        ):
            promoted = recheck_dns_pending_domains()
        assert promoted == 1
        d.refresh_from_db()
        assert d.status == OrganizationDomain.Status.VERIFIED

    def test_skips_rows_outside_poll_window(self, organization) -> None:
        from datetime import timedelta
        from django.utils import timezone

        from apps.organizations.tasks import recheck_dns_pending_domains

        d = services.start_dns_challenge(
            organization=organization,
            domain="acme.com",
            is_email_routing=True,
        )
        OrganizationDomain.objects.filter(id=d.id).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        with patch(
            "apps.organizations.services.verify_domain_dns",
            return_value=True,
        ) as mock:
            promoted = recheck_dns_pending_domains()
        assert promoted == 0
        assert mock.call_count == 0
        d.refresh_from_db()
        assert d.status == OrganizationDomain.Status.PENDING


@pytest.mark.django_db
class TestOwnershipTransferAdminEmail:
    def test_admin_email_refuses_transfer(self) -> None:
        """Auto-verify never steals a domain — DNS is required."""
        incumbent = OrganizationFactory(slug="incumbent")
        OrganizationDomain.objects.create(
            organization=incumbent,
            domain="contested.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.VERIFIED,
            verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
        )
        challenger = OrganizationFactory(slug="challenger")
        AdminFactory(
            organization=challenger,
            email="newkid@contested.com",
            is_verified=True,
        )
        with pytest.raises(services.DomainAlreadyClaimedError):
            services.try_admin_email_autoverify(
                organization=challenger,
                domain="contested.com",
                is_email_routing=True,
            )
