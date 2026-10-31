"""The default order of the ticket list, which has a GROUP BY for its message count."""

import warnings
from datetime import timedelta

import pytest
from django.core.paginator import UnorderedObjectListWarning
from django.utils import timezone

from apps.tickets.models import Ticket
from apps.tickets.serializers import ticket_list_rows
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/tickets/"


@pytest.fixture
def tickets(organization):
    """Three tickets created in a known order, then updated in another one."""
    now = timezone.now()
    rows = [TicketFactory(organization=organization) for _ in range(3)]
    for age, ticket in zip((3, 1, 2), rows, strict=True):
        Ticket.objects.filter(pk=ticket.pk).update(created_at=now - timedelta(days=age))
    for age, ticket in zip((10, 30, 20), rows, strict=True):
        Ticket.objects.filter(pk=ticket.pk).update(
            updated_at=now - timedelta(minutes=age)
        )
    return rows


def _references(res) -> list[str]:
    return [row["reference"] for row in res.data["results"]]


def test_rows_are_ordered_despite_the_group_by(organization):
    rows = ticket_list_rows(Ticket.objects.filter(organization=organization))
    assert rows.ordered
    assert rows.query.order_by == ("-created_at", "-id")


def test_default_order_is_newest_created_first(authenticated_client, tickets):
    res = authenticated_client.get(URL)
    assert _references(res) == [
        t.reference for t in (tickets[1], tickets[2], tickets[0])
    ]


def test_tickets_created_together_keep_a_stable_order(
    authenticated_client, organization
):
    now = timezone.now()
    rows = [TicketFactory(organization=organization) for _ in range(5)]
    Ticket.objects.filter(pk__in=[t.pk for t in rows]).update(created_at=now)
    res = authenticated_client.get(URL)
    expected = sorted(rows, key=lambda ticket: str(ticket.pk), reverse=True)
    assert _references(res) == [t.reference for t in expected]


def test_listing_warns_of_no_unordered_pagination(authenticated_client, tickets):
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnorderedObjectListWarning)
        res = authenticated_client.get(URL)
    assert res.status_code == 200


@pytest.mark.parametrize(
    ("ordering", "expected"),
    [("updated_at", (1, 2, 0)), ("-updated_at", (0, 2, 1)), ("created_at", (0, 2, 1))],
)
def test_client_ordering_still_wins(authenticated_client, tickets, ordering, expected):
    res = authenticated_client.get(URL, {"ordering": ordering})
    assert _references(res) == [tickets[index].reference for index in expected]
