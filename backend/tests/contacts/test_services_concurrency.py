"""Identity service against real concurrent transactions.

Each test opens a second connection, holds the contact's row while the service
blocks on it, then commits an anonymization: the service must act on the
committed row and never write the old one back.
"""

import time
from concurrent.futures import Future, ThreadPoolExecutor

import pytest
from django.db import connection, connections, transaction

from apps.contacts.models import Contact
from apps.contacts.services import (
    resolve_contact_for_email,
    resolve_contact_for_widget_session,
)
from apps.tickets.models import WidgetSession
from tests.factories import ContactFactory, OrganizationFactory

pytestmark = pytest.mark.django_db(transaction=True)

ANONYMIZED = {
    "email": "anonymized-abc@example.invalid",
    "declared_email": "",
    "name": "Anonymized contact",
    "external_id": "",
    "attributes": {},
    "is_anonymized": True,
}


def _row(contact: Contact) -> dict:
    return Contact.objects.filter(pk=contact.pk).values()[0]


def _wait_until_blocked_on_a_lock(worker: Future, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert not worker.done(), "the service didn't wait for the lock"
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_locks WHERE NOT granted")
            if cursor.fetchone()[0]:
                return
        time.sleep(0.01)
    pytest.fail("the service never waited for the contact's row")


def _run_while_anonymizing(
    contact: Contact, service, changes: dict | None = None
) -> tuple[dict, object]:
    """Run ``service`` in a second connection, anonymizing while it's blocked.

    Return the anonymized row as committed, and what the service returned.
    """

    def run():
        try:
            return service()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            Contact.objects.select_for_update().get(pk=contact.pk)
            worker = executor.submit(run)
            _wait_until_blocked_on_a_lock(worker)
            Contact.objects.filter(pk=contact.pk).update(**(changes or ANONYMIZED))
        committed = _row(contact)
        return committed, worker.result(timeout=10)


def _session(org, **kwargs):
    return WidgetSession.objects.create(organization=org, **kwargs)


@pytest.fixture
def org():
    return OrganizationFactory()


def test_identified_session_does_not_undo_the_anonymization(org):
    contact = ContactFactory(
        organization=org, external_id="u1", name="", email="", attributes={"a": 1}
    )
    session = _session(org, external_user_id="u1", name="Alice", email="a@x.io")

    committed, result = _run_while_anonymizing(
        contact, lambda: resolve_contact_for_widget_session(session)
    )

    assert _row(contact) == committed
    assert committed["is_anonymized"] is True
    assert result != contact
    assert (result.external_id, result.declared_email) == ("u1", "a@x.io")


def test_proof_on_the_email_contact_does_not_attach_to_the_anonymized_one(org):
    contact = ContactFactory(organization=org, email="a@x.io", name="Alice")
    session = _session(org, external_user_id="u1", email="a@x.io")

    committed, result = _run_while_anonymizing(
        contact,
        lambda: resolve_contact_for_widget_session(session, email_verified=True),
    )

    assert _row(contact) == committed
    assert result != contact
    assert (result.external_id, result.email) == ("u1", "a@x.io")


def test_anonymous_session_recreates_the_email_instead_of_linking_the_old_row(org):
    contact = ContactFactory(organization=org, email="a@x.io", name="Alice")
    session = _session(org, email="a@x.io")

    committed, result = _run_while_anonymizing(
        contact, lambda: resolve_contact_for_widget_session(session)
    )

    session.refresh_from_db()
    assert _row(contact) == committed
    assert result != contact
    assert session.contact == result


def test_anonymized_row_matching_the_same_identifiers_gives_no_contact(org):
    """Re-checked under the lock, even if the anonymization kept the identifier."""
    contact = ContactFactory(organization=org, external_id="u1", name="")
    linked = _session(org, external_user_id="u1", name="Alice", contact=contact)

    committed, result = _run_while_anonymizing(
        contact,
        lambda: resolve_contact_for_widget_session(linked),
        changes={"is_anonymized": True, "name": "Anonymized contact"},
    )

    linked.refresh_from_db()
    assert result is None
    assert _row(contact) == committed
    assert linked.contact is None


def test_inbound_mail_does_not_return_the_anonymized_contact(org):
    contact = ContactFactory(organization=org, email="a@x.io", name="Alice")

    committed, result = _run_while_anonymizing(
        contact, lambda: resolve_contact_for_email(org, "a@x.io", name="Alice")
    )

    assert _row(contact) == committed
    assert result != contact
    assert result.email == "a@x.io"
