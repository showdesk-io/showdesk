"""Contacts API against real concurrent transactions.

As in test_services_concurrency.py, the request runs in a second connection and
waits on a transaction this test holds, then commits. These requests read the
contact before they block, so they have to act on the committed row.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections, transaction
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from tests.contacts.test_services_concurrency import (
    ANONYMIZED,
    _row,
    _wait_until_blocked_on_a_lock,
)
from tests.factories import ContactFactory

pytestmark = pytest.mark.django_db(transaction=True)
URL = "/api/v1/contacts/"


def _lock(contact: Contact):
    return lambda: Contact.objects.select_for_update().get(pk=contact.pk)


def _race(hold, request, then=None):
    """Run ``request`` in a second connection until it waits for what ``hold`` took.

    Commit ``then`` along with ``hold``, and return the request's response.
    """

    def run():
        try:
            return request()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            hold()
            worker = executor.submit(run)
            _wait_until_blocked_on_a_lock(worker)
            if then:
                then()
        return worker.result(timeout=10)


@pytest.fixture
def client(agent) -> APIClient:
    client = APIClient()
    client.force_authenticate(agent)
    return client


def test_patch_doesnt_undo_an_anonymization(client, organization):
    contact = ContactFactory(organization=organization, name="Alice", phone="+33")

    res = _race(
        _lock(contact),
        lambda: client.patch(
            f"{URL}{contact.id}/", {"job_title": "CTO", "name": "Bob"}, format="json"
        ),
        lambda: Contact.objects.filter(pk=contact.pk).update(**ANONYMIZED, phone=""),
    )

    assert res.status_code == 409
    row = _row(contact)
    assert row["name"] == ANONYMIZED["name"]
    assert row["email"] == ANONYMIZED["email"]
    assert (row["phone"], row["job_title"], row["is_anonymized"]) == ("", "", True)


def test_patch_keeps_a_change_committed_while_it_waited(client, organization):
    contact = ContactFactory(organization=organization, phone="+33", name="Alice")

    res = _race(
        _lock(contact),
        lambda: client.patch(f"{URL}{contact.id}/", {"name": "Bob"}, format="json"),
        lambda: Contact.objects.filter(pk=contact.pk).update(phone="+44"),
    )

    assert res.status_code == 200
    assert res.data["phone"] == "+44"
    row = _row(contact)
    assert (row["name"], row["phone"]) == ("Bob", "+44")


def test_patch_of_a_contact_deleted_meanwhile_is_404(client, organization):
    contact = ContactFactory(organization=organization)

    res = _race(
        _lock(contact),
        lambda: client.patch(f"{URL}{contact.id}/", {"name": "Bob"}, format="json"),
        lambda: Contact.objects.filter(pk=contact.pk).delete(),
    )

    assert res.status_code == 404
    assert not Contact.objects.filter(pk=contact.pk).exists()


def test_patch_checks_the_email_once_it_holds_the_row(client, organization):
    contact = ContactFactory(organization=organization, email="a@x.io")

    res = _race(
        _lock(contact),
        lambda: client.patch(
            f"{URL}{contact.id}/", {"email": "dup@x.io"}, format="json"
        ),
        lambda: ContactFactory(organization=organization, email="dup@x.io"),
    )

    assert res.status_code == 400
    assert _row(contact)["email"] == "a@x.io"


def test_patch_losing_the_email_race_at_the_constraint_is_400(client, organization):
    """The other insert isn't committed yet: the check passes, the write has to wait."""
    contact = ContactFactory(organization=organization, email="a@x.io")

    res = _race(
        lambda: ContactFactory(organization=organization, email="dup@x.io"),
        lambda: client.patch(
            f"{URL}{contact.id}/", {"email": "dup@x.io"}, format="json"
        ),
    )

    assert res.status_code == 400
    assert "email" in res.data
    assert _row(contact)["email"] == "a@x.io"


def test_create_losing_the_email_race_at_the_constraint_is_400(client, organization):
    res = _race(
        lambda: ContactFactory(organization=organization, email="dup@x.io"),
        lambda: client.post(URL, {"email": "DUP@x.io"}, format="json"),
    )

    assert res.status_code == 400
    assert "email" in res.data
    assert Contact.objects.filter(organization=organization).count() == 1


def test_delete_waits_for_the_contact_lock(admin_client, organization):
    contact = ContactFactory(organization=organization)

    res = _race(_lock(contact), lambda: admin_client.delete(f"{URL}{contact.id}/"))

    assert res.status_code == 204
    assert not Contact.objects.filter(pk=contact.pk).exists()


def test_delete_of_a_contact_deleted_meanwhile_is_no_error(admin_client, organization):
    contact = ContactFactory(organization=organization)

    res = _race(
        _lock(contact),
        lambda: admin_client.delete(f"{URL}{contact.id}/"),
        lambda: Contact.objects.filter(pk=contact.pk).delete(),
    )

    assert res.status_code == 204


def test_note_doesnt_land_on_a_contact_anonymized_meanwhile(client, organization):
    contact = ContactFactory(organization=organization)

    res = _race(
        _lock(contact),
        lambda: client.post(f"{URL}{contact.id}/notes/", {"body": "x"}, format="json"),
        lambda: Contact.objects.filter(pk=contact.pk).update(**ANONYMIZED),
    )

    assert res.status_code == 409
    assert not contact.notes.exists()
