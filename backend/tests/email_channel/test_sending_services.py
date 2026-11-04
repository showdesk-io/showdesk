"""Sending domain services: enable, check, disable a domain's sending (§7).

The provider is a fake object put in place of the configured one at
`get_provider`: these tests are about what the services store, not about
what a provider asks to publish (see test_sending_providers).
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.email_channel.sending import services
from apps.email_channel.sending.providers import (
    CheckStatus,
    DomainCheck,
    RegisteredDomain,
    SendingProviderError,
)
from apps.organizations.models import OrganizationDomain
from tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db

RECORDS = [{"type": "TXT", "name": "acme.com", "value": "v=spf1 include:x ~all"}]
Sending = OrganizationDomain.SendingStatus


class FakeProvider:
    """Registers every domain as `ref-<domain>`, answers checks with `result`."""

    def __init__(self) -> None:
        self.result = DomainCheck(CheckStatus.PENDING, "SPF: add include:x.")
        self.calls: list[tuple[str, str]] = []
        self.fail: set[str] = set()

    def _call(self, name: str, arg: str) -> None:
        self.calls.append((name, arg))
        if name in self.fail:
            raise SendingProviderError(f"{name} failed")

    def register(self, domain: str) -> RegisteredDomain:
        self._call("register", domain)
        return RegisteredDomain(ref=f"ref-{domain}", records=RECORDS)

    def check(self, ref: str) -> DomainCheck:
        self._call("check", ref)
        return self.result

    def remove(self, ref: str) -> None:
        self._call("remove", ref)


@pytest.fixture
def provider(settings):
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    fake = FakeProvider()
    with mock.patch(
        "apps.email_channel.sending.services.get_provider", return_value=fake
    ):
        yield fake


def domain_row(organization, **fields) -> OrganizationDomain:
    return OrganizationDomain.objects.create(
        organization=organization,
        domain=fields.pop("domain", "acme.com"),
        is_branding=True,
        status=fields.pop("status", OrganizationDomain.Status.VERIFIED),
        **fields,
    )


def registered_row(organization, **fields) -> OrganizationDomain:
    return domain_row(
        organization,
        is_sending=True,
        sending_status=fields.pop("sending_status", Sending.PENDING),
        sending_provider_ref="ref-acme.com",
        sending_dns_records=RECORDS,
        sending_requested_at=timezone.now() - timedelta(hours=1),
        **fields,
    )


class TestEnable:
    def test_registers_stores_the_records_and_checks_once(
        self, provider, organization
    ) -> None:
        row = domain_row(organization)

        services.enable_sending(row)

        row.refresh_from_db()
        assert provider.calls == [("register", "acme.com"), ("check", "ref-acme.com")]
        assert row.is_sending is True
        assert row.sending_status == Sending.PENDING
        assert row.sending_provider_ref == "ref-acme.com"
        assert row.sending_dns_records == RECORDS
        assert row.sending_requested_at is not None
        assert row.sending_last_checked_at is not None
        assert row.sending_last_error == "SPF: add include:x."

    def test_needs_the_domain_owned(self, provider, organization) -> None:
        row = domain_row(organization, status=OrganizationDomain.Status.PENDING)

        with pytest.raises(services.NotOwnedError):
            services.enable_sending(row)
        assert provider.calls == []

    def test_waits_for_a_previous_owner_registration_to_be_removed(
        self, provider, organization
    ) -> None:
        domain_row(
            OrganizationFactory(),
            status=OrganizationDomain.Status.FAILED,
            sending_provider_ref="ref-old",
        )
        row = domain_row(organization)

        with pytest.raises(services.RemovalPendingError):
            services.enable_sending(row)
        assert provider.calls == []

    def test_a_provider_refusal_stores_nothing(self, provider, organization) -> None:
        provider.fail = {"register"}
        row = domain_row(organization)

        with pytest.raises(services.ProviderError, match="register failed"):
            services.enable_sending(row)

        row.refresh_from_db()
        assert row.sending_status == ""
        assert row.sending_provider_ref == ""

    def test_one_registration_at_a_time_per_domain(
        self, provider, organization
    ) -> None:
        row = domain_row(organization)
        cache.add(services.enable_lock_key("acme.com"), 1, 60)

        with pytest.raises(services.InProgressError):
            services.enable_sending(row)
        assert provider.calls == []

    def test_after_a_failure_the_old_registration_is_replaced(
        self, provider, organization
    ) -> None:
        row = registered_row(organization, sending_status=Sending.FAILED)

        services.enable_sending(row)

        assert provider.calls[:2] == [
            ("remove", "ref-acme.com"),
            ("register", "acme.com"),
        ]
        row.refresh_from_db()
        assert row.sending_status == Sending.PENDING


class TestCheck:
    def test_transitions(self, provider, organization) -> None:
        row = registered_row(organization)

        provider.result = DomainCheck(CheckStatus.VERIFIED)
        assert services.check_sending(row) == CheckStatus.VERIFIED
        row.refresh_from_db()
        assert row.sending_status == Sending.VERIFIED
        assert row.sending_last_error == ""

        # A regression starts a new pending cycle.
        before = row.sending_requested_at
        provider.result = DomainCheck(CheckStatus.PENDING, "DKIM missing.")
        services.check_sending(row)
        row.refresh_from_db()
        assert row.sending_status == Sending.PENDING
        assert row.sending_requested_at > before
        assert row.sending_last_error == "DKIM missing."

        provider.result = DomainCheck(CheckStatus.FAILED, "Locked.")
        services.check_sending(row)
        row.refresh_from_db()
        assert row.sending_status == Sending.FAILED

    def test_a_check_that_cannot_conclude_changes_nothing(
        self, provider, organization
    ) -> None:
        row = registered_row(organization, sending_status=Sending.VERIFIED)
        provider.fail = {"check"}

        assert services.check_sending(row) == CheckStatus.UNKNOWN

        row.refresh_from_db()
        assert row.sending_status == Sending.VERIFIED
        assert row.sending_last_error == ""
        assert row.sending_last_checked_at is not None

    def test_newer_records_replace_the_stored_ones(
        self, provider, organization
    ) -> None:
        row = registered_row(organization)
        newer = [{"type": "TXT", "name": "acme.com", "value": "v=spf1 -all"}]
        provider.result = DomainCheck(CheckStatus.PENDING, "", newer)

        services.check_sending(row)

        row.refresh_from_db()
        assert row.sending_dns_records == newer

    def test_only_a_registered_owned_domain_is_checked(
        self, provider, organization
    ) -> None:
        with pytest.raises(services.NotRegisteredError):
            services.check_sending(domain_row(organization))
        lost = registered_row(
            OrganizationFactory(), status=OrganizationDomain.Status.FAILED
        )
        with pytest.raises(services.NotOwnedError):
            services.check_sending(lost)
        assert provider.calls == []


class TestDisable:
    def test_removes_and_resets_keeping_the_purpose(
        self, provider, organization
    ) -> None:
        row = registered_row(organization, sending_status=Sending.VERIFIED)

        services.disable_sending(row)

        assert provider.calls == [("remove", "ref-acme.com")]
        row.refresh_from_db()
        assert row.is_sending is True
        assert row.sending_status == ""
        assert row.sending_provider_ref == ""
        assert row.sending_dns_records == []
        assert row.sending_last_error == ""

    def test_a_failed_removal_is_queued_and_the_row_keeps_its_ref(
        self, provider, organization, django_capture_on_commit_callbacks
    ) -> None:
        provider.fail = {"remove"}
        row = registered_row(organization, sending_status=Sending.VERIFIED)

        with (
            mock.patch(
                "apps.email_channel.tasks.remove_sending_registration.delay"
            ) as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            services.disable_sending(row)

        delay.assert_called_once_with("ref-acme.com", str(row.pk))
        row.refresh_from_db()
        assert row.sending_status == ""
        assert row.sending_provider_ref == "ref-acme.com"


class TestRemovalTask:
    def test_clears_the_ref_only_if_the_row_still_holds_it(
        self, provider, organization
    ) -> None:
        from apps.email_channel.tasks import remove_sending_registration

        row = registered_row(organization)
        remove_sending_registration("ref-other", row.pk)
        row.refresh_from_db()
        assert row.sending_provider_ref == "ref-acme.com"

        remove_sending_registration("ref-acme.com", row.pk)
        row.refresh_from_db()
        assert row.sending_provider_ref == ""
        assert provider.calls == [("remove", "ref-other"), ("remove", "ref-acme.com")]

    def test_retries_while_the_provider_fails(self, provider, organization) -> None:
        from celery.exceptions import Retry

        from apps.email_channel.tasks import remove_sending_registration

        provider.fail = {"remove"}
        with (
            mock.patch.object(
                remove_sending_registration, "retry", side_effect=Retry
            ) as retry,
            pytest.raises(Retry),
        ):
            remove_sending_registration("ref-acme.com")
        assert retry.call_args.kwargs["countdown"] > 0
