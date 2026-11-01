"""Companies API against real concurrent transactions (see test_contacts_api_concurrency)."""

import pytest
from django.db.models.signals import post_delete
from rest_framework.test import APIClient

from apps.contacts.models import Company, Contact
from tests.contacts.test_contacts_api_concurrency import _race
from tests.factories import CompanyFactory, ContactFactory

pytestmark = pytest.mark.django_db(transaction=True)
URL = "/api/v1/companies/"


def _lock(company: Company):
    return lambda: Company.objects.select_for_update().get(pk=company.pk)


@pytest.fixture
def client(agent) -> APIClient:
    client = APIClient()
    client.force_authenticate(agent)
    return client


def test_create_losing_the_domain_race_at_the_constraint_is_400(client, organization):
    res = _race(
        lambda: CompanyFactory(organization=organization, domain="dup.io"),
        lambda: client.post(URL, {"name": "A", "domain": "DUP.io"}, format="json"),
    )

    assert res.status_code == 400
    assert "domain" in res.data
    assert Company.objects.filter(organization=organization).count() == 1


def test_patch_losing_the_domain_race_at_the_constraint_is_400(client, organization):
    company = CompanyFactory(organization=organization, domain="a.io")

    res = _race(
        lambda: CompanyFactory(organization=organization, domain="dup.io"),
        lambda: client.patch(
            f"{URL}{company.id}/", {"domain": "dup.io"}, format="json"
        ),
    )

    assert res.status_code == 400
    assert "domain" in res.data
    assert Company.objects.get(pk=company.pk).domain == "a.io"


def test_patch_checks_the_domain_once_it_holds_the_row(client, organization):
    company = CompanyFactory(organization=organization, domain="a.io")

    res = _race(
        _lock(company),
        lambda: client.patch(
            f"{URL}{company.id}/", {"domain": "dup.io"}, format="json"
        ),
        lambda: CompanyFactory(organization=organization, domain="dup.io"),
    )

    assert res.status_code == 400
    assert Company.objects.get(pk=company.pk).domain == "a.io"


def test_patch_keeps_a_change_committed_while_it_waited(client, organization):
    company = CompanyFactory(organization=organization, plan="old", name="A")

    res = _race(
        _lock(company),
        lambda: client.patch(f"{URL}{company.id}/", {"name": "B"}, format="json"),
        lambda: Company.objects.filter(pk=company.pk).update(plan="new"),
    )

    assert res.status_code == 200
    assert res.data["plan"] == "new"
    row = Company.objects.get(pk=company.pk)
    assert (row.name, row.plan) == ("B", "new")


def test_patch_of_a_company_deleted_meanwhile_is_404(client, organization):
    company = CompanyFactory(organization=organization)

    res = _race(
        _lock(company),
        lambda: client.patch(f"{URL}{company.id}/", {"name": "B"}, format="json"),
        lambda: Company.objects.filter(pk=company.pk).delete(),
    )

    assert res.status_code == 404


def test_delete_of_a_company_linked_while_deleting_is_a_409(admin_client, organization):
    """The contact arrives once the delete has unlinked the others: the foreign key,
    checked when the delete commits, refuses it."""
    company = CompanyFactory(organization=organization)
    contact = ContactFactory(organization=organization)

    def link(**kwargs):
        Contact.objects.filter(pk=contact.pk).update(company=company)

    post_delete.connect(link, sender=Company)
    try:
        res = admin_client.delete(f"{URL}{company.id}/")
    finally:
        post_delete.disconnect(link, sender=Company)

    assert res.status_code == 409
    assert Company.objects.filter(pk=company.pk).exists()
