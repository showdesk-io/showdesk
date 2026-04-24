"""Tests for the in-app widget identity-hash endpoint (dogfooding)."""

import hashlib
import hmac

import pytest
from rest_framework.test import APIClient

from apps.organizations.models import SHOWDESK_INTERNAL_ORG_SLUG, Organization
from tests.factories import OrganizationFactory, UserFactory


URL = "/api/v1/widget/identity-hash/"


@pytest.fixture
def internal_org(db):
    """Internal org might already exist from the data migration in this DB."""
    org, _ = Organization.objects.get_or_create(
        slug=SHOWDESK_INTERNAL_ORG_SLUG,
        defaults={"name": "Showdesk Internal"},
    )
    return org


@pytest.mark.django_db
def test_identity_hash_requires_authentication(api_client: APIClient, internal_org):
    response = api_client.get(URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_identity_hash_returns_token_and_matching_hmac(
    api_client: APIClient, internal_org
):
    user = UserFactory()
    api_client.force_authenticate(user=user)

    response = api_client.get(URL)

    assert response.status_code == 200
    data = response.json()
    assert data["token"] == str(internal_org.api_token)
    assert data["external_user_id"] == str(user.id)

    expected = hmac.new(
        internal_org.widget_secret.encode(),
        str(user.id).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert data["user_hash"] == expected


@pytest.mark.django_db
def test_identity_hash_returns_503_when_internal_org_missing(api_client: APIClient):
    Organization.objects.filter(slug=SHOWDESK_INTERNAL_ORG_SLUG).delete()
    user = UserFactory()
    api_client.force_authenticate(user=user)

    response = api_client.get(URL)
    assert response.status_code == 503


@pytest.mark.django_db
def test_identity_hash_uses_internal_org_not_user_org(
    api_client: APIClient, internal_org
):
    other_org = OrganizationFactory()
    user = UserFactory(organization=other_org)
    api_client.force_authenticate(user=user)

    response = api_client.get(URL)
    assert response.status_code == 200
    # Token must be the internal org's, not the user's own org token.
    assert response.json()["token"] == str(internal_org.api_token)
    assert response.json()["token"] != str(other_org.api_token)


@pytest.mark.django_db
def test_identity_hash_user_payload(api_client: APIClient, internal_org):
    user = UserFactory(first_name="Ada", last_name="Lovelace", email="ada@example.com")
    api_client.force_authenticate(user=user)

    response = api_client.get(URL)
    payload = response.json()["user"]
    assert payload["id"] == str(user.id)
    assert payload["name"] == "Ada Lovelace"
    assert payload["email"] == "ada@example.com"


@pytest.mark.django_db
def test_identity_hash_falls_back_to_email_when_name_empty(
    api_client: APIClient, internal_org
):
    user = UserFactory(first_name="", last_name="", email="anon@example.com")
    api_client.force_authenticate(user=user)

    response = api_client.get(URL)
    assert response.json()["user"]["name"] == "anon@example.com"


@pytest.mark.django_db
def test_identity_hash_ignores_inactive_internal_org(api_client: APIClient):
    Organization.objects.filter(slug=SHOWDESK_INTERNAL_ORG_SLUG).delete()
    Organization.objects.create(
        slug=SHOWDESK_INTERNAL_ORG_SLUG,
        name="Showdesk Internal",
        is_active=False,
    )
    user = UserFactory()
    api_client.force_authenticate(user=user)

    response = api_client.get(URL)
    assert response.status_code == 503
