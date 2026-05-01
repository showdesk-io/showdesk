"""Tests for self-service signup, slug/domain checks, and join requests."""

import pytest
from django.core import mail
from rest_framework import status

from apps.organizations.models import (
    OrgJoinRequest,
    OTPCode,
    Organization,
    User,
)
from tests.factories import AdminFactory, OrganizationFactory, UserFactory


@pytest.mark.django_db
class TestSignupPathA:
    """Path A: email domain does not match any existing org -> create org + admin."""

    def test_signup_creates_org_and_admin(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@brand-new.com",
                "full_name": "Alice Founder",
                "org_name": "Brand New",
                "org_slug": "brand-new",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] == "created"
        assert response.data["organization"]["slug"] == "brand-new"

        org = Organization.objects.get(slug="brand-new")
        assert org.email_domain == "brand-new.com"
        user = User.objects.get(email="alice@brand-new.com")
        assert user.role == User.Role.ADMIN
        assert user.is_staff is True
        assert user.organization == org
        assert not user.has_usable_password()

    def test_signup_sends_otp_and_welcome_emails(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@example.io",
                "full_name": "Alice",
                "org_name": "Example",
                "org_slug": "example-team",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        # OTP code generated
        assert OTPCode.objects.filter(email="alice@example.io").exists()
        # Both emails dispatched (OTP + welcome)
        recipients = [m.to[0] for m in mail.outbox]
        assert recipients.count("alice@example.io") == 2

    def test_signup_with_public_email_does_not_set_email_domain(
        self, api_client
    ) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@gmail.com",
                "full_name": "Alice",
                "org_name": "Indie Project",
                "org_slug": "indie-project",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        org = Organization.objects.get(slug="indie-project")
        assert org.email_domain == ""

    def test_signup_lowercases_email(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "Alice@MixedCase.Com",
                "full_name": "Alice",
                "org_name": "Mixed",
                "org_slug": "mixed",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(email="alice@mixedcase.com").exists()

    def test_signup_missing_org_fields_for_path_a(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/",
            {"email": "solo@new-domain.io", "full_name": "Solo"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "org_required"

    def test_signup_rejects_taken_slug(self, api_client) -> None:
        OrganizationFactory(slug="taken")
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@new-place.io",
                "full_name": "Alice",
                "org_name": "Taken Inc",
                "org_slug": "taken",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "slug_taken"
        assert response.data["suggestion"]
        assert response.data["suggestion"] != "taken"

    def test_signup_rejects_invalid_slug(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@new.io",
                "full_name": "Alice",
                "org_name": "Bad",
                "org_slug": "Has Spaces!",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "slug_taken"

    def test_signup_rejects_reserved_slug(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@new.io",
                "full_name": "Alice",
                "org_name": "Admin",
                "org_slug": "admin",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "slug_taken"

    def test_signup_rejects_existing_email(
        self, api_client, organization
    ) -> None:
        UserFactory(email="taken@somewhere.com", organization=organization)
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "taken@somewhere.com",
                "full_name": "Dup",
                "org_name": "New Org",
                "org_slug": "new-org",
            },
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "email_taken"


@pytest.mark.django_db
class TestSignupPathB:
    """Path B: email domain matches an existing org -> create join request."""

    def test_signup_creates_join_request_when_domain_matches(
        self, api_client
    ) -> None:
        org = OrganizationFactory(
            slug="acme", name="Acme Inc", email_domain="acme.com"
        )
        AdminFactory(organization=org, email="founder@acme.com")

        response = api_client.post(
            "/api/v1/auth/signup/",
            {"email": "bob@acme.com", "full_name": "Bob Newhire"},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data["status"] == "join_requested"
        assert response.data["organization"]["name"] == "Acme Inc"

        join_request = OrgJoinRequest.objects.get(email="bob@acme.com")
        assert join_request.organization == org
        assert join_request.status == OrgJoinRequest.Status.PENDING
        # No User created yet
        assert not User.objects.filter(email="bob@acme.com").exists()

    def test_join_request_notifies_admins(self, api_client) -> None:
        org = OrganizationFactory(slug="acme", email_domain="acme.com")
        AdminFactory(organization=org, email="admin1@acme.com")
        AdminFactory(organization=org, email="admin2@acme.com")

        response = api_client.post(
            "/api/v1/auth/signup/",
            {"email": "bob@acme.com", "full_name": "Bob"},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        admin_recipients = [m.to[0] for m in mail.outbox if m.to]
        assert "admin1@acme.com" in [
            r for m in mail.outbox for r in m.to
        ]
        assert "admin2@acme.com" in [
            r for m in mail.outbox for r in m.to
        ]

    def test_public_domain_does_not_trigger_join_request(
        self, api_client
    ) -> None:
        """Even if an org's email_domain is somehow gmail.com, signup with
        a different gmail address should still create a new org."""
        OrganizationFactory(slug="weird", email_domain="gmail.com")
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@gmail.com",
                "full_name": "Alice",
                "org_name": "Alice Co",
                "org_slug": "alice-co",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert not OrgJoinRequest.objects.filter(
            email="alice@gmail.com"
        ).exists()

    def test_duplicate_join_request_is_idempotent(self, api_client) -> None:
        org = OrganizationFactory(slug="acme", email_domain="acme.com")
        AdminFactory(organization=org)

        api_client.post(
            "/api/v1/auth/signup/",
            {"email": "bob@acme.com", "full_name": "Bob"},
        )
        api_client.post(
            "/api/v1/auth/signup/",
            {"email": "bob@acme.com", "full_name": "Bob"},
        )
        assert (
            OrgJoinRequest.objects.filter(
                email="bob@acme.com", status=OrgJoinRequest.Status.PENDING
            ).count()
            == 1
        )


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
        OrganizationFactory(slug="acme", name="Acme Inc", email_domain="acme.com")
        response = api_client.get(
            "/api/v1/auth/check-domain/?email=bob@acme.com"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["matches_org"] is True
        assert response.data["org_name"] == "Acme Inc"

    def test_no_match(self, api_client) -> None:
        response = api_client.get(
            "/api/v1/auth/check-domain/?email=alice@unknown.io"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["matches_org"] is False

    def test_public_email_provider(self, api_client) -> None:
        OrganizationFactory(slug="weird", email_domain="gmail.com")
        response = api_client.get(
            "/api/v1/auth/check-domain/?email=alice@gmail.com"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["matches_org"] is False
        assert response.data["reason"] == "public_domain"

    def test_invalid_email(self, api_client) -> None:
        response = api_client.get("/api/v1/auth/check-domain/?email=not-an-email")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestJoinRequestApproveReject:
    def test_admin_can_list_pending_requests(
        self, admin_client, organization
    ) -> None:
        OrgJoinRequest.objects.create(
            organization=organization,
            email="bob@example.com",
            full_name="Bob",
        )
        response = admin_client.get("/api/v1/join-requests/?status=pending")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["email"] == "bob@example.com"

    def test_agent_cannot_approve(
        self, authenticated_client, organization
    ) -> None:
        jr = OrgJoinRequest.objects.create(
            organization=organization, email="bob@example.com"
        )
        response = authenticated_client.post(
            f"/api/v1/join-requests/{jr.id}/approve/"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_approve_creates_user_and_emails(
        self, admin_client, organization
    ) -> None:
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
        # Two emails: OTP + approved
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

    def test_cannot_approve_already_decided(
        self, admin_client, organization
    ) -> None:
        jr = OrgJoinRequest.objects.create(
            organization=organization,
            email="bob@example.com",
            status=OrgJoinRequest.Status.APPROVED,
        )
        response = admin_client.post(f"/api/v1/join-requests/{jr.id}/approve/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_approve_when_email_now_exists_auto_rejects(
        self, admin_client, organization
    ) -> None:
        """If the requester signed up elsewhere between request and approval,
        we don't create a duplicate user; we auto-reject the request."""
        jr = OrgJoinRequest.objects.create(
            organization=organization, email="bob@example.com"
        )
        UserFactory(email="bob@example.com")
        response = admin_client.post(f"/api/v1/join-requests/{jr.id}/approve/")
        assert response.status_code == status.HTTP_409_CONFLICT
        jr.refresh_from_db()
        assert jr.status == OrgJoinRequest.Status.REJECTED

    def test_join_requests_scoped_to_active_org(
        self, admin_client, organization
    ) -> None:
        other_org = OrganizationFactory(slug="other-org")
        OrgJoinRequest.objects.create(
            organization=other_org, email="leak@example.com"
        )
        response = admin_client.get("/api/v1/join-requests/")
        emails = [r["email"] for r in response.data["results"]]
        assert "leak@example.com" not in emails


@pytest.mark.django_db
class TestSignupSuccessQuota:
    """Quota counts only successful org-creations / join-requests, not all hits."""

    def test_failed_attempts_do_not_consume_quota(self, api_client) -> None:
        """A user iterating on slug typos / email checks shouldn't get blocked."""
        OrganizationFactory(slug="taken")
        # 8 failed attempts (slug already taken)
        for _ in range(8):
            response = api_client.post(
                "/api/v1/auth/signup/",
                {
                    "email": "alice@new.io",
                    "full_name": "Alice",
                    "org_name": "X",
                    "org_slug": "taken",
                },
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
        # 9th attempt with a valid slug should still succeed
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "alice@new.io",
                "full_name": "Alice",
                "org_name": "X",
                "org_slug": "valid-slug",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_sixth_successful_signup_is_blocked(self, api_client) -> None:
        for i in range(5):
            response = api_client.post(
                "/api/v1/auth/signup/",
                {
                    "email": f"founder{i}@unique-{i}.io",
                    "full_name": f"Founder {i}",
                    "org_name": f"Org {i}",
                    "org_slug": f"org-{i}",
                },
            )
            assert response.status_code == status.HTTP_201_CREATED
        # 6th success blocked
        response = api_client.post(
            "/api/v1/auth/signup/",
            {
                "email": "spam@spam.io",
                "full_name": "Spam",
                "org_name": "Spam",
                "org_slug": "spam-org",
            },
        )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.data["code"] == "signup_quota_exceeded"


@pytest.mark.django_db
class TestInviteEmailUniqueness:
    """The existing invite endpoint now returns 409 (not 400) for duplicate emails."""

    def test_invite_existing_email_returns_409(
        self, admin_client, agent
    ) -> None:
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

    def test_invite_existing_email_case_insensitive(
        self, admin_client, agent
    ) -> None:
        response = admin_client.post(
            "/api/v1/users/invite/",
            {"email": agent.email.upper(), "first_name": "Up"},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
