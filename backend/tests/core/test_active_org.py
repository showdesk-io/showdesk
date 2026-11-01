"""The organization a superuser's request acts on, across the API."""

import pytest
from rest_framework.test import APIClient

from apps.core.permissions import get_active_org
from tests.factories import OrganizationFactory, TicketFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "header", ["not-a-uuid", "00000000-0000-4000-8000-000000000000"]
)
def test_other_viewsets_keep_the_superusers_own_org(organization, header):
    # The frontend persists the org it sends: a stale one mustn't lock the user out.
    ticket = TicketFactory(organization=organization)
    client = APIClient()
    client.force_authenticate(UserFactory(organization=organization, is_superuser=True))
    res = client.get("/api/v1/tickets/", HTTP_X_SHOWDESK_ORG=header)
    assert res.status_code == 200
    assert [row["id"] for row in res.data["results"]] == [str(ticket.id)]


def test_impersonation_resolves_the_header(organization, rf):
    other = OrganizationFactory()
    request = rf.get("/", HTTP_X_SHOWDESK_ORG=str(other.id))
    request.user = UserFactory(organization=organization, is_superuser=True)
    assert get_active_org(request) == other
