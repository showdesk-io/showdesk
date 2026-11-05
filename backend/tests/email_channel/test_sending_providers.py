"""Sending domain providers: what each asks to publish and how it reads a check (§7.2).

The DNS boundary is `dns_verification.lookup_txt` and the HTTP one
`requests.request` as `scaleway_tem` and `mailjet` call it; nothing else is
mocked.
"""

import base64
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


class FakeAPI:
    """`requests.request`, answering each (method, url) with canned JSON.

    A body of None is an empty one, bytes are sent as they are. A list of
    answers gives one per call, in order.
    """

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls = []

    def __call__(self, method: str, url: str, **kwargs) -> requests.Response:
        self.calls.append((method, url, kwargs))
        answer = self.routes[method, url]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        response = requests.Response()
        response.status_code = status
        if body is None:
            response._content = b""
        elif isinstance(body, bytes):
            response._content = body
        else:
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


def answering(routes: dict, module: str = "scaleway_tem"):
    fake = FakeAPI(routes)
    return mock.patch(
        f"apps.email_channel.sending.{module}.requests.request", fake
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
        # Scaleway's own words go to the log, not to the organization's admins.
        assert str(error.value) == "The sending service answered 503."

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


MJ_KEY = "mj-public-key-not-to-leak"
MJ_SECRET = "mj-private-key-not-to-leak"
MJ = "https://api.mailjet.com/v3/REST"
MJ_SENDER_ID = 4242
MJ_DNS_ID = 77
MJ_TOKEN = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
MJ_SENDER = ("GET", f"{MJ}/sender/{MJ_SENDER_ID}")
MJ_VALIDATE = ("POST", f"{MJ}/sender/{MJ_SENDER_ID}/validate")
MJ_DNS = ("GET", f"{MJ}/dns/{MJ_DNS_ID}")
MJ_DNS_CHECK = ("POST", f"{MJ}/dns/{MJ_DNS_ID}/check")
MJ_FIND = ("GET", f"{MJ}/sender?Email=*@acme.com&ShowDeleted=true")
MJ_GONE = (
    404,
    {"ErrorInfo": "", "ErrorMessage": "Object not found", "StatusCode": 404},
)


def mj(*items: dict) -> dict:
    """A Mailjet answer: results wrapped in Count, Total and Data."""
    return {"Count": len(items), "Total": len(items), "Data": list(items)}


def mj_sender(status: str, dns_id: int = MJ_DNS_ID) -> dict:
    # As Mailjet gives it: a real DNSID even while inactive, the ownership
    # token as the validation file's name.
    return {
        "CreatedAt": "2026-11-05T09:12:44Z",
        "DNSID": dns_id,
        "Email": "*@acme.com",
        "EmailType": "transactional",
        "Filename": f"{MJ_TOKEN}.txt",
        "ID": MJ_SENDER_ID,
        "IsDefaultSender": False,
        "Name": "",
        "Status": status,
    }


def mj_dns(domain: str = "acme.com", dns_id: int = MJ_DNS_ID) -> dict:
    return {
        "ID": dns_id,
        "Domain": domain,
        "OwnerShipToken": MJ_TOKEN,
        "OwnerShipTokenRecordName": f"mailjet._a1b2c3d4.{domain}.",
        "SPFRecordValue": "v=spf1 include:spf.mailjet.com ?all",
        "SPFStatus": "Not checked",
        "DKIMRecordName": f"mailjet._domainkey.{domain}.",
        "DKIMRecordValue": "k=rsa; p=MIIBIjANBgkqhkiG9w0B",
        "DKIMStatus": "Not checked",
    }


def mj_validation(dns_error: str = "", global_error: str = "") -> dict:
    """`validate`'s answer, as it is: not wrapped in Data."""
    errors = {}
    if dns_error:
        errors = {
            "FileValidationError": "File verification failed as the server is "
            "not accessible.",
            "DNSValidationError": dns_error,
        }
    return {"ValidationMethod": "", "Errors": errors, "GlobalError": global_error}


NO_TXT = (
    "DNS record verification failed as no TXT record for that ownership token "
    "was found on the remote server."
)
MJ_RECORDS = [
    {"type": "TXT", "name": "mailjet._a1b2c3d4.acme.com", "value": MJ_TOKEN},
    {
        "type": "TXT",
        "name": "acme.com",
        "value": "v=spf1 include:spf.mailjet.com ?all",
        "merge": True,
    },
    {
        "type": "TXT",
        "name": "mailjet._domainkey.acme.com",
        "value": "k=rsa; p=MIIBIjANBgkqhkiG9w0B",
    },
]
# Without the DNS entry (a deleted sender's): ownership and SPF, no DKIM.
MJ_DERIVED_RECORDS = MJ_RECORDS[:2]


@pytest.fixture
def mailjet(settings):
    settings.SENDING_DOMAIN_PROVIDER = "mailjet"
    settings.ANYMAIL = {
        **settings.ANYMAIL,
        "MAILJET_API_KEY": MJ_KEY,
        "MAILJET_SECRET_KEY": MJ_SECRET,
    }
    settings.MAILJET_API_URL = "https://api.mailjet.com"
    return get_provider()


def mailjet_answering(routes: dict):
    return answering(routes, module="mailjet")


def calls_of(fake) -> list:
    return [call[:2] for call in fake.calls]


class TestMailjet:
    def test_register_creates_a_domain_sender_and_returns_its_records(
        self, mailjet
    ) -> None:
        patcher, fake = mailjet_answering(
            {
                ("POST", f"{MJ}/sender"): (201, mj(mj_sender("Inactive"))),
                MJ_DNS: (200, mj(mj_dns())),
            }
        )
        with patcher:
            registered = mailjet.register("acme.com")

        (method, url, kwargs), lookup = fake.calls
        assert (method, url) == ("POST", f"{MJ}/sender")
        assert kwargs["json"] == {"Email": "*@acme.com", "EmailType": "transactional"}
        assert kwargs["auth"] == (MJ_KEY, MJ_SECRET)
        assert kwargs["timeout"] == 10
        assert lookup[:2] == MJ_DNS
        assert registered.ref == str(MJ_SENDER_ID)
        assert registered.records == MJ_RECORDS

    def test_register_reuses_the_sender_mailjet_already_has(self, mailjet) -> None:
        def register(state: str, dns_answer: tuple):
            patcher, fake = mailjet_answering(
                {
                    ("POST", f"{MJ}/sender"): (
                        400,
                        {
                            "ErrorInfo": "",
                            "ErrorMessage": f"There is an already existing {state} "
                            'sender with the same email. You can use "validate" '
                            "action in order to activate it.",
                            "StatusCode": 400,
                        },
                    ),
                    MJ_FIND: (
                        200,
                        mj(mj_sender(state.capitalize())),
                    ),
                    MJ_DNS: dns_answer,
                }
            )
            with patcher:
                return mailjet.register("acme.com"), calls_of(fake)

        registered, calls = register("inactive", (200, mj(mj_dns())))
        assert MJ_FIND in calls
        assert (registered.ref, registered.records) == (str(MJ_SENDER_ID), MJ_RECORDS)

        # A deleted sender has no DNS entry any more: its ownership token and
        # SPF are known anyway, DKIM comes once validation reactivates it.
        registered = register("deleted", MJ_GONE)[0]
        assert registered.ref == str(MJ_SENDER_ID)
        assert registered.records == MJ_DERIVED_RECORDS

    def test_register_errors(self, mailjet, caplog) -> None:
        refused = {"ErrorMessage": "MJ03 Email is invalid", "StatusCode": 400}
        patcher, _fake = mailjet_answering({("POST", f"{MJ}/sender"): (400, refused)})
        with patcher, pytest.raises(SendingProviderError) as error:
            mailjet.register("acme.com")
        assert not isinstance(error.value, AlreadyRegisteredError)

        # Said to exist, yet not found.
        patcher, _fake = mailjet_answering(
            {
                ("POST", f"{MJ}/sender"): (
                    400,
                    {"ErrorMessage": "There is an already existing inactive sender"},
                ),
                MJ_FIND: (200, mj()),
            }
        )
        with patcher, pytest.raises(SendingProviderError):
            mailjet.register("acme.com")

        patcher, _fake = mailjet_answering(
            {("POST", f"{MJ}/sender"): (503, b"<html>Service Unavailable</html>")}
        )
        with patcher, pytest.raises(SendingProviderError) as error:
            mailjet.register("acme.com")
        assert str(error.value) == "The sending service answered 503."
        assert MJ_KEY not in caplog.text and MJ_SECRET not in caplog.text

        # A sender without an id can't be stored.
        patcher, _fake = mailjet_answering(
            {("POST", f"{MJ}/sender"): (201, mj({"Status": "Inactive"}))}
        )
        with patcher, pytest.raises(SendingProviderError):
            mailjet.register("acme.com")

    def test_register_keeps_the_sender_when_its_records_cant_be_read(
        self, mailjet
    ) -> None:
        for dns_answer in (
            (503, b"Service Unavailable"),
            (200, mj(mj_dns("other.org"))),
        ):
            patcher, _fake = mailjet_answering(
                {
                    ("POST", f"{MJ}/sender"): (201, mj(mj_sender("Inactive"))),
                    MJ_DNS: dns_answer,
                }
            )
            with patcher:
                registered = mailjet.register("acme.com")
            assert registered.ref == str(MJ_SENDER_ID)
            assert registered.records == MJ_DERIVED_RECORDS

    @pytest.mark.parametrize("status", ["Inactive", "Deleted"])
    def test_check_asks_mailjet_to_validate_a_sender_not_active(
        self, mailjet, status
    ) -> None:
        patcher, fake = mailjet_answering(
            {
                MJ_SENDER: (200, mj(mj_sender(status))),
                MJ_VALIDATE: (
                    200,
                    mj_validation(
                        NO_TXT,
                        "Neither the file at your domain root nor "
                        "the DNS TXT record have been found to validate this sender.",
                    ),
                ),
                MJ_DNS: (200, mj(mj_dns())) if status == "Inactive" else MJ_GONE,
            }
        )
        with patcher:
            result = mailjet.check(str(MJ_SENDER_ID))
        assert result.status == CheckStatus.PENDING
        assert result.error == NO_TXT
        # DKIM and SPF are checked once the sender is active.
        assert MJ_DNS_CHECK not in calls_of(fake)
        expected = MJ_RECORDS if status == "Inactive" else MJ_DERIVED_RECORDS
        assert result.records == expected

        # Without Mailjet's DNS error, its global one.
        patcher, _fake = mailjet_answering(
            {
                MJ_SENDER: (200, mj(mj_sender(status))),
                MJ_VALIDATE: (200, mj_validation(global_error="Not found.")),
                MJ_DNS: MJ_GONE,
            }
        )
        with patcher:
            assert mailjet.check(str(MJ_SENDER_ID)).error == "Not found."

    def test_check_of_an_active_sender_reads_dkim_and_spf(self, mailjet) -> None:
        def check(dns_check: dict):
            patcher, fake = mailjet_answering(
                {
                    MJ_SENDER: (200, mj(mj_sender("Active"))),
                    MJ_DNS: (200, mj(mj_dns())),
                    MJ_DNS_CHECK: (200, mj(dns_check)),
                }
            )
            with patcher:
                return mailjet.check(str(MJ_SENDER_ID)), calls_of(fake)

        result, calls = check({"DKIMStatus": "OK", "SPFStatus": "OK"})
        assert (result.status, result.error) == (CheckStatus.VERIFIED, "")
        assert result.records == MJ_RECORDS
        assert MJ_VALIDATE not in calls

        result, _calls = check(
            {
                "DKIMErrors": ["no DKIM record", "wrong key"],
                "DKIMRecordCurrentValue": "",
                "DKIMStatus": "Error",
                "SPFErrors": [],
                "SPFRecordsCurrentValues": [],
                "SPFStatus": "OK",
            }
        )
        assert result.status == CheckStatus.PENDING
        assert result.error == "DKIM: no DKIM record; wrong key"

        result, _calls = check(
            {"DKIMStatus": "OK", "SPFStatus": "Error", "SPFErrors": "Host not found."}
        )
        assert result.error == "SPF: Host not found."

    def test_check_verifies_a_sender_mailjet_validates(self, mailjet) -> None:
        # `validate` as Mailjet gives it, or wrapped in Data.
        for validation in (mj_validation(), mj(mj_validation())):
            patcher, fake = mailjet_answering(
                {
                    MJ_SENDER: [
                        (200, mj(mj_sender("Deleted"))),
                        (200, mj(mj_sender("Active"))),
                    ],
                    MJ_VALIDATE: (200, validation),
                    MJ_DNS: (200, mj(mj_dns())),
                    MJ_DNS_CHECK: (200, mj({"DKIMStatus": "OK", "SPFStatus": "OK"})),
                }
            )
            with patcher:
                result = mailjet.check(str(MJ_SENDER_ID))
            assert (result.status, result.error) == (CheckStatus.VERIFIED, "")
            assert result.records == MJ_RECORDS
            assert calls_of(fake).count(MJ_SENDER) == 2

        # Validated without error, yet not active: pending.
        patcher, _fake = mailjet_answering(
            {
                MJ_SENDER: (200, mj(mj_sender("Inactive"))),
                MJ_VALIDATE: (200, mj_validation()),
                MJ_DNS: (200, mj(mj_dns())),
            }
        )
        with patcher:
            assert mailjet.check(str(MJ_SENDER_ID)).status == CheckStatus.PENDING

    def test_dns_entry_of_another_domain_is_not_used(self, mailjet) -> None:
        patcher, fake = mailjet_answering(
            {
                MJ_SENDER: (200, mj(mj_sender("Active", 12))),
                ("GET", f"{MJ}/dns/12"): (200, mj(mj_dns("other.org", 12))),
            }
        )
        with patcher:
            result = mailjet.check(str(MJ_SENDER_ID))
        assert result.status == CheckStatus.PENDING
        assert result.records == MJ_DERIVED_RECORDS
        assert ("POST", f"{MJ}/dns/12/check") not in calls_of(fake)

    def test_check_of_a_missing_or_strange_sender(self, mailjet) -> None:
        patcher, _fake = mailjet_answering({MJ_SENDER: MJ_GONE})
        with patcher:
            assert mailjet.check(str(MJ_SENDER_ID)).status == CheckStatus.FAILED

        patcher, _fake = mailjet_answering(
            {MJ_SENDER: (200, mj(mj_sender("Suspended")))}
        )
        with patcher:
            assert mailjet.check(str(MJ_SENDER_ID)).status == CheckStatus.UNKNOWN

    def test_mailjet_echoing_the_keys_is_masked(self, mailjet, caplog) -> None:
        basic = base64.b64encode(f"{MJ_KEY}:{MJ_SECRET}".encode()).decode()
        echo = f"Bad auth {MJ_KEY} / {MJ_SECRET} (Basic {basic})"
        for validation in ((200, mj_validation(echo)), (400, {"ErrorMessage": echo})):
            patcher, _fake = mailjet_answering(
                {
                    MJ_SENDER: (200, mj(mj_sender("Inactive"))),
                    MJ_VALIDATE: validation,
                    MJ_DNS: (200, mj(mj_dns())),
                }
            )
            with patcher:
                result = mailjet.check(str(MJ_SENDER_ID))
            assert "Bad auth" in result.error
            for secret in (MJ_KEY, MJ_SECRET, basic):
                assert secret not in result.error and secret not in caplog.text

        patcher, _fake = mailjet_answering(
            {
                MJ_SENDER: (200, mj(mj_sender("Active"))),
                MJ_DNS: (200, mj(mj_dns())),
                MJ_DNS_CHECK: (
                    200,
                    mj(
                        {"DKIMStatus": "Error", "DKIMErrors": [echo], "SPFStatus": "OK"}
                    ),
                ),
            }
        )
        with patcher:
            result = mailjet.check(str(MJ_SENDER_ID))
        assert "Bad auth" in result.error
        for secret in (MJ_KEY, MJ_SECRET, basic):
            assert secret not in result.error

        patcher, _fake = mailjet_answering(
            {("POST", f"{MJ}/sender"): (401, {"ErrorMessage": echo})}
        )
        with patcher, pytest.raises(SendingProviderError) as error:
            mailjet.register("acme.com")
        for secret in (MJ_KEY, MJ_SECRET, basic):
            assert secret not in str(error.value) and secret not in caplog.text

    def test_check_that_cannot_conclude_raises(self, mailjet, caplog) -> None:
        patcher, _fake = mailjet_answering(
            {
                MJ_SENDER: requests.ConnectionError(
                    f"https://{MJ_KEY}:{MJ_SECRET}@api.mailjet.com refused"
                )
            }
        )
        with patcher, pytest.raises(SendingProviderError) as error:
            mailjet.check(str(MJ_SENDER_ID))
        assert MJ_KEY not in str(error.value) and MJ_KEY not in caplog.text
        assert MJ_SECRET not in caplog.text

        # A ref that isn't a sender id never reaches a URL.
        patcher, fake = mailjet_answering({})
        with patcher, pytest.raises(SendingProviderError):
            mailjet.check("../dns")
        assert fake.calls == []

    def test_remove_deletes_the_sender(self, mailjet) -> None:
        delete = ("DELETE", f"{MJ}/sender/{MJ_SENDER_ID}")
        patcher, fake = mailjet_answering(
            {MJ_SENDER: (200, mj(mj_sender("Active"))), delete: (204, None)}
        )
        with patcher:
            mailjet.remove(str(MJ_SENDER_ID))
        assert calls_of(fake) == [MJ_SENDER, delete]

        # Already gone, or deleted: removed, nothing to delete.
        for answer in (MJ_GONE, (200, mj(mj_sender("Deleted")))):
            patcher, fake = mailjet_answering({MJ_SENDER: answer})
            with patcher:
                mailjet.remove(str(MJ_SENDER_ID))
            assert calls_of(fake) == [MJ_SENDER]

        # Gone between the read and the delete.
        patcher, _fake = mailjet_answering(
            {MJ_SENDER: (200, mj(mj_sender("Inactive"))), delete: MJ_GONE}
        )
        with patcher:
            mailjet.remove(str(MJ_SENDER_ID))

        # A 400 on delete is fine when the sender reads as deleted after it.
        patcher, fake = mailjet_answering(
            {
                MJ_SENDER: [
                    (200, mj(mj_sender("Active"))),
                    (200, mj(mj_sender("Deleted"))),
                ],
                delete: (400, {"ErrorMessage": "Sender already deleted"}),
            }
        )
        with patcher:
            mailjet.remove(str(MJ_SENDER_ID))
        assert calls_of(fake) == [MJ_SENDER, delete, MJ_SENDER]

        # Otherwise it isn't removed.
        patcher, _fake = mailjet_answering(
            {
                MJ_SENDER: (200, mj(mj_sender("Active"))),
                delete: (400, {"ErrorMessage": "Cannot delete"}),
            }
        )
        with patcher, pytest.raises(SendingProviderError):
            mailjet.remove(str(MJ_SENDER_ID))

    def test_without_credentials_is_misconfigured(self, mailjet, settings) -> None:
        settings.ANYMAIL = {**settings.ANYMAIL, "MAILJET_SECRET_KEY": ""}
        with pytest.raises(ImproperlyConfigured):
            get_provider()
