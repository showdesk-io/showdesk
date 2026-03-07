"""Shared pytest fixtures for Showdesk tests."""

import pytest
from rest_framework.test import APIClient

from tests.factories import AdminFactory, OrganizationFactory, UserFactory


@pytest.fixture
def api_client() -> APIClient:
    """Return an unauthenticated API client."""
    return APIClient()


@pytest.fixture
def organization():
    """Create and return a test organization."""
    return OrganizationFactory()


@pytest.fixture
def agent(organization):
    """Create and return an agent user."""
    return UserFactory(organization=organization, role="agent")


@pytest.fixture
def admin_user(organization):
    """Create and return an admin user."""
    return AdminFactory(organization=organization)


@pytest.fixture
def authenticated_client(agent) -> APIClient:
    """Return an API client authenticated as an agent."""
    client = APIClient()
    client.force_authenticate(user=agent)
    return client


@pytest.fixture
def admin_client(admin_user) -> APIClient:
    """Return an API client authenticated as an admin."""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client
