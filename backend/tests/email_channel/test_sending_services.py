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
TOKEN = "token"


class FakeProvider:
    """Registers every domain as `ref-<domain>`, answers checks with `result`."""

    removal_needed = True

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
    with (
        mock.patch(
            "apps.email_channel.sending.services.get_provider", return_value=fake
        ),
        # The rows' own `_showdesk` TXT is published.
        mock.patch(
            "apps.organizations.dns_verification.lookup_txt",
            return_value=[f"showdesk-verification={TOKEN}"],
        ),
    ):
        yield fake


def domain_row(organization, **fields) -> OrganizationDomain:
    return OrganizationDomain.objects.create(
        organization=organization,
        domain=fields.pop("domain", "acme.com"),
        is_branding=True,
        status=fields.pop("status", OrganizationDomain.Status.VERIFIED),
        verification_token=fields.pop("verification_token", TOKEN),
        **fields,
    )


def registered_row(organization, **fields) -> OrganizationDomain:
    return domain_row(
        organization,
        is_sending=True,
        sending_status=fields.pop("sending_status", Sending.PENDING),
        sending_provider_ref=fields.pop("sending_provider_ref", "ref-acme.com"),
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
        assert row.sending_dns_records == [services.ownership_record(row), *RECORDS]
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

    def test_a_removal_waiting_on_another_provider_does_not_block(
        self, provider, organization
    ) -> None:
        """Set up under `scaleway_tem`, then the operator moved to `manual`:
        TEM's registration waits for TEM, and `manual` registers at once."""
        row = registered_row(
            organization,
            sending_status=Sending.VERIFIED,
            sending_provider="scaleway_tem",
            sending_provider_ref="tem-id",
        )

        services.enable_sending(row)

        row.refresh_from_db()
        assert row.sending_status == Sending.PENDING
        assert row.sending_provider == "manual"
        assert row.sending_provider_ref == "ref-acme.com"
        removal = SendingRemoval.objects.get(ref="tem-id")
        assert removal.provider == "scaleway_tem"

        # TEM answering that it knows the name isn't ours to wait for either.
        services.disable_sending(row)
        with (
            mock.patch.object(
                provider, "register", side_effect=AlreadyRegisteredError("taken")
            ),
            pytest.raises(services.ProviderConflictError),
        ):
            services.enable_sending(row)

    def test_a_name_the_provider_already_holds(
        self, provider, organization, caplog
    ) -> None:
        row = domain_row(organization)

        def taken_while_removing(domain):
            SendingRemoval.objects.get_or_create(domain=domain, ref="ref-old")
            raise AlreadyRegisteredError("taken")

        with (
            mock.patch.object(provider, "register", side_effect=taken_while_removing),
            pytest.raises(services.RemovalPendingError),
        ):
            services.enable_sending(row)

        # Without any removal of ours, someone else holds it: an operator's job.
        SendingRemoval.objects.all().delete()
        with (
            mock.patch.object(
                provider, "register", side_effect=AlreadyRegisteredError("taken")
            ),
            pytest.raises(services.ProviderConflictError) as refused,
        ):
            services.enable_sending(row)
        assert (refused.value.code, refused.value.http_status) == (
            "provider_conflict",
            409,
        )
        assert any(
            r.levelname == "ERROR" and "acme.com" in r.getMessage()
            for r in caplog.records
        )

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

    def test_what_happened_meanwhile_is_respected(self, provider, organization) -> None:
        """A ref stored meanwhile is removed, a lock taken meanwhile kept."""
        row = domain_row(organization)
        key = services.enable_lock_key("acme.com")

        def meanwhile():
            OrganizationDomain.objects.filter(pk=row.pk).update(
                sending_provider_ref="ref-meanwhile"
            )
            cache.set(key, "someone else's", 60)  # Ours expired, theirs began.

        provider.on_register = meanwhile

        services.enable_sending(row)

        row.refresh_from_db()
        assert row.sending_provider_ref == "ref-acme.com"
        assert SendingRemoval.objects.filter(ref="ref-meanwhile").exists()
        assert cache.get(key) == "someone else's"

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

        # A refusal needs no lock: it is told as such, and takes none.
        pending = domain_row(
            OrganizationFactory(), status=OrganizationDomain.Status.PENDING
        )
        with pytest.raises(services.NotOwnedError):
            services.enable_sending(pending)
        with pytest.raises(services.NotOwnedError):
            services.disable_sending(pending)

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


def test_the_instance_own_domains_are_never_sent_from(
    provider, organization, settings
) -> None:
    """The From domain, the site's host, the inbound domain and its subdomains
    are the instance's: a row of one (made before that was refused) can't be
    set up, checked, disabled, nor sent from."""
    settings.DEFAULT_FROM_EMAIL = "Showdesk <noreply@mail.showdesk.test>"
    settings.SITE_URL = "https://app.showdesk.test"
    settings.INBOUND_EMAIL_DOMAIN = "in.showdesk.test"
    for domain in (
        "mail.showdesk.test",
        "app.showdesk.test",
        "in.showdesk.test",
        "eu.in.showdesk.test",
    ):
        row = domain_row(organization, domain=domain)
        with pytest.raises(services.OperatorDomainError) as refused:
            services.enable_sending(row)
        assert (refused.value.code, refused.value.http_status) == (
            "operator_domain",
            400,
        )
        assert str(refused.value) == (
            "This domain is used by the Showdesk instance itself."
        )
        row.delete()
        registered = registered_row(
            organization, domain=domain, sending_status=Sending.VERIFIED
        )
        mailbox = MailboxFactory(
            organization=organization, public_address=f"help@{domain}"
        )
        for service in (
            services.check_sending,
            services.check_now,
            services.disable_sending,
        ):
            with pytest.raises(services.OperatorDomainError):
                service(registered)
        assert services.sendable_domains(organization.id) == set()
        assert services.sendable_address(mailbox) is None
        registered.delete()
        mailbox.delete()
    assert provider.calls == []

    # Only the inbound domain's subdomains: the others may be a customer's.
    services.enable_sending(domain_row(organization, domain="showdesk.test"))
    assert provider.calls[0] == ("register", "showdesk.test")


def test_the_instance_own_domains_are_read_as_written(settings) -> None:
    """A trailing dot, capitals, a SITE_URL without its scheme, a Unicode name:
    still the instance's."""
    settings.DEFAULT_FROM_EMAIL = '"Show, desk" <noreply@Mail.Showdesk.Test.>'
    settings.SITE_URL = "app.bücher.test/"
    assert services.is_operator_domain("mail.showdesk.test")
    assert services.is_operator_domain("app.xn--bcher-kva.test")
    assert not services.is_operator_domain("showdesk.test")


def test_a_registration_on_the_instance_own_domain_is_never_removed(
    provider, organization, settings, caplog
) -> None:
    """Whatever lets go of it (here: the row deleted), the instance's own
    sender stays: no removal recorded, an error logged."""
    settings.DEFAULT_FROM_EMAIL = "noreply@mail.showdesk.test"
    row = registered_row(
        organization, domain="mail.showdesk.test", sending_status=Sending.VERIFIED
    )

    row.delete()

    assert not SendingRemoval.objects.exists()
    assert services.record_removal("mail.showdesk.test", "ref") is None
    assert not SendingRemoval.objects.exists()
    assert any(
        r.levelname == "ERROR"
        and "not removing the sending registration of the instance's own domain"
        in r.getMessage().lower()
        for r in caplog.records
    )


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
        checked = timezone.now() - timedelta(hours=25)
        row = registered_row(
            organization,
            sending_status=Sending.VERIFIED,
            sending_last_checked_at=checked,
        )
        provider.fail = {"check"}

        assert services.check_sending(row) == CheckStatus.UNKNOWN

        row.refresh_from_db()
        assert row.sending_status == Sending.VERIFIED
        assert row.sending_last_error == ""
        # Still due: the next periodic check tries again.
        assert row.sending_last_checked_at == checked

    def test_check_now_on_a_failed_domain_still_pending_keeps_its_error(
        self, provider, organization
    ) -> None:
        row = registered_row(
            organization,
            sending_status=Sending.FAILED,
            sending_last_error="Not verified within 72 hours. SPF missing.",
        )
        cache.delete(services.check_lock_key(row))
        provider.result = DomainCheck(CheckStatus.PENDING, "DKIM missing.")

        services.check_now(row)

        row.refresh_from_db()
        assert row.sending_status == Sending.FAILED
        assert row.sending_last_error == "Not verified within 72 hours. SPF missing."

    def test_newer_records_replace_the_stored_ones(
        self, provider, organization
    ) -> None:
        row = registered_row(organization)
        newer = [{"type": "TXT", "name": "acme.com", "value": "v=spf1 -all"}]
        provider.result = DomainCheck(CheckStatus.PENDING, "", newer)

        services.check_sending(row)

        row.refresh_from_db()
        assert row.sending_dns_records == [services.ownership_record(row), *newer]

    def test_the_ownership_record_is_refreshed_at_every_check(
        self, provider, organization
    ) -> None:
        """The token changed since the records were stored (a new token asked
        for, or given on enable): the next check shows the current one first,
        even when the provider returns no records."""
        stale = {"type": "TXT", "name": "_showdesk.acme.com", "value": "old"}
        row = registered_row(organization)
        OrganizationDomain.objects.filter(pk=row.pk).update(
            sending_dns_records=[*RECORDS, stale]
        )
        row.refresh_from_db()

        services.check_sending(row)

        row.refresh_from_db()
        assert row.sending_dns_records == [services.ownership_record(row), *RECORDS]

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

    def test_a_broker_down_leaves_the_removal_to_the_sweep(
        self, provider, organization, admin_client
    ) -> None:
        provider.fail = {"remove"}
        row = registered_row(organization, sending_status=Sending.VERIFIED)

        with mock.patch(
            "apps.email_channel.tasks.remove_sending_registration.delay",
            side_effect=ConnectionError("broker down"),
        ):
            response = admin_client.delete(
                f"/api/v1/organization-domains/{row.id}/sending/"
            )

        assert response.status_code == 200, response.data
        assert response.data["sending_status"] == ""
        removal = SendingRemoval.objects.get()
        assert removal.ref == "ref-acme.com"
        assert removal.provider == "manual"
        assert removal.last_attempt_at is not None


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

    def test_a_removal_made_under_another_provider_waits(
        self, provider, caplog
    ) -> None:
        from apps.email_channel.tasks import remove_sending_registration

        removal = SendingRemoval.objects.create(
            domain="acme.com", ref="ref-old", provider="scaleway_tem"
        )

        with mock.patch.object(remove_sending_registration, "retry") as retry:
            remove_sending_registration(removal.pk)

        retry.assert_not_called()
        assert provider.calls == []
        removal.refresh_from_db()
        assert removal.attempts == 0
        assert removal.last_attempt_at is not None
        assert "scaleway_tem" in caplog.text

    def test_the_sweep_requeues_what_is_stuck(self, caplog) -> None:
        from apps.email_channel.tasks import requeue_sending_removals

        now = timezone.now()
        never_tried = SendingRemoval.objects.create(
            domain="a.com", ref="1", created_at=now - timedelta(hours=4)
        )
        stuck = SendingRemoval.objects.create(
            domain="b.com",
            ref="2",
            created_at=now - timedelta(days=1),
            last_attempt_at=now - timedelta(hours=4),
            attempts=1,
        )
        given_up = SendingRemoval.objects.create(
            domain="c.com",
            ref="3",
            created_at=now - timedelta(days=1),
            last_attempt_at=now - timedelta(hours=4),
            attempts=services.MAX_REMOVAL_ATTEMPTS,
        )
        SendingRemoval.objects.create(domain="d.com", ref="4")  # Just queued.
        SendingRemoval.objects.create(  # Still retrying.
            domain="e.com",
            ref="5",
            created_at=now - timedelta(days=1),
            last_attempt_at=now - timedelta(hours=1),
            attempts=5,
        )

        with mock.patch(
            "apps.email_channel.tasks.remove_sending_registration.delay"
        ) as delay:
            requeue_sending_removals()

        assert sorted(c.args[0] for c in delay.call_args_list) == sorted(
            [never_tried.pk, stuck.pk, given_up.pk]
        )
        [error] = [r for r in caplog.records if r.levelname == "ERROR"]
        assert "c.com" in error.getMessage()


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


def test_the_migration_frees_addresses_on_another_organization_domain(organization):
    """Squatted before public addresses needed their domain verified."""
    import importlib

    from django.apps import apps

    migration = importlib.import_module(
        "apps.email_channel.migrations.0005_free_squatted_public_addresses"
    )
    domain_row(organization)  # acme.com, verified by `organization`.
    squatter = MailboxFactory(public_address="support@acme.com")
    owner = MailboxFactory(organization=organization, public_address="help@acme.com")
    unclaimed = MailboxFactory(public_address="hello@nobody.com")

    migration.free_squatted_public_addresses(apps, None)

    for mailbox in (squatter, owner, unclaimed):
        mailbox.refresh_from_db()
    assert squatter.public_address == ""
    assert owner.public_address == "help@acme.com"
    assert unclaimed.public_address == "hello@nobody.com"


def test_an_old_verified_webmail_row_never_counts_as_ownership(
    provider, organization, admin_client
):
    """A `gmail.com` row verified before webmail domains were refused."""
    import importlib

    from django.apps import apps

    migration = importlib.import_module(
        "apps.email_channel.migrations.0005_free_squatted_public_addresses"
    )
    row = domain_row(
        organization,
        is_sending=True,
        sending_status=Sending.VERIFIED,
        sending_provider="manual",
    )
    OrganizationDomain.objects.filter(pk=row.pk).update(domain="gmail.com")
    someone = MailboxFactory(public_address="someone@gmail.com")
    ours = MailboxFactory(organization=organization, public_address="us@gmail.com")

    migration.free_squatted_public_addresses(apps, None)
    response = admin_client.patch(
        f"/api/v1/mailboxes/{ours.id}/",
        {"public_address": "help@gmail.com"},
        format="json",
    )

    someone.refresh_from_db()
    assert someone.public_address == "someone@gmail.com"
    assert response.status_code == 400
    assert "public webmail" in response.data["public_address"][0]
    assert services.sendable_address(ours) is None
    assert services.sendable_domains(organization.id) == set()
    row.refresh_from_db()
    assert row.status == OrganizationDomain.Status.VERIFIED  # Left as it was.


def test_only_the_configured_provider_rows_are_sendable(provider, organization):
    """`provider` configures `manual`. A row registered with another one, or
    with none recorded, is not sendable, by either path."""
    for domain, made_by in (
        ("acme.com", "manual"),
        ("acme.org", "scaleway_tem"),
        ("acme.net", ""),
    ):
        registered_row(
            organization,
            domain=domain,
            sending_status=Sending.VERIFIED,
            sending_provider=made_by,
            sending_provider_ref=f"ref-{domain}",
        )
    mailboxes = {
        domain: MailboxFactory(
            organization=organization, public_address=f"help@{domain}"
        )
        for domain in ("acme.com", "acme.org", "acme.net")
    }

    domains = services.sendable_domains(organization.id)

    assert domains == {"acme.com"}
    for domain, mailbox in mailboxes.items():
        expected = mailbox.public_address if domain == "acme.com" else None
        assert services.sendable_address(mailbox, domains) == expected
        assert services.sendable_address(mailbox) == expected


class FakeMailjet:
    """Mailjet's sender and DNS API, as observed, for one account."""

    def __init__(self) -> None:
        self.senders: dict[int, dict] = {}

    def add(self, domain: str, status: str) -> int:
        sender_id = 4242 + len(self.senders)
        self.senders[sender_id] = {
            "ID": sender_id,
            "DNSID": sender_id + 1000,
            "Email": f"*@{domain}",
            "Filename": "a1b2c3d4e5f60718293a4b5c6d7e8f90.txt",
            "Status": status,
        }
        return sender_id

    def __call__(self, method: str, url: str, **kwargs):
        import json

        import requests

        path = url.removeprefix("https://api.mailjet.com/v3/REST")
        status, body = self.answer(method, path, kwargs.get("json"))
        response = requests.Response()
        response.status_code = status
        response._content = b"" if body is None else json.dumps(body).encode()
        return response

    def answer(self, method: str, path: str, data):
        import re

        listing = re.fullmatch(r"/sender\?Email=\*@(.+)&ShowDeleted=true", path)
        one = re.fullmatch(r"/sender/(\d+)(/validate)?", path)
        dns = re.fullmatch(r"/dns/(\d+)(/check)?", path)
        if (method, path) == ("POST", "/sender"):
            domain = data["Email"][2:]
            for sender in self.senders.values():
                if sender["Email"] == data["Email"]:
                    return 400, {
                        "ErrorMessage": "There is an already existing "
                        f"{sender['Status'].lower()} sender with the same email."
                    }
            return 201, {"Data": [self.senders[self.add(domain, "Inactive")]]}
        if listing:
            found = [
                s for s in self.senders.values() if s["Email"] == f"*@{listing[1]}"
            ]
            return 200, {"Data": found}
        if one:
            sender = self.senders.get(int(one[1]))
            if sender is None:
                return 404, {"ErrorMessage": "Object not found"}
            if method == "DELETE":
                sender["Status"] = "Deleted"
                return 204, None
            if one[2]:  # Its ownership TXT is published.
                sender["Status"] = "Active"
                return 200, {"Errors": {}, "GlobalError": ""}
            return 200, {"Data": [sender]}
        if dns:
            sender = next(s for s in self.senders.values() if s["DNSID"] == int(dns[1]))
            if sender["Status"] == "Deleted":
                return 404, {"ErrorMessage": "Object not found"}
            if dns[2]:
                return 200, {"Data": [{"DKIMStatus": "OK", "SPFStatus": "OK"}]}
            return 200, {
                "Data": [
                    {
                        "ID": sender["DNSID"],
                        "Domain": sender["Email"][2:],
                        "OwnerShipToken": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
                        "OwnerShipTokenRecordName": "mailjet._a1b2c3d4",
                        "SPFRecordValue": "v=spf1 include:spf.mailjet.com ?all",
                        "DKIMRecordName": "mailjet._domainkey",
                        "DKIMRecordValue": "k=rsa; p=MIIB",
                    }
                ]
            }
        raise AssertionError(f"Unexpected Mailjet call {method} {path}")


def test_a_domain_changing_hands_under_mailjet(
    organization, settings, django_capture_on_commit_callbacks
):
    """The loser's sender is deleted before the winner may set the domain
    up, which then reuses it."""
    from apps.organizations import services as domains

    settings.SENDING_DOMAIN_PROVIDER = "mailjet"
    settings.ANYMAIL = {
        **settings.ANYMAIL,
        "MAILJET_API_KEY": "key",
        "MAILJET_SECRET_KEY": "secret",
    }
    settings.MAILJET_API_URL = "https://api.mailjet.com"
    mailjet = FakeMailjet()
    previous = registered_row(
        OrganizationFactory(),
        sending_status=Sending.VERIFIED,
        sending_provider="mailjet",
        sending_provider_ref=str(mailjet.add("acme.com", "Active")),
    )
    challenge = domains.start_dns_challenge(
        organization=organization, domain="acme.com", is_branding=True
    )
    with (
        mock.patch("apps.email_channel.sending.mailjet.requests.request", mailjet),
        mock.patch(
            "apps.organizations.dns_verification.lookup_txt",
            return_value=[challenge.txt_record_value],
        ),
        mock.patch("apps.email_channel.tasks.remove_sending_registration.delay"),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            assert domains.perform_dns_check(challenge) is True
        removal = SendingRemoval.objects.get(ref=previous.sending_provider_ref)
        challenge.refresh_from_db()

        with pytest.raises(services.RemovalPendingError) as refused:
            services.enable_sending(challenge)
        assert refused.value.http_status == 409

        services.run_removal(removal.pk)
        assert mailjet.senders[4242]["Status"] == "Deleted"

        row = services.enable_sending(challenge)

    assert list(mailjet.senders) == [4242]  # Reused, not created again.
    assert mailjet.senders[4242]["Status"] == "Active"
    assert (row.sending_provider_ref, row.sending_status) == ("4242", Sending.VERIFIED)
