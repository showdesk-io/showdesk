"""A changed email has to be proven again, without touching first-run setup."""

from types import SimpleNamespace

import pytest
from django.contrib.admin.sites import AdminSite
from rest_framework.test import APIClient

from apps.organizations.admin import UserAdmin
from apps.organizations.models import OrganizationDomain, OTPCode, User
from tests.factories import AdminFactory

pytestmark = pytest.mark.django_db

NEW_EMAIL = "someone@claimed.example"


def _client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _change_email(client: APIClient, user: User, email: str = NEW_EMAIL):
    return client.patch(f"/api/v1/users/{user.id}/", {"email": email}, format="json")


def _claim_domain(client: APIClient):
    return client.post(
        "/api/v1/organization-domains/",
        {
            "domain": "claimed.example",
            "verification_method": "admin_email",
            "is_email_routing": True,
        },
        format="json",
    )


def _setup_stays_locked(*users: User) -> None:
    client = APIClient()
    assert client.get("/api/v1/setup/status/").data["initialized"] is True
    body = {"email": "new@example.com", "first_name": "New"}
    assert client.post("/api/v1/setup/initialize/", body).status_code == 403
    for user in users:
        assert User.objects.filter(pk=user.pk).exists()


@pytest.fixture
def admin(organization):
    return AdminFactory(organization=organization, is_verified=True)


class TestEmailChange:
    def test_another_admin_changing_it(self, admin, organization) -> None:
        other = AdminFactory(organization=organization, is_verified=True)
        assert _change_email(_client_for(admin), other).status_code == 200
        other.refresh_from_db()
        assert other.email == NEW_EMAIL
        assert other.is_verified is False

    def test_an_admin_changing_their_own(self, admin) -> None:
        assert _change_email(_client_for(admin), admin).status_code == 200
        admin.refresh_from_db()
        assert admin.is_verified is False

    def test_the_same_email_changes_nothing(self, admin) -> None:
        client = _client_for(admin)
        assert _change_email(client, admin, admin.email).status_code == 200
        admin.refresh_from_db()
        assert admin.is_verified is True

    def test_other_fields_change_nothing(self, admin) -> None:
        res = _client_for(admin).patch(
            f"/api/v1/users/{admin.id}/", {"first_name": "New"}, format="json"
        )
        assert res.status_code == 200
        admin.refresh_from_db()
        assert admin.is_verified is True

    def test_from_the_django_admin(self, admin) -> None:
        admin.email = NEW_EMAIL
        form = SimpleNamespace(changed_data=["email"])
        UserAdmin(User, AdminSite()).save_model(None, admin, form, change=True)
        admin.refresh_from_db()
        assert admin.is_verified is False


class TestDomainClaim:
    def test_an_unproven_address_cannot_verify_a_domain(self, admin) -> None:
        client = _client_for(admin)
        _change_email(client, admin)
        res = _claim_domain(client)
        assert res.status_code == 400
        assert res.data["code"] == "cannot_autoverify"
        assert not OrganizationDomain.objects.filter(
            domain="claimed.example", status="verified"
        ).exists()

    def test_the_next_login_proves_it(self, admin) -> None:
        client = _client_for(admin)
        _change_email(client, admin)
        otp = OTPCode.generate(NEW_EMAIL)
        res = APIClient().post(
            "/api/v1/auth/verify-otp/", {"email": NEW_EMAIL, "code": otp.code}
        )
        assert res.status_code == 200
        admin.refresh_from_db()
        assert admin.is_verified is True
        assert _claim_domain(client).status_code == 201


class TestFirstRunSetup:
    def test_the_only_admin_changing_their_email(self, admin) -> None:
        _change_email(_client_for(admin), admin)
        admin.refresh_from_db()
        assert admin.is_verified is False
        _setup_stays_locked(admin)

    def test_a_superuser_in_an_organization(self, organization) -> None:
        superuser = User.objects.create_superuser(
            email="root@example.com", organization=organization, is_verified=True
        )
        assert _change_email(_client_for(superuser), superuser).status_code == 200
        superuser.refresh_from_db()
        assert superuser.is_verified is False
        _setup_stays_locked(superuser)

    def test_the_only_platform_admin_from_the_django_admin(self) -> None:
        """In no organization, it has no domain to claim and looks like a retry."""
        superuser = User.objects.create_superuser(
            email="root@example.com", is_verified=True
        )
        superuser.email = NEW_EMAIL
        form = SimpleNamespace(changed_data=["email"])
        UserAdmin(User, AdminSite()).save_model(None, superuser, form, change=True)
        superuser.refresh_from_db()
        assert superuser.is_verified is True
        _setup_stays_locked(superuser)
