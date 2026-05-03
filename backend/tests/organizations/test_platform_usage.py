"""Tests for /api/v1/platform/organizations/usage/.

Aggregates resource usage platform-wide and per-org. Read-only,
admin-only (IsPlatformAdmin = is_superuser).
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tests.factories import (
    OrganizationFactory,
    TicketAttachmentFactory,
    TicketFactory,
    UserFactory,
)


URL = "/api/v1/platform/organizations/usage/"


@pytest.fixture
def superuser_client():
    """Authenticated as a platform admin (is_superuser=True)."""
    org = OrganizationFactory()
    su = UserFactory(organization=org, role="admin", is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=su)
    return client


@pytest.mark.django_db
class TestPlatformUsage:
    def test_non_superuser_forbidden(self, authenticated_client):
        response = authenticated_client.get(URL)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_platform_totals_and_per_org(self, superuser_client):
        # The fixture itself provisions one org + one user.
        org_a = OrganizationFactory(slug="acme")
        org_b = OrganizationFactory(slug="globex")

        UserFactory.create_batch(2, organization=org_a, role="agent")
        UserFactory(organization=org_b, role="admin")

        TicketFactory.create_batch(5, organization=org_a)
        TicketFactory.create_batch(3, organization=org_b)

        ticket = TicketFactory(organization=org_a)
        TicketAttachmentFactory(ticket=ticket, file_size=1024, content_type="image/png")

        response = superuser_client.get(URL)
        assert response.status_code == status.HTTP_200_OK

        platform = response.data["platform"]
        # 1 fixture org + 2 here = 3 total. (Ticket.create might also
        # auto-build org via SubFactory -- that adds one more per ticket
        # without organization=). We pinned organization on every Ticket
        # above, so no extras. Just sanity-check non-zero.
        assert platform["organizations_total"] >= 3
        assert platform["agents_active"] >= 3
        # 5 + 3 + 1 (the attachment-bearing ticket) = 9
        assert platform["tickets_total"] >= 9
        assert platform["attachment_storage_bytes"] >= 1024

        # Per-org breakdown lists Acme heavier than Globex (ticket count).
        rows = {r["slug"]: r for r in response.data["organizations"]}
        assert rows["acme"]["tickets"] >= 6  # 5 + 1
        assert rows["globex"]["tickets"] == 3
        assert rows["acme"]["storage_bytes"] >= 1024
        assert rows["acme"]["agents"] == 2

    def test_period_month_filters_old_data(self, superuser_client):
        from datetime import timedelta
        from django.utils import timezone

        org = OrganizationFactory(slug="acme-month")

        # Recent ticket (visible in month window).
        TicketFactory(organization=org)

        # Stale ticket (45 days old) -- excluded from month window.
        old = TicketFactory(organization=org)
        old.created_at = timezone.now() - timedelta(days=45)
        old.save(update_fields=["created_at"])

        response = superuser_client.get(URL, {"period": "month"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["period"] == "month"

        rows = {r["slug"]: r for r in response.data["organizations"]}
        # 1 recent only -- the 45-day-old one is filtered out.
        assert rows["acme-month"]["tickets"] == 1

    def test_top_orgs_capped_at_twenty(self, superuser_client):
        for i in range(25):
            org = OrganizationFactory(slug=f"o-{i}")
            # Variable ticket counts so the sort actually has work to do.
            TicketFactory.create_batch(i + 1, organization=org)

        response = superuser_client.get(URL)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["organizations"]) == 20
        # Sorted heaviest-first.
        counts = [r["tickets"] for r in response.data["organizations"]]
        assert counts == sorted(counts, reverse=True)
