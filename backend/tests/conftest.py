"""Shared pytest fixtures for Showdesk tests."""

import pytest
from django.core.cache import caches
from rest_framework.test import APIClient

from tests.factories import AdminFactory, OrganizationFactory, UserFactory


@pytest.fixture(autouse=True)
def _in_memory_cache(settings):
    """Keep tests in a per-process cache, away from any real Redis.

    cache.clear() is a FLUSHDB on RedisCache: run against the default settings
    it would wipe the developer's Redis database, whatever else is stored there.
    Clearing here also stops throttle counters leaking from one test to the next.
    This instance is the one cleared, even if a test then changes CACHES.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "showdesk-tests",
        },
    }
    in_memory = caches["default"]
    in_memory.clear()
    yield
    in_memory.clear()


@pytest.fixture
def local_media(settings, tmp_path):
    """Store uploads on the local disk, as the default storage needs S3."""
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path)},
        },
    }


@pytest.fixture(autouse=True)
def _fast_password_hasher(settings):
    """The default hasher is slow on purpose, and every factory user pays for it."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


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
