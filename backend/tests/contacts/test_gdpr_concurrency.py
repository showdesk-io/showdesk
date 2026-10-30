"""Anonymization against real concurrent transactions.

As in test_contacts_api_concurrency.py: the request runs in a second connection and
waits on a transaction this test holds.
"""

import pytest
from rest_framework.test import APIClient

from apps.contacts.gdpr import anonymize_contact
from apps.tickets.models import WidgetSession
from tests.contacts.test_contacts_api_concurrency import _lock, _race
from tests.contacts.test_services_concurrency import ANONYMIZED, _row
from tests.factories import ContactFactory

pytestmark = pytest.mark.django_db(transaction=True)
URL = "/api/v1/contacts/"


@pytest.fixture
def client(agent) -> APIClient:
    client = APIClient()
    client.force_authenticate(agent)
    return client


def test_anonymize_waits_for_the_contact_lock(admin_client, organization):
    contact = ContactFactory(organization=organization, name="Alice", phone="+33")
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, email="a@x.io"
    )

    res = _race(
        _lock(contact), lambda: admin_client.post(f"{URL}{contact.id}/anonymize/")
    )

    assert res.status_code == 200
    row = _row(contact)
    assert (row["is_anonymized"], row["name"]) == (True, "Anonymized contact")
    session.refresh_from_db()
    assert session.email == ""


def test_anonymize_acts_on_the_committed_row(admin_client, organization):
    """What was committed while it waited is scrubbed too, not written back."""
    contact = ContactFactory(organization=organization, phone="+33")

    res = _race(
        _lock(contact),
        lambda: admin_client.post(f"{URL}{contact.id}/anonymize/"),
        lambda: type(contact).objects.filter(pk=contact.pk).update(job_title="CTO"),
    )

    assert res.status_code == 200
    row = _row(contact)
    assert (row["phone"], row["job_title"]) == ("", "")


def test_anonymize_waiting_on_another_one_changes_nothing(admin_client, organization):
    contact = ContactFactory(organization=organization)

    res = _race(
        _lock(contact),
        lambda: admin_client.post(f"{URL}{contact.id}/anonymize/"),
        lambda: type(contact).objects.filter(pk=contact.pk).update(**ANONYMIZED),
    )

    assert res.status_code == 200
    assert _row(contact)["email"] == ANONYMIZED["email"]


def test_anonymize_of_a_contact_deleted_meanwhile_is_404(admin_client, organization):
    contact = ContactFactory(organization=organization)

    res = _race(
        _lock(contact),
        lambda: admin_client.post(f"{URL}{contact.id}/anonymize/"),
        lambda: type(contact).objects.filter(pk=contact.pk).delete(),
    )

    assert res.status_code == 404


def test_patch_waiting_on_a_real_anonymization_is_a_409(client, organization):
    contact = ContactFactory(organization=organization, name="Alice")

    res = _race(
        _lock(contact),
        lambda: client.patch(f"{URL}{contact.id}/", {"name": "Bob"}, format="json"),
        lambda: anonymize_contact(contact),
    )

    assert res.status_code == 409
    assert _row(contact)["name"] == "Anonymized contact"
