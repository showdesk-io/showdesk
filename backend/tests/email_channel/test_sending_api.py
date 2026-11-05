"""The sending endpoints of a domain: set up, check, stop sending (§7).

Through the `manual` provider, with the DNS boundary
(`dns_verification.lookup_txt`) patched.
"""

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.email_channel.models import SendingRemoval
from apps.email_channel.sending.providers import CheckStatus
from apps.email_channel.sending.services import check_sending
from apps.organizations.models import OrganizationDomain
from tests.email_channel.mails import INBOUND_DOMAIN
from tests.factories import AdminFactory, OrganizationFactory

pytestmark = pytest.mark.django_db

OPERATOR_KEY = "v=DKIM1; k=rsa; p=MIIBIjANBgkqh"


@pytest.fixture(autouse=True)
def manual(settings):
    settings.SENDING_DOMAIN_PROVIDER = "manual"
    settings.SENDING_DOMAIN_SPF_INCLUDE = "spf.mail.example.net"
    settings.SENDING_DOMAIN_DKIM_SELECTOR = "showdesk"


def published(records: dict[str, list[str]]):
    """The DNS has these TXT records, and the operator's DKIM key."""
    records = {f"showdesk._domainkey.{INBOUND_DOMAIN}": [OPERATOR_KEY], **records}
    return mock.patch(
        "apps.organizations.dns_verification.lookup_txt",
        side_effect=lambda name: records.get(name, []),
    )


# What `manual` asks every organization to publish, whoever it is.
MANUAL_RECORDS = {
    "acme.com": ["v=spf1 include:spf.mail.example.net ~all"],
    "showdesk._domainkey.acme.com": [OPERATOR_KEY],
}


def url(row: OrganizationDomain, action: str = "") -> str:
    return f"/api/v1/organization-domains/{row.id}/sending/{action}"


def owned(organization, **fields) -> OrganizationDomain:
    return OrganizationDomain.objects.create(
        organization=organization,
        domain="acme.com",
        is_branding=True,
        status=fields.pop("status", OrganizationDomain.Status.VERIFIED),
        **fields,
    )


def test_enable_gives_the_records_and_the_first_check(admin_client, organization):
    row = owned(organization)

    with published({}):
        response = admin_client.post(url(row))

    assert response.status_code == 200, response.data
    assert response.data["is_sending"] is True
    assert response.data["sending_status"] == "pending"
    assert [r["type"] for r in response.data["sending_dns_records"]] == [
        "TXT",
        "TXT",
        "CNAME",
    ]
    assert "SPF" in response.data["sending_last_error"]
    assert "sending_provider_ref" not in response.data


def test_enable_refusals(admin_client, organization):
    pending = owned(organization, status=OrganizationDomain.Status.PENDING)
    response = admin_client.post(url(pending))
    assert response.status_code == 400
    assert response.data["code"] == "not_owned"

    pending.status = OrganizationDomain.Status.VERIFIED
    pending.save()
    SendingRemoval.objects.create(domain="acme.com", ref="acme.com")
    response = admin_client.post(url(pending))
    assert response.status_code == 409
    assert response.data["code"] == "removal_pending"


def test_a_public_webmail_domain_is_refused(admin_client, organization):
    """A webmail row verified before the rule: never registered for sending."""
    row = owned(organization)
    OrganizationDomain.objects.filter(pk=row.pk).update(domain="gmail.com")

    response = admin_client.post(url(row))

    assert response.status_code == 400
    assert response.data["code"] == "public_domain"


def test_a_misconfigured_provider_is_a_502(admin_client, organization, settings):
    settings.SENDING_DOMAIN_SPF_INCLUDE = ""
    row = owned(organization)

    response = admin_client.post(url(row))

    assert response.status_code == 502
    assert response.data["code"] == "provider_error"
    assert "SENDING_DOMAIN" not in response.data["detail"]


def test_sending_needs_the_organization_own_dns_proof(admin_client, organization):
    """Proven by an admin's mailbox, a domain isn't proven in its DNS, and the
    `manual` records are the same for every organization: the row's own
    `_showdesk` TXT is asked for first, and checked at every check."""
    row = owned(
        organization,
        is_email_routing=True,
        verification_method=OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
    )

    with published(MANUAL_RECORDS):
        response = admin_client.post(url(row))

    assert response.status_code == 200, response.data
    assert response.data["sending_status"] == "pending"
    assert "_showdesk TXT record" in response.data["sending_last_error"]
    row.refresh_from_db()
    assert row.status == OrganizationDomain.Status.VERIFIED
    assert row.verification_method == OrganizationDomain.VerificationMethod.ADMIN_EMAIL
    assert row.verification_token
    assert response.data["sending_dns_records"][0] == {
        "type": "TXT",
        "name": "_showdesk.acme.com",
        "value": f"showdesk-verification={row.verification_token}",
    }

    proven = {**MANUAL_RECORDS, "_showdesk.acme.com": [row.txt_record_value]}
    with published(proven):
        assert check_sending(row) == CheckStatus.VERIFIED
    with published(MANUAL_RECORDS):
        assert check_sending(row) == CheckStatus.PENDING
    row.refresh_from_db()
    assert row.sending_status == "pending"  # A regression.
    with published({**proven, "_showdesk.acme.com": None}):
        assert check_sending(row) == CheckStatus.UNKNOWN


def test_another_organization_token_does_not_prove_ours(admin_client, organization):
    """The real owner's `_showdesk` TXT, published for its own row, leaves a
    squatter's row pending."""
    row = owned(organization, verification_token="ours")
    with published({}):
        assert admin_client.post(url(row)).status_code == 200
    row.refresh_from_db()

    theirs = {**MANUAL_RECORDS, "_showdesk.acme.com": ["showdesk-verification=theirs"]}
    with published(theirs):
        assert check_sending(row) == CheckStatus.PENDING
    row.refresh_from_db()
    assert row.sending_status == "pending"
    assert "_showdesk TXT record" in row.sending_last_error


def test_a_domain_set_up_under_another_provider_shows_as_not_set_up(
    admin_client, organization
):
    """Until the periodic check resets it, the row isn't shown as set up."""
    row = owned(
        organization,
        is_sending=True,
        sending_status="verified",
        sending_provider="scaleway_tem",
        sending_provider_ref="tem-id",
        sending_dns_records=[{"type": "TXT", "name": "acme.com", "value": "x"}],
        sending_last_error="SPF: add include:x.",
    )

    response = admin_client.get(f"/api/v1/organization-domains/{row.id}/")

    assert response.status_code == 200, response.data
    assert response.data["sending_status"] == ""
    assert response.data["sending_dns_records"] == []
    assert response.data["sending_last_error"] == ""
    assert response.data["is_sending"] is True


def test_check_now(admin_client, organization):
    row = owned(organization)
    response = admin_client.post(url(row, "check/"))
    assert response.status_code == 400
    assert response.data["code"] == "not_registered"

    with published({}):
        admin_client.post(url(row))
    row.refresh_from_db()
    good = {**MANUAL_RECORDS, "_showdesk.acme.com": [row.txt_record_value]}
    with published(good):
        first = admin_client.post(url(row, "check/"))
        second = admin_client.post(url(row, "check/"))

    assert first.status_code == 200, first.data
    assert first.data["sending_status"] == "verified"
    assert second.status_code == 429
    assert second.data["code"] == "too_soon"


def test_disable_resets_the_sending_state(admin_client, organization):
    row = owned(organization)
    with published({}):
        admin_client.post(url(row))

    response = admin_client.delete(url(row))

    assert response.status_code == 200, response.data
    assert response.data["sending_status"] == ""
    assert response.data["sending_dns_records"] == []
    row.refresh_from_db()
    assert row.sending_provider_ref == ""


def test_admins_of_the_organization_only(authenticated_client, organization, settings):
    row = owned(organization)
    stranger = APIClient()
    stranger.force_authenticate(AdminFactory(organization=OrganizationFactory()))

    assert authenticated_client.post(url(row)).status_code == 403
    assert authenticated_client.post(url(row, "check/")).status_code == 403
    assert authenticated_client.delete(url(row)).status_code == 403
    assert stranger.post(url(row)).status_code == 404
    assert stranger.post(url(row, "check/")).status_code == 404
    assert stranger.delete(url(row)).status_code == 404


def test_not_there_without_a_provider(admin_client, organization, settings):
    settings.SENDING_DOMAIN_PROVIDER = "none"
    row = owned(organization)

    assert admin_client.post(url(row)).status_code == 404
    assert admin_client.post(url(row, "check/")).status_code == 404
    assert admin_client.delete(url(row)).status_code == 404


def test_a_transfer_under_manual_leaves_nothing_to_remove(
    admin_client, organization, django_capture_on_commit_callbacks
):
    """`manual` registers nothing anywhere: the new owner sets up at once."""
    from apps.email_channel.sending.services import on_ownership_verified

    previous = owned(OrganizationFactory())
    theirs = APIClient()
    theirs.force_authenticate(AdminFactory(organization=previous.organization))
    with published({}):
        assert theirs.post(url(previous)).status_code == 200

    # `organization` wins the domain.
    OrganizationDomain.objects.filter(pk=previous.pk).update(
        status=OrganizationDomain.Status.FAILED
    )
    row = owned(organization)
    with django_capture_on_commit_callbacks(execute=True):
        on_ownership_verified(row)

    assert not SendingRemoval.objects.exists()
    with published({}):
        response = admin_client.post(url(row))
    assert response.status_code == 200, response.data
    assert response.data["sending_status"] == "pending"


def test_the_instance_own_domain_is_still_an_organization_brand(
    admin_client, organization, settings
):
    """An organization owning the From domain proves it for its branding, but
    can't send from it: it is the instance's."""
    settings.DEFAULT_FROM_EMAIL = "Acme support <noreply@acme.com>"
    response = admin_client.post(
        "/api/v1/organization-domains/",
        {"domain": "acme.com", "is_branding": True},
        format="json",
    )
    assert response.status_code == 201, response.data
    row = OrganizationDomain.objects.get(pk=response.data["id"])
    with mock.patch("apps.organizations.services.verify_domain_dns", return_value=True):
        response = admin_client.post(f"/api/v1/organization-domains/{row.id}/verify/")
    assert response.data["status"] == "verified"

    response = admin_client.post(url(row))

    assert response.status_code == 400
    assert response.data["code"] == "operator_domain"
