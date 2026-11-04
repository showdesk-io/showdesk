"""Sending domain providers: what each asks to publish and how it reads a check (§7.2).

The DNS boundary is `dns_verification.lookup_txt`; nothing else is mocked.
"""

from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.email_channel.sending.providers import (
    CheckStatus,
    DomainCheck,
    SendingProviderError,
    get_provider,
)
from tests.email_channel.mails import INBOUND_DOMAIN

OPERATOR_KEY = "v=DKIM1; k=rsa; p=MIIBIjANBgkqh"
GOOD_SPF = "v=spf1 include:_spf.google.com include:spf.mail.example.net ~all"


@pytest.fixture
def manual(settings):
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    settings.SENDING_DOMAIN_SPF_INCLUDE = "spf.mail.example.net"
    settings.SENDING_DOMAIN_DKIM_SELECTOR = "showdesk"
    return get_provider()


def published(records: dict[str, list[str] | None]):
    """Patch the DNS with these TXT records; other names have none."""
    return mock.patch(
        "apps.organizations.dns_verification.lookup_txt",
        side_effect=lambda name: records.get(name, []),
    )


class TestManualProvider:
    def test_register_asks_for_an_spf_include_and_a_dkim_cname(self, manual) -> None:
        registered = manual.register("acme.com")
        assert registered.ref == "acme.com"
        assert registered.records == [
            {
                "type": "TXT",
                "name": "acme.com",
                "value": "v=spf1 include:spf.mail.example.net ~all",
            },
            {
                "type": "CNAME",
                "name": "showdesk._domainkey.acme.com",
                "value": f"showdesk._domainkey.{INBOUND_DOMAIN}",
            },
        ]

    def test_check_is_verified_when_both_records_are_published(self, manual) -> None:
        with published(
            {
                "acme.com": ["google-site-verification=abc", GOOD_SPF],
                # The CNAME is followed: both names give the operator's key.
                "showdesk._domainkey.acme.com": [OPERATOR_KEY],
                f"showdesk._domainkey.{INBOUND_DOMAIN}": [OPERATOR_KEY],
            }
        ):
            assert manual.check("acme.com") == DomainCheck(CheckStatus.VERIFIED, "")

    def test_check_names_what_is_missing(self, manual) -> None:
        with published(
            {
                "acme.com": ["v=spf1 include:_spf.google.com ~all"],
                "showdesk._domainkey.acme.com": [OPERATOR_KEY],
                f"showdesk._domainkey.{INBOUND_DOMAIN}": [OPERATOR_KEY],
            }
        ):
            result = manual.check("acme.com")
        assert result.status == CheckStatus.PENDING
        assert "SPF" in result.error and "DKIM" not in result.error

        with published(
            {
                "acme.com": [GOOD_SPF],
                "showdesk._domainkey.acme.com": ["v=DKIM1; k=rsa; p=SOMEONEELSE"],
                f"showdesk._domainkey.{INBOUND_DOMAIN}": [OPERATOR_KEY],
            }
        ):
            result = manual.check("acme.com")
        assert result.status == CheckStatus.PENDING
        assert "DKIM" in result.error and "SPF" not in result.error

    def test_check_that_cannot_resolve_is_unknown(self, manual) -> None:
        with published(
            {
                "acme.com": None,
                "showdesk._domainkey.acme.com": [OPERATOR_KEY],
                f"showdesk._domainkey.{INBOUND_DOMAIN}": [OPERATOR_KEY],
            }
        ):
            assert manual.check("acme.com").status == CheckStatus.UNKNOWN

    def test_without_settings_is_misconfigured(self, settings) -> None:
        settings.SENDING_DOMAIN_PROVIDER = "manual"
        settings.SENDING_DOMAIN_SPF_INCLUDE = ""
        settings.SENDING_DOMAIN_DKIM_SELECTOR = "showdesk"
        with pytest.raises(ImproperlyConfigured):
            get_provider()


def test_none_provider_refuses_to_register(settings) -> None:
    settings.SENDING_DOMAIN_PROVIDER = "none"
    with pytest.raises(SendingProviderError):
        get_provider().register("acme.com")


def test_unknown_provider_is_misconfigured(settings) -> None:
    settings.SENDING_DOMAIN_PROVIDER = "carrier-pigeon"
    with pytest.raises(ImproperlyConfigured):
        get_provider()
