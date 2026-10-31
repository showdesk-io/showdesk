"""First-run setup only ever replaces its own unfinished attempts."""

import pytest
from rest_framework.test import APIClient

from apps.organizations.models import User
from tests.factories import (
    AdminFactory,
    EndUserFactory,
    OrganizationFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

STATUS = "/api/v1/setup/status/"
INITIALIZE = "/api/v1/setup/initialize/"
BODY = {"email": "new@example.com", "first_name": "New"}


def _initialized() -> bool:
    return APIClient().get(STATUS).data["initialized"]


def _initialize() -> int:
    return APIClient().post(INITIALIZE, BODY).status_code


def test_a_new_instance_can_be_set_up() -> None:
    assert _initialized() is False
    assert _initialize() == 201
    assert User.objects.get(email=BODY["email"]).is_superuser is True


def test_an_unfinished_attempt_can_be_replaced() -> None:
    User.objects.create_superuser(email="typo@example.com")
    assert _initialized() is False
    assert _initialize() == 201
    assert not User.objects.filter(email="typo@example.com").exists()


def test_end_users_do_not_lock_setup_and_are_kept() -> None:
    end_user = EndUserFactory(organization=OrganizationFactory())
    assert _initialized() is False
    assert _initialize() == 201
    assert User.objects.filter(pk=end_user.pk).exists()


@pytest.mark.parametrize(
    "make",
    [
        lambda: User.objects.create_superuser(
            email="root@example.com", is_verified=True
        ),
        lambda: AdminFactory(email="root@example.com", is_staff=True, is_verified=True),
        # Back to unverified after an email change.
        lambda: AdminFactory(
            email="root@example.com", is_staff=True, is_verified=False
        ),
        lambda: User.objects.create_superuser(
            email="root@example.com",
            is_verified=False,
            organization=OrganizationFactory(),
        ),
        # Lost is_staff to a demotion, or never had it.
        lambda: UserFactory(
            email="root@example.com", is_staff=False, is_verified=False
        ),
        lambda: AdminFactory(
            email="root@example.com",
            is_staff=False,
            is_verified=False,
            organization=None,
        ),
    ],
    ids=[
        "verified-superuser",
        "verified-admin",
        "unverified-admin",
        "unverified-superuser-in-org",
        "unverified-agent",
        "unverified-admin-without-org",
    ],
)
def test_a_real_user_locks_setup_and_is_kept(make) -> None:
    user = make()
    assert _initialized() is True
    assert _initialize() == 403
    assert User.objects.filter(pk=user.pk).exists()
    assert not User.objects.filter(email=BODY["email"]).exists()
