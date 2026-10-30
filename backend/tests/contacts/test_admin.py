"""Tests for the admin integration of contacts."""

import pytest
from django.urls import reverse

from tests.factories import ContactFactory, TicketFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_ticket_change_page_does_not_list_every_contact(client):
    own = ContactFactory(name="Own Org Contact")
    other = ContactFactory(name="Foreign Org Contact")
    ticket = TicketFactory(organization=own.organization, contact=own)
    client.force_login(UserFactory(is_staff=True, is_superuser=True))

    response = client.get(reverse("admin:tickets_ticket_change", args=[ticket.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert own.name in content
    assert other.name not in content
