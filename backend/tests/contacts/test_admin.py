"""Tests for the admin integration of contacts."""

import pytest
from django.urls import reverse

from apps.contacts.models import CompanyAttributeDef, ContactAttributeDef
from tests.factories import (
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
    UserFactory,
)

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


def _add_definition(client, model, **fields):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client.post(
        reverse(f"admin:contacts_{model._meta.model_name}_add"),
        {
            "organization": str(OrganizationFactory().id),
            "key": "plan",
            "label": "Plan",
            "position": 0,
            **fields,
        },
    )


@pytest.mark.parametrize(
    ("model", "type_", "options"),
    [
        (ContactAttributeDef, "enum", '["a", ""]'),
        (CompanyAttributeDef, "string", '["a"]'),
    ],
)
def test_admin_refuses_invalid_options(client, model, type_, options):
    response = _add_definition(client, model, type=type_, options=options)
    assert response.status_code == 200
    assert response.context["adminform"].form.errors["options"]
    assert not model.objects.exists()


@pytest.mark.parametrize(
    ("type_", "options", "stored"),
    [
        ("enum", '["free", "pro"]', ["free", "pro"]),
        ("string", "[]", []),
        ("string", "", []),
    ],
)
def test_admin_accepts_valid_options(client, type_, options, stored):
    response = _add_definition(client, ContactAttributeDef, type=type_, options=options)
    assert response.status_code == 302
    assert ContactAttributeDef.objects.get().options == stored
