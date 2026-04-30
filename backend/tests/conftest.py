"""Shared pytest fixtures for Showdesk tests."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from tests.factories import AdminFactory, OrganizationFactory, UserFactory


@pytest.fixture(autouse=True)
def _reset_throttle_cache():
    """Clear DRF throttle counters between tests so they don't leak.

    DRF's AnonRateThrottle stores hit counts in the default cache, keyed by
    client IP. Without this fixture, tests that hit the same throttled
    endpoint (e.g. signup) accumulate across the suite and fail with 429.
    """
    cache.clear()
    yield
    cache.clear()


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
