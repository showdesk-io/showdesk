"""The periodic check of sending domains, and the admins' mails (§7.3).

The provider is a fake object put in place of the configured one at
`get_provider`, as in test_sending_services: these tests are about which rows
are checked, what they become, and who hears about it.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.utils import timezone

from apps.email_channel.sending.providers import CheckStatus, DomainCheck
from apps.email_channel.sending.services import sendable_address
from apps.email_channel.tasks import check_sending_domains
from apps.organizations.models import OrganizationDomain
from tests.factories import AdminFactory, MailboxFactory, UserFactory

pytestmark = pytest.mark.django_db

Sending = OrganizationDomain.SendingStatus


class FakeProvider:
    """Answers every check with `result`, and remembers the refs checked."""

    def __init__(self) -> None:
        self.result = DomainCheck(CheckStatus.VERIFIED)
        self.checked: list[str] = []

    def check(self, ref: str) -> DomainCheck:
        self.checked.append(ref)
        return self.result


@pytest.fixture
def provider(settings):
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    fake = FakeProvider()
    with mock.patch(
        "apps.email_channel.sending.services.get_provider", return_value=fake
    ):
        yield fake


@pytest.fixture
def admin(organization):
    return AdminFactory(organization=organization, email="admin@acme.com")


@pytest.fixture
def mailbox(organization):
    return MailboxFactory(organization=organization, public_address="support@acme.com")


def sending_row(organization, status, **fields) -> OrganizationDomain:
    return OrganizationDomain.objects.create(
        organization=organization,
        domain=fields.pop("domain", "acme.com"),
        is_branding=True,
        status=OrganizationDomain.Status.VERIFIED,
        is_sending=True,
        sending_status=status,
        sending_provider_ref=fields.pop("ref", "ref-acme.com"),
        sending_requested_at=fields.pop(
            "requested_at", timezone.now() - timedelta(hours=1)
        ),
        **fields,
    )


def run_task(capture) -> int:
    with capture(execute=True):
        return check_sending_domains()


def test_a_pending_domain_once_verified_mails_once_and_sends_from_it(
    provider, organization, admin, mailbox, django_capture_on_commit_callbacks
) -> None:
    UserFactory(organization=organization, role="agent", email="agent@acme.com")
    row = sending_row(organization, Sending.PENDING)
    assert sendable_address(mailbox) is None

    assert run_task(django_capture_on_commit_callbacks) == 1
    row.refresh_from_db()
    assert row.sending_status == Sending.VERIFIED
    assert sendable_address(mailbox) == "support@acme.com"
    [sent] = mail.outbox
    assert sent.to == ["admin@acme.com"]
    assert sent.subject == "You now send from acme.com"

    run_task(django_capture_on_commit_callbacks)
    assert len(mail.outbox) == 1  # Checked again tomorrow, not now.


def test_a_verified_domain_whose_records_went_is_pending_again(
    provider, organization, admin, mailbox, django_capture_on_commit_callbacks
) -> None:
    long_ago = timezone.now() - timedelta(days=10)
    row = sending_row(
        organization,
        Sending.VERIFIED,
        requested_at=long_ago,
        sending_last_checked_at=timezone.now() - timedelta(hours=25),
    )
    provider.result = DomainCheck(CheckStatus.PENDING, "SPF: add include:x.")

    run_task(django_capture_on_commit_callbacks)

    row.refresh_from_db()
    assert row.sending_status == Sending.PENDING
    assert row.sending_requested_at > timezone.now() - timedelta(minutes=1)
    assert sendable_address(mailbox) is None
    [sent] = mail.outbox
    assert sent.subject == (
        "Sending from acme.com stopped: we will keep checking for 72 hours"
    )
    assert "SPF: add include:x." in sent.body


def test_a_failed_result_fails_a_verified_domain(
    provider, organization, admin, django_capture_on_commit_callbacks
) -> None:
    row = sending_row(organization, Sending.VERIFIED)
    provider.result = DomainCheck(CheckStatus.FAILED, "The domain was revoked.")

    run_task(django_capture_on_commit_callbacks)

    row.refresh_from_db()
    assert row.sending_status == Sending.FAILED
    [sent] = mail.outbox
    assert sent.subject == "Sending from acme.com failed"
    assert "The domain was revoked." in sent.body


def test_a_domain_pending_for_72_hours_fails(
    provider, organization, admin, django_capture_on_commit_callbacks
) -> None:
    row = sending_row(
        organization,
        Sending.PENDING,
        requested_at=timezone.now() - timedelta(hours=73),
    )
    provider.result = DomainCheck(CheckStatus.PENDING, "DKIM: publish the CNAME.")

    run_task(django_capture_on_commit_callbacks)

    row.refresh_from_db()
    assert row.sending_status == Sending.FAILED
    assert "DKIM: publish the CNAME." in row.sending_last_error
    [sent] = mail.outbox
    assert sent.subject == "Sending from acme.com failed"
    assert "DKIM: publish the CNAME." in sent.body

    run_task(django_capture_on_commit_callbacks)
    assert provider.checked == ["ref-acme.com"]  # Failed rows wait for an admin.


def test_a_check_that_cannot_conclude_changes_nothing(
    provider, organization, admin, django_capture_on_commit_callbacks
) -> None:
    pending = sending_row(
        organization,
        Sending.PENDING,
        requested_at=timezone.now() - timedelta(hours=73),
    )
    verified = sending_row(organization, Sending.VERIFIED, domain="acme.org", ref="r2")
    provider.result = DomainCheck(CheckStatus.UNKNOWN)

    assert run_task(django_capture_on_commit_callbacks) == 2

    pending.refresh_from_db()
    verified.refresh_from_db()
    assert pending.sending_status == Sending.PENDING
    assert verified.sending_status == Sending.VERIFIED
    assert mail.outbox == []


def test_nothing_is_checked_without_a_provider(
    provider, organization, settings, django_capture_on_commit_callbacks
) -> None:
    sending_row(organization, Sending.PENDING)
    settings.SENDING_DOMAIN_PROVIDER = "none"

    assert run_task(django_capture_on_commit_callbacks) == 0
    assert provider.checked == []
