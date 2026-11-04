"""Sending domain providers: what each asks to publish and how it reads a check (§7.2).

The DNS boundary is `dns_verification.lookup_txt` and the HTTP one
`requests.request` as `scaleway_tem` calls it; nothing else is mocked.
"""

import json
from unittest import mock

import pytest
import requests
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


TEM_KEY = "scw-secret-key-not-to-leak"
TEM_PROJECT = "11111111-2222-3333-4444-555555555555"
TEM_DOMAINS = (
    "https://api.scaleway.com/transactional-email/v1alpha1/regions/fr-par/domains"
)


def tem_domain(status: str, last_error: str = "", **records) -> dict:
    """A TEM domain as its API returns it."""
    return {
        "id": "dom-1",
        "name": "acme.com",
        "status": status,
        "last_error": last_error,
        "records": records,
    }


class FakeTEM:
    """`requests.request`, answering each (method, url) with canned JSON."""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls = []

    def __call__(self, method: str, url: str, **kwargs) -> requests.Response:
        self.calls.append((method, url, kwargs))
        answer = self.routes[method, url]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(body).encode()
        response.url = url
        return response


@pytest.fixture
def tem(settings):
    settings.SENDING_DOMAIN_PROVIDER = "scaleway_tem"
    settings.SCW_TEM_SECRET_KEY = TEM_KEY
    settings.SCW_TEM_PROJECT_ID = TEM_PROJECT
    settings.SCW_TEM_REGION = "fr-par"
    return get_provider()


def answering(routes: dict) -> FakeTEM:
    fake = FakeTEM(routes)
    return mock.patch(
        "apps.email_channel.sending.scaleway_tem.requests.request", fake
    ), fake


class TestScalewayTEM:
    def test_register_creates_the_domain_and_returns_its_records(self, tem) -> None:
        created = tem_domain(
            "unchecked",
            dmarc={"name": "_dmarc", "value": "v=DMARC1; p=none"},
            mx={"name": "", "value": "10 blackhole.scw-tem.cloud."},
            dkim={"name": f"{TEM_PROJECT}._domainkey", "value": "v=DKIM1; h=sha256"},
            spf={"name": "", "value": "v=spf1 include:_spf.tem.scaleway.com -all"},
        )
        patcher, fake = answering({("POST", TEM_DOMAINS): (200, created)})
        with patcher:
            registered = tem.register("acme.com")

        [(method, url, kwargs)] = fake.calls
        assert (method, url) == ("POST", TEM_DOMAINS)
        assert kwargs["headers"]["X-Auth-Token"] == TEM_KEY
        assert kwargs["json"] == {
            "project_id": TEM_PROJECT,
            "domain_name": "acme.com",
            "autoconfig": False,
        }
        assert kwargs["timeout"] == 10
        assert registered.ref == "dom-1"
        assert registered.records == [
            {
                "type": "TXT",
                "name": "acme.com",
                "value": "v=spf1 include:_spf.tem.scaleway.com -all",
            },
            {
                "type": "TXT",
                "name": f"{TEM_PROJECT}._domainkey.acme.com",
                "value": "v=DKIM1; h=sha256",
            },
            {"type": "MX", "name": "acme.com", "value": "10 blackhole.scw-tem.cloud."},
            {"type": "TXT", "name": "_dmarc.acme.com", "value": "v=DMARC1; p=none"},
        ]

    def test_check_maps_statuses(self, tem) -> None:
        def check(status: str, last_error: str = ""):
            domain = tem_domain(status, last_error)
            patcher, fake = answering(
                {
                    ("GET", f"{TEM_DOMAINS}/dom-1"): (200, domain),
                    ("POST", f"{TEM_DOMAINS}/dom-1/check"): (200, domain),
                }
            )
            with patcher:
                return tem.check("dom-1"), [call[:2] for call in fake.calls]

        result, calls = check("checked")
        assert result.status == CheckStatus.VERIFIED
        assert calls == [
            ("GET", f"{TEM_DOMAINS}/dom-1"),
            ("POST", f"{TEM_DOMAINS}/dom-1/check"),
        ]

        result, _calls = check("invalid", "SPF record not found")
        assert (result.status, result.error) == (
            CheckStatus.PENDING,
            "SPF record not found",
        )
        assert check("autoconfiguring")[0].status == CheckStatus.PENDING

        # A domain TEM gave up on isn't checked again.
        result, calls = check("locked")
        assert result.status == CheckStatus.FAILED
        assert calls == [("GET", f"{TEM_DOMAINS}/dom-1")]

    def test_http_errors_raise_a_provider_error(self, tem) -> None:
        patcher, _fake = answering(
            {("GET", f"{TEM_DOMAINS}/dom-1"): requests.Timeout("read timed out")}
        )
        with patcher, pytest.raises(SendingProviderError):
            tem.check("dom-1")

        patcher, _fake = answering(
            {("GET", f"{TEM_DOMAINS}/dom-1"): (503, {"message": "unavailable"})}
        )
        with patcher, pytest.raises(SendingProviderError) as error:
            tem.check("dom-1")
        assert TEM_KEY not in str(error.value)

        patcher, _fake = answering(
            {("POST", TEM_DOMAINS): (409, {"message": "domain already exists"})}
        )
        with patcher, pytest.raises(SendingProviderError, match="already registered"):
            tem.register("acme.com")

    def test_remove_revokes(self, tem) -> None:
        revoke = ("POST", f"{TEM_DOMAINS}/dom-1/revoke")
        patcher, fake = answering({revoke: (200, tem_domain("revoked"))})
        with patcher:
            tem.remove("dom-1")
        assert [call[:2] for call in fake.calls] == [revoke]

        # Already gone counts as removed.
        patcher, _fake = answering({revoke: (404, {"message": "not found"})})
        with patcher:
            tem.remove("dom-1")

    def test_without_credentials_is_misconfigured(self, tem, settings) -> None:
        settings.SCW_TEM_SECRET_KEY = ""
        with pytest.raises(ImproperlyConfigured):
            get_provider()
