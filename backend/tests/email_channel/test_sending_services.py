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

from apps.email_channel.models import SendingRemoval
from apps.email_channel.sending import services
from apps.email_channel.sending.providers import (
    AlreadyRegisteredError,
    CheckStatus,
    DomainCheck,
    RegisteredDomain,
    SendingProviderError,
)
from apps.organizations.models import OrganizationDomain
from tests.factories import AdminFactory, MailboxFactory, OrganizationFactory

pytestmark = pytest.mark.django_db

RECORDS = [{"type": "TXT", "name": "acme.com", "value": "v=spf1 include:x ~all"}]
Sending = OrganizationDomain.SendingStatus


class FakeProvider:
    """Registers every domain as `ref-<domain>`, answers checks with `result`."""

    def __init__(self) -> None:
        self.result = DomainCheck(CheckStatus.PENDING, "SPF: add include:x.")
        self.calls: list[tuple[str, str]] = []
        self.fail: set[str] = set()
        self.on_register = None  # Run while registering, as if meanwhile.

    def _call(self, name: str, arg: str) -> None:
        self.calls.append((name, arg))
        if name in self.fail:
            raise SendingProviderError(f"{name} failed")

    def register(self, domain: str) -> RegisteredDomain:
        self._call("register", domain)
        if self.on_register:
            self.on_register()
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

    def test_waits_for_a_previous_registration_to_be_removed(
        self, provider, organization
    ) -> None:
        SendingRemoval.objects.create(domain="acme.com", ref="ref-old")
        row = domain_row(organization)

        with pytest.raises(services.RemovalPendingError):
            services.enable_sending(row)
        assert provider.calls == []

        # The provider still knowing the name is the same answer.
        SendingRemoval.objects.all().delete()
        with (
            mock.patch.object(
                provider, "register", side_effect=AlreadyRegisteredError("taken")
            ),
            pytest.raises(services.RemovalPendingError),
        ):
            services.enable_sending(row)

    def test_a_registration_that_is_not_stored_is_removed(
        self, provider, organization
    ) -> None:
        row = domain_row(organization)
        provider.on_register = lambda: OrganizationDomain.objects.filter(
            pk=row.pk
        ).delete()

        with pytest.raises(services.NotOwnedError):
            services.enable_sending(row)
        assert SendingRemoval.objects.filter(ref="ref-acme.com").exists()

        SendingRemoval.objects.all().delete()
        provider.on_register = None
        row = domain_row(organization)
        with (
            mock.patch.object(OrganizationDomain, "save", side_effect=RuntimeError),
            pytest.raises(RuntimeError),
        ):
            services.enable_sending(row)
        assert SendingRemoval.objects.filter(ref="ref-acme.com").exists()

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
        assert not SendingRemoval.objects.exists()


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
        assert not SendingRemoval.objects.exists()

    def test_a_failed_removal_is_recorded_and_queued(
        self, provider, organization
    ) -> None:
        provider.fail = {"remove"}
        row = registered_row(organization, sending_status=Sending.VERIFIED)

        with mock.patch(
            "apps.email_channel.tasks.remove_sending_registration.delay"
        ) as delay:
            services.disable_sending(row)

        removal = SendingRemoval.objects.get()
        assert (removal.domain, removal.ref, removal.attempts) == (
            "acme.com",
            "ref-acme.com",
            1,
        )
        assert removal.last_error == "remove failed"
        delay.assert_called_once_with(removal.pk)
        row.refresh_from_db()
        assert row.sending_status == ""
        assert row.sending_provider_ref == ""


class TestRemovalTask:
    def test_a_done_removal_is_forgotten(self, provider) -> None:
        from apps.email_channel.tasks import remove_sending_registration

        removal = SendingRemoval.objects.create(domain="acme.com", ref="ref-old")

        remove_sending_registration(removal.pk)

        assert provider.calls == [("remove", "ref-old")]
        assert not SendingRemoval.objects.exists()

    def test_retries_while_the_provider_fails_then_gives_up(
        self, provider, caplog
    ) -> None:
        from celery.exceptions import Retry

        from apps.email_channel.tasks import remove_sending_registration

        provider.fail = {"remove"}
        removal = SendingRemoval.objects.create(domain="acme.com", ref="ref-old")
        with (
            mock.patch.object(
                remove_sending_registration, "retry", side_effect=Retry
            ) as retry,
            pytest.raises(Retry),
        ):
            remove_sending_registration(removal.pk)
        assert retry.call_args.kwargs["countdown"] > 0
        removal.refresh_from_db()
        assert removal.attempts == 1

        SendingRemoval.objects.filter(pk=removal.pk).update(
            attempts=services.MAX_REMOVAL_ATTEMPTS - 1
        )
        with mock.patch.object(remove_sending_registration, "retry") as retry:
            remove_sending_registration(removal.pk)
        retry.assert_not_called()
        assert "ref-old" in caplog.text
        assert any(r.levelname == "ERROR" for r in caplog.records)
        assert SendingRemoval.objects.filter(pk=removal.pk).exists()

    def test_without_a_provider_the_removal_waits(self, settings) -> None:
        from apps.email_channel.tasks import remove_sending_registration

        settings.SENDING_DOMAIN_PROVIDER = "none"
        removal = SendingRemoval.objects.create(domain="acme.com", ref="ref-old")

        with mock.patch.object(remove_sending_registration, "retry") as retry:
            remove_sending_registration(removal.pk)

        retry.assert_not_called()
        removal.refresh_from_db()
        assert removal.attempts == 0

    def test_the_sweep_requeues_what_was_lost_or_given_up(self) -> None:
        from apps.email_channel.tasks import requeue_sending_removals

        old = timezone.now() - timedelta(hours=2)
        lost = SendingRemoval.objects.create(domain="a.com", ref="1", created_at=old)
        given_up = SendingRemoval.objects.create(
            domain="b.com",
            ref="2",
            created_at=old,
            attempts=services.MAX_REMOVAL_ATTEMPTS,
        )
        SendingRemoval.objects.create(domain="c.com", ref="3")  # Just queued.
        SendingRemoval.objects.create(  # Still retrying.
            domain="d.com", ref="4", created_at=old, attempts=2
        )

        with mock.patch(
            "apps.email_channel.tasks.remove_sending_registration.delay"
        ) as delay:
            requeue_sending_removals()

        assert sorted(c.args[0] for c in delay.call_args_list) == sorted(
            [lost.pk, given_up.pk]
        )


class TestOwnershipVerified:
    def test_a_dns_win_frees_the_previous_owner(
        self, provider, organization, django_capture_on_commit_callbacks
    ) -> None:
        from apps.organizations import services as domains

        previous = registered_row(
            OrganizationFactory(), sending_status=Sending.VERIFIED
        )
        theirs = MailboxFactory(
            organization=previous.organization, public_address="support@acme.com"
        )
        elsewhere = MailboxFactory(
            organization=previous.organization, public_address="help@other.com"
        )
        challenge = domains.start_dns_challenge(
            organization=organization, domain="acme.com", is_branding=True
        )

        with (
            mock.patch(
                "apps.organizations.dns_verification.lookup_txt",
                return_value=[challenge.txt_record_value],
            ),
            mock.patch(
                "apps.email_channel.tasks.remove_sending_registration.delay"
            ) as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            assert domains.perform_dns_check(challenge) is True

        theirs.refresh_from_db()
        elsewhere.refresh_from_db()
        previous.refresh_from_db()
        assert theirs.public_address == ""
        assert elsewhere.public_address == "help@other.com"
        assert previous.status == OrganizationDomain.Status.FAILED
        assert previous.sending_status == ""
        assert previous.is_sending is True
        assert previous.sending_provider_ref == ""
        removal = SendingRemoval.objects.get(ref="ref-acme.com")
        delay.assert_called_once_with(removal.pk)

    def test_an_admin_email_verification_frees_a_squatter(
        self, provider, organization, django_capture_on_commit_callbacks
    ) -> None:
        from apps.organizations import services as domains

        squatter = MailboxFactory(public_address="support@acme.com")
        AdminFactory(organization=organization, email="ceo@acme.com", is_verified=True)

        with django_capture_on_commit_callbacks(execute=True):
            domains.try_admin_email_autoverify(
                organization=organization, domain="acme.com", is_email_routing=True
            )

        squatter.refresh_from_db()
        assert squatter.public_address == ""

    def test_freeing_is_part_of_the_verification_and_spares_the_winner(
        self, provider, organization
    ) -> None:
        """No commit callback needed, and the winner's own setup stays."""
        from apps.organizations import services as domains

        previous = domain_row(
            OrganizationFactory(), is_sending=True, sending_status=Sending.VERIFIED
        )
        squatter = MailboxFactory(
            organization=previous.organization, public_address="support@acme.com"
        )
        # The winner had set sending up, then asked for a new token.
        winner = registered_row(organization, status=OrganizationDomain.Status.PENDING)
        winner.verification_method = OrganizationDomain.VerificationMethod.DNS_TXT
        winner.verification_token = "token"
        winner.save()

        with mock.patch(
            "apps.organizations.dns_verification.lookup_txt",
            return_value=[winner.txt_record_value],
        ):
            assert domains.perform_dns_check(winner) is True

        squatter.refresh_from_db()
        previous.refresh_from_db()
        winner.refresh_from_db()
        assert squatter.public_address == ""
        assert previous.sending_status == ""
        assert winner.status == OrganizationDomain.Status.VERIFIED
        assert winner.sending_status == Sending.PENDING
        assert winner.sending_provider_ref == "ref-acme.com"

    def test_a_stale_call_for_a_row_no_longer_verified_does_nothing(
        self, provider, organization
    ) -> None:
        lost = domain_row(organization, status=OrganizationDomain.Status.FAILED)
        other = registered_row(OrganizationFactory(), sending_status=Sending.VERIFIED)
        theirs = MailboxFactory(
            organization=other.organization, public_address="support@acme.com"
        )

        services.on_ownership_verified(lost)

        theirs.refresh_from_db()
        other.refresh_from_db()
        assert theirs.public_address == "support@acme.com"
        assert other.sending_status == Sending.VERIFIED

    def test_deleting_a_registered_domain_removes_its_registration(
        self, provider, organization, admin_client, django_capture_on_commit_callbacks
    ) -> None:
        row = registered_row(organization, sending_status=Sending.VERIFIED)
        other = OrganizationFactory()
        domain_row(
            other,
            domain="other.com",
            status=OrganizationDomain.Status.FAILED,
            sending_provider_ref="ref-other.com",
        )

        with (
            mock.patch(
                "apps.email_channel.tasks.remove_sending_registration.delay"
            ) as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = admin_client.delete(f"/api/v1/organization-domains/{row.id}/")
            other.delete()  # Its rows go by cascade.

        assert response.status_code == 204
        removals = SendingRemoval.objects.order_by("ref")
        assert [(r.domain, r.ref) for r in removals] == [
            ("acme.com", "ref-acme.com"),
            ("other.com", "ref-other.com"),
        ]
        assert sorted(c.args[0] for c in delay.call_args_list) == sorted(
            r.pk for r in removals
        )
