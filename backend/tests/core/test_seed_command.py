"""The demo seed command must keep working as models evolve."""

import pytest
from django.core.management import call_command

from apps.organizations.models import Organization, OrganizationDomain


@pytest.mark.django_db
def test_seed_creates_demo_data_and_is_rerunnable():
    call_command("seed")
    call_command("seed")  # idempotent: second run must not fail

    org = Organization.objects.get(slug="acme-corp")
    assert OrganizationDomain.objects.filter(
        organization=org,
        domain="acme.example.com",
        status=OrganizationDomain.Status.VERIFIED,
    ).exists()
