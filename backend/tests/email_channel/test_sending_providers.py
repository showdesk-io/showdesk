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
    AlreadyRegisteredError,
    CheckStatus,
    DomainCheck,
    ProviderUnavailableError,
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
                "merge": True,
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

    def test_check_reads_records_as_receivers_do(self, manual) -> None:
        """Qualifiers, trailing dots and split TXT strings don't matter."""
        with published(
            {
                "acme.com": ["v=spf1 +include:spf.mail.example.net. -all"],
                "showdesk._domainkey.acme.com": ["v=DKIM1; k=rsa; p=MIIBIj ANBgkqh"],
                f"showdesk._domainkey.{INBOUND_DOMAIN}": [OPERATOR_KEY],
            }
        ):
            assert manual.check("acme.com").status == CheckStatus.VERIFIED

        # Nothing after the first `all` mechanism is ever evaluated.
        with published(
            {
                "acme.com": ["v=spf1 ~all include:spf.mail.example.net"],
                "showdesk._domainkey.acme.com": [OPERATOR_KEY],
                f"showdesk._domainkey.{INBOUND_DOMAIN}": [OPERATOR_KEY],
            }
        ):
            result = manual.check("acme.com")
        assert result.status == CheckStatus.PENDING and "SPF" in result.error

    def test_check_without_the_operator_key_is_unknown(self, manual, caplog) -> None:
        """A missing or revoked (empty `p=`) operator key is the operator's fault."""
        with published(
            {
                "acme.com": [GOOD_SPF],
                "showdesk._domainkey.acme.com": ["v=DKIM1; k=rsa; p="],
                f"showdesk._domainkey.{INBOUND_DOMAIN}": ["v=DKIM1; k=rsa; p="],
            }
        ):
            assert manual.check("acme.com").status == CheckStatus.UNKNOWN
        assert f"showdesk._domainkey.{INBOUND_DOMAIN}" in caplog.text

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
    """Nor does it pretend to remove anything: a removal waits for a provider."""
    settings.SENDING_DOMAIN_PROVIDER = "none"
    with pytest.raises(SendingProviderError):
        get_provider().register("acme.com")
    with pytest.raises(ProviderUnavailableError):
        get_provider().remove("ref")


def test_unknown_provider_is_misconfigured(settings) -> None:
    settings.SENDING_DOMAIN_PROVIDER = "carrier-pigeon"
    with pytest.raises(ImproperlyConfigured):
        get_provider()


TEM_KEY = "scw-secret-key-not-to-leak"
TEM_PROJECT = "11111111-2222-3333-4444-555555555555"
TEM_ID = "0b6a3c1e-9d2f-4e7a-8c5b-1f2e3d4c5b6a"
TEM_DOMAINS = (
    "https://api.scaleway.com/transactional-email/v1alpha1/regions/fr-par/domains"
)


def tem_domain(status: str, last_error: str = "", **records) -> dict:
    """A TEM domain as its API returns it."""
    return {
        "id": TEM_ID,
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
        assert registered.ref == TEM_ID
        assert registered.records == [
            {
                "type": "TXT",
                "name": "acme.com",
                "value": "v=spf1 include:_spf.tem.scaleway.com -all",
                "merge": True,
            },
            {
                "type": "TXT",
                "name": f"{TEM_PROJECT}._domainkey.acme.com",
                "value": "v=DKIM1; h=sha256",
            },
            # No MX: TEM's blackhole would take the support address's mail.
            {
                "type": "TXT",
                "name": "_dmarc.acme.com",
                "value": "v=DMARC1; p=none",
                "merge": True,
            },
        ]

    def test_register_refuses_unusable_answers(self, tem) -> None:
        for answer in (
            (503, {"message": "unavailable"}),
            (200, ["not", "an", "object"]),
            (200, {"name": "acme.com", "status": "unchecked"}),  # No id.
        ):
            patcher, _fake = answering({("POST", TEM_DOMAINS): answer})
            with patcher, pytest.raises(SendingProviderError):
                tem.register("acme.com")

        # A record without a name can't be published: it is left out.
        created = tem_domain(
            "unchecked",
            dkim={"value": "v=DKIM1; h=sha256"},
            spf={"name": "", "value": "v=spf1 include:_spf.tem.scaleway.com -all"},
        )
        patcher, _fake = answering({("POST", TEM_DOMAINS): (200, created)})
        with patcher:
            records = tem.register("acme.com").records
        assert [record["name"] for record in records] == ["acme.com"]

    def test_check_maps_statuses(self, tem) -> None:
        def check(status: str, last_error: str = "", check_answer=None):
            domain = tem_domain(status, last_error)
            patcher, fake = answering(
                {
                    ("GET", f"{TEM_DOMAINS}/{TEM_ID}"): (200, domain),
                    ("POST", f"{TEM_DOMAINS}/{TEM_ID}/check"): check_answer
                    or (200, domain),
                }
            )
            with patcher:
                return tem.check(TEM_ID), [call[:2] for call in fake.calls]

        # The outcome is TEM's last real check; the POST only asks for the
        # next one, and answers `pending` while it runs.
        result, calls = check("checked", check_answer=(200, tem_domain("pending")))
        assert result.status == CheckStatus.VERIFIED
        assert calls == [
            ("GET", f"{TEM_DOMAINS}/{TEM_ID}"),
            ("POST", f"{TEM_DOMAINS}/{TEM_ID}/check"),
        ]
        # Asking for the next check may fail without changing the outcome.
        result, _calls = check("checked", check_answer=(503, {"message": "busy"}))
        assert result.status == CheckStatus.VERIFIED

        assert check("unknown")[0].status == CheckStatus.UNKNOWN

        result, _calls = check("invalid", "SPF record not found")
        assert (result.status, result.error) == (
            CheckStatus.PENDING,
            "SPF record not found",
        )
        assert check("autoconfiguring")[0].status == CheckStatus.PENDING

        # A domain TEM gave up on isn't checked again.
        result, calls = check("locked")
        assert result.status == CheckStatus.FAILED
        assert calls == [("GET", f"{TEM_DOMAINS}/{TEM_ID}")]

    def test_http_errors_raise_a_provider_error(self, tem) -> None:
        patcher, _fake = answering(
            {("GET", f"{TEM_DOMAINS}/{TEM_ID}"): requests.Timeout("read timed out")}
        )
        with patcher, pytest.raises(SendingProviderError):
            tem.check(TEM_ID)

        patcher, _fake = answering(
            {("GET", f"{TEM_DOMAINS}/{TEM_ID}"): (503, {"message": "unavailable"})}
        )
        with patcher, pytest.raises(SendingProviderError) as error:
            tem.check(TEM_ID)
        assert TEM_KEY not in str(error.value)

        patcher, _fake = answering(
            {("POST", TEM_DOMAINS): (409, {"message": "domain already exists"})}
        )
        with patcher, pytest.raises(AlreadyRegisteredError):
            tem.register("acme.com")

        # A ref that isn't TEM's never reaches a URL.
        patcher, fake = answering({})
        with patcher, pytest.raises(SendingProviderError):
            tem.check("../../projects")
        assert fake.calls == []

    def test_remove_revokes(self, tem) -> None:
        revoke = ("POST", f"{TEM_DOMAINS}/{TEM_ID}/revoke")
        patcher, fake = answering({revoke: (200, tem_domain("revoked"))})
        with patcher:
            tem.remove(TEM_ID)
        assert [call[:2] for call in fake.calls] == [revoke]

        # Already gone (404) or already revoked (409) counts as removed.
        for status_code in (404, 409):
            patcher, _fake = answering({revoke: (status_code, {"message": "no"})})
            with patcher:
                tem.remove(TEM_ID)

    def test_without_credentials_is_misconfigured(self, tem, settings) -> None:
        settings.SCW_TEM_SECRET_KEY = ""
        with pytest.raises(ImproperlyConfigured):
            get_provider()
