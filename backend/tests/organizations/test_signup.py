"""Tests for the OTP-first self-service signup flow.

Steps:
  1. POST /api/v1/auth/signup/request-otp/  -- send OTP to email
  2. POST /api/v1/auth/signup/verify-otp/   -- verify, create lonely User,
                                               return JWT + next_step
  3a. POST /api/v1/auth/signup/create-org/   -- wizard: create the user's org
  3b. POST /api/v1/auth/signup/request-join/ -- request join when domain matches
"""

import pytest
from django.core import mail
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import (
    OrganizationDomain,
    OrgJoinRequest,
    OTPCode,
    Organization,
    User,
)
from tests.factories import AdminFactory, OrganizationFactory, UserFactory


def _org_with_routing_domain(slug: str, name: str, domain: str) -> Organization:
    """Build an org with a verified email-routing domain row."""
    org = OrganizationFactory(slug=slug, name=name)
    OrganizationDomain.objects.create(
        organization=org,
        domain=domain,
        is_email_routing=True,
        status=OrganizationDomain.Status.VERIFIED,
        verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
    )
    return org


def _request_and_verify(api_client, email: str, full_name: str = ""):
    """Helper: complete steps 1+2 and return the verify-otp response data."""
    payload: dict = {"email": email}
    if full_name:
        payload["full_name"] = full_name
    r1 = api_client.post("/api/v1/auth/signup/request-otp/", payload)
    assert r1.status_code == status.HTTP_200_OK, r1.data
    otp = OTPCode.objects.filter(email=email).order_by("-created_at").first()
    assert otp is not None
    r2 = api_client.post(
        "/api/v1/auth/signup/verify-otp/",
        {"email": email, "code": otp.code},
    )
    assert r2.status_code == status.HTTP_200_OK, r2.data
    return r2.data


@pytest.mark.django_db
class TestSignupRequestOTP:
    def test_sends_otp_for_new_email(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/request-otp/",
            {"email": "alice@brand-new.com", "full_name": "Alice Founder"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert OTPCode.objects.filter(email="alice@brand-new.com").exists()
        assert mail.outbox, "OTP email should have been sent"
        assert mail.outbox[-1].to == ["alice@brand-new.com"]

    def test_sends_otp_for_existing_admin(self, api_client, organization) -> None:
        """Existing admin can use the signup flow as a login path."""
        AdminFactory(organization=organization, email="admin@acme.com")
        response = api_client.post(
            "/api/v1/auth/signup/request-otp/",
            {"email": "admin@acme.com"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert OTPCode.objects.filter(email="admin@acme.com").exists()

    def test_blocks_end_user_email(self, api_client, organization) -> None:
        UserFactory(
            email="customer@acme.com",
            organization=organization,
            role=User.Role.END_USER,
        )
        response = api_client.post(
            "/api/v1/auth/signup/request-otp/",
            {"email": "customer@acme.com"},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "email_taken"
        assert not OTPCode.objects.filter(email="customer@acme.com").exists()

    def test_blocks_deactivated_email(self, api_client, organization) -> None:
        UserFactory(
            email="ghost@acme.com",
            organization=organization,
            role=User.Role.AGENT,
            is_active=False,
        )
        response = api_client.post(
            "/api/v1/auth/signup/request-otp/",
            {"email": "ghost@acme.com"},
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_lowercases_email(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/request-otp/",
            {"email": "Alice@MixedCase.Com"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert OTPCode.objects.filter(email="alice@mixedcase.com").exists()

    def test_full_name_persists_across_request(self, api_client) -> None:
        """The full_name from request-otp is applied at user creation."""
        api_client.post(
            "/api/v1/auth/signup/request-otp/",
            {"email": "bob@brand-new.io", "full_name": "Bob Builder"},
        )
        otp = OTPCode.objects.get(email="bob@brand-new.io")
        api_client.post(
            "/api/v1/auth/signup/verify-otp/",
            {"email": "bob@brand-new.io", "code": otp.code},
        )
        user = User.objects.get(email="bob@brand-new.io")
        assert user.first_name == "Bob"
        assert user.last_name == "Builder"


@pytest.mark.django_db
class TestSignupVerifyOTP:
    def test_verify_creates_lonely_user(self, api_client) -> None:
        data = _request_and_verify(api_client, "alice@new.io", "Alice")
        assert data["next_step"] == "create_org"
        assert data["domain"] == "new.io"
        assert data["access"]
        assert data["refresh"]

        user = User.objects.get(email="alice@new.io")
        assert user.organization is None
        assert user.role == User.Role.ADMIN
        assert user.is_staff is True
        assert user.is_verified is True
        assert not user.has_usable_password()

    def test_verify_returns_join_request_when_domain_matches(self, api_client) -> None:
        org = _org_with_routing_domain("acme", "Acme Inc", "acme.com")
        AdminFactory(organization=org, email="founder@acme.com")
        data = _request_and_verify(api_client, "bob@acme.com", "Bob")
        assert data["next_step"] == "join_request"
        assert data["org_name"] == "Acme Inc"
        assert data["org_id"] == str(org.id)

    def test_verify_returns_has_org_for_existing_admin(
        self, api_client, organization
    ) -> None:
        admin = AdminFactory(organization=organization, email="admin@acme.com")
        data = _request_and_verify(api_client, admin.email)
        assert data["next_step"] == "has_org"
        assert data["org_id"] == str(organization.id)
        assert data["org_slug"] == organization.slug

    def test_verify_with_public_domain_does_not_match_join_request(
        self, api_client
    ) -> None:
        # Even if some org somehow has gmail.com configured, public webmail
        # is excluded from the routing-domain lookup.
        OrganizationFactory(slug="weird")
        data = _request_and_verify(api_client, "alice@gmail.com")
        assert data["next_step"] == "create_org"
        assert data["domain"] == "gmail.com"

    def test_verify_invalid_code(self, api_client) -> None:
        api_client.post("/api/v1/auth/signup/request-otp/", {"email": "alice@x.io"})
        response = api_client.post(
            "/api/v1/auth/signup/verify-otp/",
            {"email": "alice@x.io", "code": "000000"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["code"] == "invalid_otp"
        assert not User.objects.filter(email="alice@x.io").exists()

    def test_verify_marks_otp_used(self, api_client) -> None:
        _request_and_verify(api_client, "alice@x.io")
        otp = OTPCode.objects.get(email="alice@x.io")
        assert otp.used_at is not None
        # Reusing the same code is rejected.
        response = api_client.post(
            "/api/v1/auth/signup/verify-otp/",
            {"email": "alice@x.io", "code": otp.code},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


def _auth_client(verify_data: dict) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {verify_data['access']}")
    return client


@pytest.mark.django_db
class TestSignupCreateOrg:
    def test_create_org_attaches_lonely_user(self, api_client) -> None:
        data = _request_and_verify(api_client, "alice@brand-new.com", "Alice")
        client = _auth_client(data)
        response = client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "Brand New", "org_slug": "brand-new"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        org = Organization.objects.get(slug="brand-new")
        assert response.data["email_domain"] == "brand-new.com"
        assert response.data["email_domain_status"] == "verified"
        # Founder's domain auto-verified into a routing row.
        assert org.domains.filter(
            domain="brand-new.com",
            is_email_routing=True,
            status=OrganizationDomain.Status.VERIFIED,
        ).exists()
        user = User.objects.get(email="alice@brand-new.com")
        assert user.organization == org
        assert user.role == User.Role.ADMIN
        assert user.is_staff is True

    def test_create_org_skips_domain_for_public_email(self, api_client) -> None:
        data = _request_and_verify(api_client, "alice@gmail.com")
        client = _auth_client(data)
        response = client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "Indie", "org_slug": "indie"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        org = Organization.objects.get(slug="indie")
        # No routing row created for public webmail.
        assert not org.domains.filter(is_email_routing=True).exists()
        assert response.data["email_domain"] == ""

    def test_create_org_with_custom_email_domain_starts_dns_challenge(
        self, api_client
    ) -> None:
        data = _request_and_verify(api_client, "alice@personal.io")
        client = _auth_client(data)
        response = client.post(
            "/api/v1/auth/signup/create-org/",
            {
                "org_name": "Acme",
                "org_slug": "acme",
                "email_domain": "acme-corp.fr",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["email_domain"] == "acme-corp.fr"
        assert response.data["email_domain_status"] == "pending_dns"
        org = Organization.objects.get(slug="acme")
        row = org.domains.get(domain="acme-corp.fr")
        assert row.status == OrganizationDomain.Status.PENDING
        assert row.verification_method == OrganizationDomain.VerificationMethod.DNS_TXT
        assert row.verification_token != ""

    def test_create_org_rejects_taken_slug(self, api_client) -> None:
        OrganizationFactory(slug="taken")
        data = _request_and_verify(api_client, "alice@new.io")
        client = _auth_client(data)
        response = client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "Whatever", "org_slug": "taken"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "slug_taken"
        assert response.data["suggestion"] != "taken"

    def test_create_org_rejects_reserved_slug(self, api_client) -> None:
        data = _request_and_verify(api_client, "alice@new.io")
        client = _auth_client(data)
        response = client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "Admin", "org_slug": "admin"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "slug_taken"

    def test_create_org_unauthenticated(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "X", "org_slug": "x-co"},
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_create_org_user_with_existing_org(self, api_client, organization) -> None:
        admin = AdminFactory(organization=organization, email="admin@a.com")
        data = _request_and_verify(api_client, admin.email)
        client = _auth_client(data)
        response = client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "Other", "org_slug": "other"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "already_in_org"

    def test_create_org_sends_welcome_email(self, api_client) -> None:
        data = _request_and_verify(api_client, "alice@brand-new.com")
        client = _auth_client(data)
        mail.outbox.clear()
        client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "Brand New", "org_slug": "brand-new"},
        )
        recipients = [m.to[0] for m in mail.outbox if m.to]
        assert "alice@brand-new.com" in recipients


@pytest.mark.django_db
class TestSignupRequestJoin:
    def test_request_join_creates_pending_request(self, api_client) -> None:
        org = _org_with_routing_domain("acme", "Acme", "acme.com")
        AdminFactory(organization=org, email="founder@acme.com")
        data = _request_and_verify(api_client, "bob@acme.com", "Bob Newhire")
        client = _auth_client(data)
        response = client.post(
            "/api/v1/auth/signup/request-join/", {"full_name": "Bob Newhire"}
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data["organization"]["name"] == org.name

        join_request = OrgJoinRequest.objects.get(email="bob@acme.com")
        assert join_request.organization == org
        assert join_request.status == OrgJoinRequest.Status.PENDING

        # User exists from OTP verify; org is still None until approval.
        user = User.objects.get(email="bob@acme.com")
        assert user.organization is None

    def test_request_join_notifies_admins(self, api_client) -> None:
        org = _org_with_routing_domain("acme", "Acme", "acme.com")
        AdminFactory(organization=org, email="admin1@acme.com")
        AdminFactory(organization=org, email="admin2@acme.com")
        data = _request_and_verify(api_client, "bob@acme.com")
        client = _auth_client(data)
        mail.outbox.clear()
        client.post("/api/v1/auth/signup/request-join/")
        all_recipients = [r for m in mail.outbox for r in m.to]
        assert "admin1@acme.com" in all_recipients
        assert "admin2@acme.com" in all_recipients

    def test_request_join_idempotent(self, api_client) -> None:
        org = _org_with_routing_domain("acme", "Acme", "acme.com")
        AdminFactory(organization=org)
        data = _request_and_verify(api_client, "bob@acme.com")
        client = _auth_client(data)
        client.post("/api/v1/auth/signup/request-join/")
        client.post("/api/v1/auth/signup/request-join/")
        assert (
            OrgJoinRequest.objects.filter(
                email="bob@acme.com", status=OrgJoinRequest.Status.PENDING
            ).count()
            == 1
        )

    def test_request_join_no_match(self, api_client) -> None:
        data = _request_and_verify(api_client, "alice@unknown.io")
        client = _auth_client(data)
        response = client.post("/api/v1/auth/signup/request-join/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "no_match"

    def test_request_join_public_domain(self, api_client) -> None:
        OrganizationFactory(slug="weird")
        data = _request_and_verify(api_client, "alice@gmail.com")
        client = _auth_client(data)
        response = client.post("/api/v1/auth/signup/request-join/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestApproveAttachesLonelyUser:
    """The new approve action attaches an existing lonely user instead of
    auto-rejecting (the old behavior)."""

    def test_approve_attaches_lonely_user(self, api_client) -> None:
        org = _org_with_routing_domain("acme", "Acme", "acme.com")
        admin = AdminFactory(organization=org)
        # Bob signs up via the new flow
        data = _request_and_verify(api_client, "bob@acme.com", "Bob")
        client = _auth_client(data)
        client.post("/api/v1/auth/signup/request-join/")

        # Admin approves
        admin_client = APIClient()
        admin_client.force_authenticate(user=admin)
        jr = OrgJoinRequest.objects.get(email="bob@acme.com")
        response = admin_client.post(f"/api/v1/join-requests/{jr.id}/approve/")
        assert response.status_code == status.HTTP_200_OK

        bob = User.objects.get(email="bob@acme.com")
        assert bob.organization == org
        assert bob.role == User.Role.AGENT

    def test_approve_rejects_when_user_joined_another_org(self, api_client) -> None:
        org_a = _org_with_routing_domain("a-corp", "A Corp", "example.com")
        admin_a = AdminFactory(organization=org_a)
        # Bob asks to join A
        data = _request_and_verify(api_client, "bob@example.com")
        client = _auth_client(data)
        client.post("/api/v1/auth/signup/request-join/")
        # ...but in the meantime he is somehow attached to another org.
        org_b = OrganizationFactory(slug="b-corp")
        bob = User.objects.get(email="bob@example.com")
        bob.organization = org_b
        bob.save()

        admin_client = APIClient()
        admin_client.force_authenticate(user=admin_a)
        jr = OrgJoinRequest.objects.get(email="bob@example.com")
        response = admin_client.post(f"/api/v1/join-requests/{jr.id}/approve/")
        assert response.status_code == status.HTTP_409_CONFLICT
        jr.refresh_from_db()
        assert jr.status == OrgJoinRequest.Status.REJECTED


@pytest.mark.django_db
class TestCheckSlug:
    def test_available_slug(self, api_client) -> None:
        response = api_client.get("/api/v1/auth/check-slug/?slug=fresh-slug")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["available"] is True

    def test_taken_slug(self, api_client) -> None:
        OrganizationFactory(slug="taken-slug")
        response = api_client.get("/api/v1/auth/check-slug/?slug=taken-slug")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["available"] is False
        assert response.data["reason"] == "taken"
        assert response.data["suggestion"]

    def test_reserved_slug(self, api_client) -> None:
        response = api_client.get("/api/v1/auth/check-slug/?slug=admin")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["available"] is False
        assert response.data["reason"] == "reserved"

    def test_invalid_format(self, api_client) -> None:
        response = api_client.get("/api/v1/auth/check-slug/?slug=Has Spaces")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["available"] is False
        assert response.data["reason"] == "invalid_format"

    def test_missing_slug(self, api_client) -> None:
        response = api_client.get("/api/v1/auth/check-slug/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCheckDomain:
    def test_matches_existing_org(self, api_client) -> None:
        _org_with_routing_domain("acme", "Acme Inc", "acme.com")
        response = api_client.get("/api/v1/auth/check-domain/?email=bob@acme.com")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["matches_org"] is True
        assert response.data["org_name"] == "Acme Inc"

    def test_no_match(self, api_client) -> None:
        response = api_client.get("/api/v1/auth/check-domain/?email=alice@unknown.io")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["matches_org"] is False

    def test_public_email_provider(self, api_client) -> None:
        OrganizationFactory(slug="weird")
        response = api_client.get("/api/v1/auth/check-domain/?email=alice@gmail.com")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["matches_org"] is False
        assert response.data["reason"] == "public_domain"

    def test_invalid_email(self, api_client) -> None:
        response = api_client.get("/api/v1/auth/check-domain/?email=not-an-email")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestSignupSuccessQuota:
    """Quota counts only successful org-creations / join-requests, not OTP sends."""

    def test_failed_create_org_attempts_do_not_consume_quota(self, api_client) -> None:
        OrganizationFactory(slug="taken")
        data = _request_and_verify(api_client, "alice@new.io")
        client = _auth_client(data)
        # 8 failed slug attempts
        for _ in range(8):
            r = client.post(
                "/api/v1/auth/signup/create-org/",
                {"org_name": "X", "org_slug": "taken"},
            )
            assert r.status_code == status.HTTP_400_BAD_REQUEST
        # A valid one still succeeds.
        r = client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "X", "org_slug": "valid-slug"},
        )
        assert r.status_code == status.HTTP_201_CREATED

    def test_sixth_successful_create_is_blocked(self, api_client) -> None:
        cache.clear()
        for i in range(5):
            data = _request_and_verify(api_client, f"founder{i}@unique-{i}.io")
            client = _auth_client(data)
            r = client.post(
                "/api/v1/auth/signup/create-org/",
                {"org_name": f"Org {i}", "org_slug": f"org-{i}"},
            )
            assert r.status_code == status.HTTP_201_CREATED
        data = _request_and_verify(api_client, "spam@spam.io")
        client = _auth_client(data)
        r = client.post(
            "/api/v1/auth/signup/create-org/",
            {"org_name": "Spam", "org_slug": "spam-org"},
        )
        assert r.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert r.data["code"] == "signup_quota_exceeded"


@pytest.mark.django_db
class TestJoinRequestAdminActions:
    """Admin-side approve/reject actions on the JoinRequestViewSet."""

    def test_admin_can_list_pending_requests(self, admin_client, organization) -> None:
        OrgJoinRequest.objects.create(
            organization=organization,
            email="bob@example.com",
            full_name="Bob",
        )
        response = admin_client.get("/api/v1/join-requests/?status=pending")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["email"] == "bob@example.com"

    def test_agent_cannot_approve(self, authenticated_client, organization) -> None:
        jr = OrgJoinRequest.objects.create(
            organization=organization, email="bob@example.com"
        )
        response = authenticated_client.post(f"/api/v1/join-requests/{jr.id}/approve/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_approve_creates_user_when_no_lonely_row(
        self, admin_client, organization
    ) -> None:
        """Approve still works in the legacy path: JR exists but no User row.

        This covers any path that bypasses signup-verify-otp (e.g. a manual
        admin-side import of a join request)."""
        jr = OrgJoinRequest.objects.create(
            organization=organization,
            email="bob@example.com",
            full_name="Bob Junior",
        )
        response = admin_client.post(f"/api/v1/join-requests/{jr.id}/approve/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "approved"
        user = User.objects.get(email="bob@example.com")
        assert user.role == User.Role.AGENT
        assert user.organization == organization
        assert user.first_name == "Bob"
        assert user.last_name == "Junior"
        assert OTPCode.objects.filter(email="bob@example.com").exists()
        bob_messages = [m for m in mail.outbox if "bob@example.com" in m.to]
        assert len(bob_messages) == 2

    def test_admin_reject_does_not_create_user(
        self, admin_client, organization
    ) -> None:
        jr = OrgJoinRequest.objects.create(
            organization=organization, email="bob@example.com"
        )
        response = admin_client.post(f"/api/v1/join-requests/{jr.id}/reject/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "rejected"
        assert not User.objects.filter(email="bob@example.com").exists()

    def test_cannot_approve_already_decided(self, admin_client, organization) -> None:
        jr = OrgJoinRequest.objects.create(
            organization=organization,
            email="bob@example.com",
            status=OrgJoinRequest.Status.APPROVED,
        )
        response = admin_client.post(f"/api/v1/join-requests/{jr.id}/approve/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_join_requests_scoped_to_active_org(
        self, admin_client, organization
    ) -> None:
        other_org = OrganizationFactory(slug="other-org")
        OrgJoinRequest.objects.create(organization=other_org, email="leak@example.com")
        response = admin_client.get("/api/v1/join-requests/")
        emails = [r["email"] for r in response.data["results"]]
        assert "leak@example.com" not in emails


@pytest.mark.django_db
class TestInviteEmailUniqueness:
    """The existing invite endpoint still returns 409 for duplicate emails."""

    def test_invite_existing_email_returns_409(self, admin_client, agent) -> None:
        response = admin_client.post(
            "/api/v1/users/invite/",
            {"email": agent.email, "first_name": "Dup", "last_name": "Agent"},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "email_taken"

    def test_invite_existing_email_case_insensitive(self, admin_client, agent) -> None:
        response = admin_client.post(
            "/api/v1/users/invite/",
            {"email": agent.email.upper(), "first_name": "Up"},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
