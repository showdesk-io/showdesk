"""Companies API: scoping, filters, edits, permissions and query counts."""

import json
import warnings
from datetime import UTC, datetime

import pytest
from django.core.paginator import UnorderedObjectListWarning
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.contacts.models import Company, Contact
from apps.contacts.serializers import CompanySerializer
from apps.contacts.views import CompanyViewSet
from tests.factories import (
    CompanyAttributeDefFactory,
    CompanyFactory,
    ContactAttributeDefFactory,
    ContactFactory,
    EndUserFactory,
    OrganizationFactory,
    TagFactory,
    TicketFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/companies/"
NO_ID = "00000000-0000-4000-8000-000000000000"


def _ids(res) -> list[str]:
    return [row["id"] for row in res.data["results"]]


def _detail(company) -> str:
    return f"{URL}{company.id}/"


# Listing and scoping


def test_list_is_scoped_to_org(authenticated_client, organization):
    mine = CompanyFactory(organization=organization)
    CompanyFactory(organization=OrganizationFactory())
    res = authenticated_client.get(URL)
    assert res.status_code == 200
    assert _ids(res) == [str(mine.id)]


def test_list_counts_arent_multiplied_by_the_joins(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    first = ContactFactory(organization=organization, company=company)
    second = ContactFactory(organization=organization, company=company)
    ContactFactory(organization=organization)
    for contact, status in (
        (first, "open"),
        (first, "in_progress"),
        (first, "closed"),
        (second, "waiting"),
        (second, "resolved"),
    ):
        TicketFactory(organization=organization, contact=contact, status=status)
    row = authenticated_client.get(URL).data["results"][0]
    assert (row["contacts_count"], row["open_tickets_count"]) == (2, 3)


def test_counts_ignore_rows_of_another_org(authenticated_client, organization):
    """They agree with the ``contacts`` and ``tickets`` actions."""
    company = CompanyFactory(organization=organization)
    contact = ContactFactory(organization=organization, company=company)
    TicketFactory(organization=OrganizationFactory(), contact=contact, status="open")
    ContactFactory(organization=OrganizationFactory(), company=company)
    row = authenticated_client.get(URL).data["results"][0]
    assert (row["contacts_count"], row["open_tickets_count"]) == (1, 0)
    assert len(authenticated_client.get(f"{_detail(company)}contacts/").data) == 1
    assert len(authenticated_client.get(f"{_detail(company)}tickets/").data) == 0


def test_list_is_ordered_by_name_then_id(authenticated_client, organization):
    """The counts' GROUP BY makes Django drop ``Meta.ordering``."""
    twins = sorted(
        (CompanyFactory(organization=organization, name="Same") for _ in range(3)),
        key=lambda company: company.id,
    )
    last = CompanyFactory(organization=organization, name="Zed")
    first = CompanyFactory(organization=organization, name="Acme")
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnorderedObjectListWarning)
        res = authenticated_client.get(URL)
    assert _ids(res) == [str(c.id) for c in (first, *twins, last)]


def test_ordering_stays_stable_on_equal_values(authenticated_client, organization):
    companies = sorted(
        (CompanyFactory(organization=organization, mrr_cents=5) for _ in range(3)),
        key=lambda company: company.id,
    )
    res = authenticated_client.get(URL, {"ordering": "-mrr_cents"})
    assert _ids(res) == [str(c.id) for c in companies]


def test_ordering_keeps_companies_without_mrr_last(authenticated_client, organization):
    none = CompanyFactory(organization=organization, mrr_cents=None)
    low = CompanyFactory(organization=organization, mrr_cents=1)
    high = CompanyFactory(organization=organization, mrr_cents=2)
    for ordering, expected in (
        ("-mrr_cents", [high, low, none]),
        ("mrr_cents", [low, high, none]),
    ):
        res = authenticated_client.get(URL, {"ordering": ordering})
        assert _ids(res) == [str(c.id) for c in expected]


def test_unknown_ordering_field_is_ignored(authenticated_client, organization):
    CompanyFactory(organization=organization)
    for ordering in ("organization__api_token", "garbage", "-contacts__id"):
        res = authenticated_client.get(URL, {"ordering": ordering})
        assert res.status_code == 200
        assert res.data["count"] == 1


def test_page_size_is_capped(authenticated_client, organization):
    CompanyFactory.create_batch(101, organization=organization)
    assert len(authenticated_client.get(URL).data["results"]) == 25
    res = authenticated_client.get(URL, {"page_size": 100000})
    assert len(res.data["results"]) == 100


# Filters


def test_search_by_name_domain_and_external_id(authenticated_client, organization):
    acme = CompanyFactory(
        organization=organization, name="Acme", domain="acme.io", external_id="host-1"
    )
    CompanyFactory(organization=organization, name="Other", domain="other.io")
    for term in ("acm", "acme.io", "host-1"):
        assert _ids(authenticated_client.get(URL, {"search": term})) == [str(acme.id)]


def test_search_with_a_nul_character_is_a_400(authenticated_client, organization):
    CompanyFactory(organization=organization)
    assert authenticated_client.get(URL, {"search": "a\x00b"}).status_code == 400


def test_attribute_filter(authenticated_client, organization):
    pro = CompanyFactory(organization=organization, attributes={"tier": "pro", "n": 3})
    CompanyFactory(organization=organization, attributes={"tier": "free"})
    assert _ids(authenticated_client.get(URL, {"attr.tier": "pro"})) == [str(pro.id)]
    assert _ids(authenticated_client.get(URL, {"attr.n": "3"})) == [str(pro.id)]


def test_filters_dont_reach_another_org(authenticated_client, organization):
    CompanyFactory(
        organization=OrganizationFactory(), name="Secret", attributes={"t": "secret"}
    )
    for params in ({"search": "Secret"}, {"attr.t": "secret"}):
        assert _ids(authenticated_client.get(URL, params)) == []


@pytest.mark.parametrize("key", ["attr.a__b"])
def test_unsafe_attribute_keys_are_ignored(authenticated_client, organization, key):
    CompanyFactory(organization=organization, attributes={"a": {"b": "x"}})
    res = authenticated_client.get(URL, {key: "x"})
    assert res.status_code == 200
    assert res.data["count"] == 1


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("", {"search": "nobody"}),
        ("", {"attr.tier": "nope"}),
        ("contacts/", {"search": "nobody"}),
        ("tickets/", {"attr.tier": "nope"}),
    ],
)
def test_filters_only_apply_to_the_list(
    authenticated_client, organization, path, params
):
    company = CompanyFactory(organization=organization, attributes={"tier": "pro"})
    res = authenticated_client.get(f"{_detail(company)}{path}", params)
    assert res.status_code == 200


def test_patch_out_of_the_filter_it_was_sent_with_is_no_error(
    authenticated_client, organization
):
    CompanyAttributeDefFactory(organization=organization, key="tier")
    company = CompanyFactory(organization=organization, attributes={"tier": "pro"})
    res = authenticated_client.patch(
        f"{_detail(company)}?attr.tier=pro",
        {"attributes": {"tier": "free"}},
        format="json",
    )
    assert res.status_code == 200


# Create


def test_create_normalizes_the_domain(authenticated_client, organization):
    res = authenticated_client.post(
        URL, {"name": "Acme", "domain": "  ACME.io. "}, format="json"
    )
    assert res.status_code == 201
    assert res.data["domain"] == "acme.io"
    assert (res.data["contacts_count"], res.data["open_tickets_count"]) == (0, 0)
    assert Company.objects.get(pk=res.data["id"]).organization == organization


@pytest.mark.parametrize("domain", ["not a domain", "x.io..", "a\x00.io", None])
def test_malformed_domain_is_400(authenticated_client, organization, domain):
    company = CompanyFactory(organization=organization, domain="kept.io")
    body = json.dumps({"name": "Acme", "domain": domain})
    res = authenticated_client.post(URL, body, content_type="application/json")
    assert res.status_code == 400
    assert "domain" in res.data
    res = authenticated_client.patch(
        _detail(company), body, content_type="application/json"
    )
    assert res.status_code == 400
    company.refresh_from_db()
    assert company.domain == "kept.io"


@pytest.mark.parametrize("domain", ["", "   "])
def test_several_companies_can_have_no_domain(
    authenticated_client, organization, domain
):
    for name in ("One", "Two"):
        res = authenticated_client.post(
            URL, {"name": name, "domain": domain}, format="json"
        )
        assert res.status_code == 201
        assert res.data["domain"] == ""


def test_international_domain_is_accepted(authenticated_client):
    res = authenticated_client.post(
        URL, {"name": "M", "domain": "MÜNCHEN.de"}, format="json"
    )
    assert res.status_code == 201
    assert res.data["domain"] == "münchen.de"


@pytest.mark.parametrize("domain", ["dup.io", "DUP.io", "dup.io."])
def test_create_duplicate_domain_is_400(authenticated_client, organization, domain):
    CompanyFactory(organization=organization, domain="dup.io")
    res = authenticated_client.post(
        URL, {"name": "Acme", "domain": domain}, format="json"
    )
    assert res.status_code == 400
    assert "domain" in res.data


def test_same_domain_in_another_org_is_allowed(authenticated_client):
    CompanyFactory(organization=OrganizationFactory(), domain="dup.io")
    res = authenticated_client.post(
        URL, {"name": "Acme", "domain": "dup.io"}, format="json"
    )
    assert res.status_code == 201


def test_create_ignores_server_side_fields(authenticated_client, organization):
    other = OrganizationFactory()
    CompanyFactory(organization=organization, external_id="taken")
    res = authenticated_client.post(
        URL,
        {
            "name": "Acme",
            "organization": str(other.id),
            "external_id": "taken",
            "contacts_count": 9,
        },
        format="json",
    )
    assert res.status_code == 201
    company = Company.objects.get(pk=res.data["id"])
    assert company.organization == organization
    assert company.external_id == ""
    assert res.data["contacts_count"] == 0


def test_create_validates_attributes(authenticated_client, organization):
    CompanyAttributeDefFactory(organization=organization, key="seats", type="number")
    # A definition of the other entity gives no right to store its key here.
    ContactAttributeDefFactory(organization=organization, key="role")
    res = authenticated_client.post(
        URL,
        {"name": "Acme", "attributes": {"seats": "3", "junk": 1, "role": "x"}},
        format="json",
    )
    assert res.status_code == 201
    assert res.data["attributes"] == {"seats": 3}


def test_attribute_defined_only_in_another_org_is_dropped(
    authenticated_client, organization
):
    CompanyAttributeDefFactory(organization=OrganizationFactory(), key="tier")
    company = CompanyFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(company), {"attributes": {"tier": "gold"}}, format="json"
    )
    assert res.status_code == 200
    assert res.data["attributes"] == {}
    res = authenticated_client.post(
        URL, {"name": "Acme", "attributes": {"tier": "gold"}}, format="json"
    )
    assert res.status_code == 201
    assert res.data["attributes"] == {}


def test_impersonation_validates_attributes_on_the_impersonated_org(organization):
    other = OrganizationFactory()
    CompanyAttributeDefFactory(organization=other, key="tier")
    CompanyAttributeDefFactory(organization=organization, key="mine")
    company = CompanyFactory(organization=other)
    client = APIClient()
    client.force_authenticate(UserFactory(organization=organization, is_superuser=True))
    res = client.patch(
        _detail(company),
        {"attributes": {"tier": "gold", "mine": "x"}},
        format="json",
        HTTP_X_SHOWDESK_ORG=str(other.id),
    )
    assert res.status_code == 200
    assert res.data["attributes"] == {"tier": "gold"}


def test_patch_moves_updated_at(authenticated_client, organization):
    company = CompanyFactory(organization=organization, name="Acme")
    before = company.updated_at
    res = authenticated_client.patch(_detail(company), {"name": "New"}, format="json")
    assert res.status_code == 200
    company.refresh_from_db()
    assert company.updated_at > before


@pytest.mark.parametrize("value", ["text", None])
def test_attributes_must_be_an_object(authenticated_client, organization, value):
    company = CompanyFactory(organization=organization, attributes={"tier": "pro"})
    res = authenticated_client.patch(
        _detail(company), {"attributes": value}, format="json"
    )
    assert res.status_code == 400
    assert "attributes" in res.data
    company.refresh_from_db()
    assert company.attributes == {"tier": "pro"}
    res = authenticated_client.post(
        URL, {"name": "Acme", "attributes": value}, format="json"
    )
    assert res.status_code == 400


@pytest.mark.parametrize("body", [{}, {"name": "   "}])
def test_a_name_is_required(authenticated_client, organization, body):
    res = authenticated_client.post(
        URL, json.dumps(body), content_type="application/json"
    )
    assert res.status_code == 400
    assert "name" in res.data
    assert not Company.objects.filter(organization=organization).exists()


@pytest.mark.parametrize(
    "body",
    [
        {"logo_url": "javascript:alert(1)"},
        {"signed_up_at": "9999-12-31T23:59:59-23:59"},
    ],
)
def test_invalid_fields_are_400(authenticated_client, organization, body):
    company = CompanyFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(company), json.dumps(body), content_type="application/json"
    )
    assert res.status_code == 400


def test_all_the_profile_fields_can_be_set(authenticated_client, organization):
    res = authenticated_client.post(
        URL,
        {
            "name": "Acme",
            "logo_url": "https://x.io/l.png",
            "industry": "Retail",
            "size": "11-50",
            "website": "https://x.io",
            "plan": "pro",
            "mrr_cents": 5000,
            "health_score": 80,
            "signed_up_at": "2026-01-01T00:00:00Z",
            "churned_at": "2026-02-01T00:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 201
    company = Company.objects.get(pk=res.data["id"])
    assert (company.mrr_cents, company.health_score) == (5000, 80)
    assert company.signed_up_at == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("body", [[], "text", 1, None])
def test_a_body_that_isnt_an_object_is_400(authenticated_client, organization, body):
    company = CompanyFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(company), json.dumps(body), content_type="application/json"
    )
    assert res.status_code == 400


# Patch


def test_patch_merges_attributes(authenticated_client, organization):
    CompanyAttributeDefFactory(organization=organization, key="tier")
    CompanyAttributeDefFactory(organization=organization, key="region")
    company = CompanyFactory(organization=organization, attributes={"tier": "pro"})
    res = authenticated_client.patch(
        _detail(company),
        {"attributes": {"region": "eu", "junk": 1}},
        format="json",
    )
    assert res.data["attributes"] == {"tier": "pro", "region": "eu"}


def test_patch_copes_with_any_stored_attributes(authenticated_client, organization):
    CompanyAttributeDefFactory(organization=organization, key="tier")
    company = CompanyFactory(organization=organization)
    Company.objects.filter(pk=company.pk).update(attributes=[1])
    res = authenticated_client.patch(
        _detail(company), {"attributes": {"tier": "pro"}}, format="json"
    )
    assert res.status_code == 200
    assert res.data["attributes"] == {"tier": "pro"}


def test_patch_normalizes_the_domain(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(company), {"domain": " NEW.io. "}, format="json"
    )
    assert res.status_code == 200
    assert res.data["domain"] == "new.io"
    res = authenticated_client.patch(_detail(company), {"domain": ""}, format="json")
    assert res.status_code == 200
    assert res.data["domain"] == ""


def test_patch_to_a_domain_in_use_is_400(authenticated_client, organization):
    CompanyFactory(organization=organization, domain="dup.io")
    company = CompanyFactory(organization=organization, domain="a.io")
    for domain in ("dup.io", "DUP.io", "dup.io."):
        res = authenticated_client.patch(
            _detail(company), {"domain": domain}, format="json"
        )
        assert res.status_code == 400
        assert "domain" in res.data
    company.refresh_from_db()
    assert company.domain == "a.io"


def test_patch_to_its_own_domain_is_no_conflict(authenticated_client, organization):
    company = CompanyFactory(organization=organization, domain="a.io")
    res = authenticated_client.patch(
        _detail(company), {"domain": "A.IO"}, format="json"
    )
    assert res.status_code == 200


def test_lost_domain_race_is_400(authenticated_client, organization, monkeypatch):
    """The check passed, then another request took the domain: see also the real
    race in test_companies_api_concurrency.py."""
    monkeypatch.setattr(CompanySerializer, "validate", lambda self, attrs: attrs)
    CompanyFactory(organization=organization, domain="dup.io")
    company = CompanyFactory(organization=organization, domain="a.io")
    res = authenticated_client.patch(
        _detail(company), {"domain": "dup.io"}, format="json"
    )
    assert res.status_code == 400
    assert "domain" in res.data
    res = authenticated_client.post(
        URL, {"name": "Acme", "domain": "dup.io"}, format="json"
    )
    assert res.status_code == 400
    assert "domain" in res.data


def test_any_other_refusal_of_the_database_is_a_400(
    authenticated_client, organization, monkeypatch
):
    def refuse(*args, **kwargs):
        raise IntegrityError("some other constraint")

    company = CompanyFactory(organization=organization)
    monkeypatch.setattr(Company, "save", refuse)
    for res in (
        authenticated_client.patch(_detail(company), {"name": "B"}, format="json"),
        authenticated_client.post(URL, {"name": "B"}, format="json"),
    ):
        assert res.status_code == 400
        assert "non_field_errors" in res.data


@pytest.mark.parametrize("external_id", ["new", "taken", "", "x" * 300])
def test_external_id_is_read_only(authenticated_client, organization, external_id):
    """It's what a signed widget payload upserts a company on, as with a contact."""
    CompanyFactory(organization=organization, external_id="taken")
    company = CompanyFactory(organization=organization, external_id="u1")
    res = authenticated_client.patch(
        _detail(company), {"external_id": external_id}, format="json"
    )
    assert res.status_code == 200
    assert res.data["external_id"] == "u1"
    company.refresh_from_db()
    assert company.external_id == "u1"


def test_editing_the_domain_doesnt_relink_contacts(authenticated_client, organization):
    company = CompanyFactory(organization=organization, domain="old.io")
    linked = ContactFactory(
        organization=organization, company=company, email="a@old.io"
    )
    unlinked = ContactFactory(organization=organization, email="b@new.io")
    res = authenticated_client.patch(
        _detail(company), {"domain": "new.io"}, format="json"
    )
    assert res.status_code == 200
    linked.refresh_from_db()
    unlinked.refresh_from_db()
    assert linked.company == company
    assert unlinked.company is None


def _stale(monkeypatch, company):
    """Make the view work from ``company`` as it was read before later changes."""
    monkeypatch.setattr(CompanyViewSet, "get_object", lambda self: company)


def test_patch_writes_only_its_fields_and_merges_on_the_current_row(
    authenticated_client, organization, monkeypatch
):
    CompanyAttributeDefFactory(organization=organization, key="tier")
    CompanyAttributeDefFactory(organization=organization, key="region")
    company = CompanyFactory(organization=organization, plan="old", attributes={})
    _stale(monkeypatch, company)
    Company.objects.filter(pk=company.pk).update(plan="new", attributes={"tier": "pro"})
    res = authenticated_client.patch(
        _detail(company), {"attributes": {"region": "eu"}}, format="json"
    )
    assert res.status_code == 200
    row = Company.objects.get(pk=company.pk)
    assert row.plan == "new"
    assert row.attributes == {"tier": "pro", "region": "eu"}


def test_patch_locks_the_row_without_blocking_references(
    authenticated_client, organization
):
    company = CompanyFactory(organization=organization)
    with CaptureQueriesContext(connection) as queries:
        authenticated_client.patch(_detail(company), {"name": "B"}, format="json")
    sql = [query["sql"] for query in queries]
    assert any("FOR NO KEY UPDATE" in q and '"contacts_company"' in q for q in sql)
    update = next(q for q in sql if q.startswith('UPDATE "contacts_company"'))
    assert '"plan"' not in update


def test_patch_response_keeps_the_counts(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    contact = ContactFactory(organization=organization, company=company)
    TicketFactory(organization=organization, contact=contact, status="open")
    res = authenticated_client.patch(_detail(company), {"name": "B"}, format="json")
    assert (res.data["contacts_count"], res.data["open_tickets_count"]) == (1, 1)


def test_patch_changing_nothing_writes_nothing(authenticated_client, organization):
    company = CompanyFactory(organization=organization, name="Acme")
    before = company.updated_at
    for body in ({}, {"name": "Acme"}):
        res = authenticated_client.patch(_detail(company), body, format="json")
        assert res.status_code == 200
    company.refresh_from_db()
    assert company.updated_at == before


def test_put_isnt_offered(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    res = authenticated_client.put(_detail(company), {"name": "A"}, format="json")
    assert res.status_code == 405


# Delete


def test_delete_requires_admin(authenticated_client, admin_client, organization):
    company = CompanyFactory(organization=organization)
    assert authenticated_client.delete(_detail(company)).status_code == 403
    assert Company.objects.filter(pk=company.pk).exists()
    assert admin_client.delete(_detail(company)).status_code == 204
    assert not Company.objects.filter(pk=company.pk).exists()


def test_delete_keeps_the_contacts_and_their_tickets(admin_client, organization):
    company = CompanyFactory(organization=organization)
    contact = ContactFactory(organization=organization, company=company)
    ticket = TicketFactory(organization=organization, contact=contact)
    assert admin_client.delete(_detail(company)).status_code == 204
    contact.refresh_from_db()
    ticket.refresh_from_db()
    assert contact.company is None
    assert ticket.contact == contact


# Other organizations, permissions


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("patch", ""),
        ("delete", ""),
        ("get", "contacts/"),
        ("get", "tickets/"),
    ],
)
def test_other_org_company_is_404(admin_client, method, path):
    other = CompanyFactory(organization=OrganizationFactory(), name="Theirs")
    res = getattr(admin_client, method)(
        f"{_detail(other)}{path}", {"name": "Mine"}, format="json"
    )
    assert res.status_code == 404
    other.refresh_from_db()
    assert other.name == "Theirs"


@pytest.mark.parametrize("pk", ["not-a-uuid", "1", "a%00b", NO_ID])
def test_malformed_or_unknown_id_is_404(authenticated_client, pk):
    assert authenticated_client.get(f"{URL}{pk}/").status_code == 404


def test_anonymous_request_is_refused(organization):
    company = CompanyFactory(organization=organization)
    client = APIClient()
    assert client.get(URL).status_code == 401
    assert client.get(_detail(company)).status_code == 401


def test_end_users_are_refused(organization):
    company = CompanyFactory(organization=organization)
    client = APIClient()
    client.force_authenticate(EndUserFactory(organization=organization))
    assert client.get(URL).status_code == 403
    assert client.get(_detail(company)).status_code == 403
    assert client.post(URL, {"name": "A"}, format="json").status_code == 403
    assert client.get(f"{_detail(company)}contacts/").status_code == 403
    assert client.get(f"{_detail(company)}tickets/").status_code == 403


def test_a_user_without_organization_is_refused():
    client = APIClient()
    client.force_authenticate(UserFactory(organization=None, is_superuser=True))
    assert client.get(URL).status_code == 403
    assert client.post(URL, {"name": "A"}, format="json").status_code == 403


# Contacts and tickets of a company


def test_contacts_lists_its_contacts_with_their_counts(
    authenticated_client, organization
):
    company = CompanyFactory(organization=organization)
    bob = ContactFactory(organization=organization, company=company, name="Bob")
    alice = ContactFactory(organization=organization, company=company, name="Alice")
    ContactFactory(organization=organization)
    TicketFactory(organization=organization, contact=alice, status="open")
    TicketFactory(organization=organization, contact=alice, status="closed")
    rows = authenticated_client.get(f"{_detail(company)}contacts/").data
    assert [row["id"] for row in rows] == [str(alice.id), str(bob.id)]
    assert (rows[0]["tickets_count"], rows[0]["open_tickets_count"]) == (2, 1)
    assert rows[0]["company_detail"]["name"] == company.name


def test_contacts_are_stably_ordered_on_equal_names(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    twins = sorted(
        (
            ContactFactory(organization=organization, company=company, name="Same")
            for _ in range(3)
        ),
        key=lambda contact: contact.id,
    )
    rows = authenticated_client.get(f"{_detail(company)}contacts/").data
    assert [row["id"] for row in rows] == [str(c.id) for c in twins]


def test_contacts_are_capped(authenticated_client, organization, monkeypatch):
    monkeypatch.setattr("apps.contacts.views.COMPANY_CONTACTS_LIMIT", 2)
    company = CompanyFactory(organization=organization)
    ContactFactory.create_batch(3, organization=organization, company=company)
    assert len(authenticated_client.get(f"{_detail(company)}contacts/").data) == 2


def test_tickets_cover_all_its_contacts_newest_first(
    authenticated_client, organization
):
    company = CompanyFactory(organization=organization)
    first = ContactFactory(organization=organization, company=company)
    second = ContactFactory(organization=organization, company=company)
    TicketFactory(organization=organization, contact=ContactFactory())
    old = TicketFactory(organization=organization, contact=first)
    new = TicketFactory(organization=organization, contact=second)
    rows = authenticated_client.get(f"{_detail(company)}tickets/").data
    assert [row["id"] for row in rows] == [str(new.id), str(old.id)]
    assert [row["message_count"] for row in rows] == [0, 0]


def test_a_contact_moved_elsewhere_takes_its_tickets_along(
    authenticated_client, organization
):
    company = CompanyFactory(organization=organization)
    contact = ContactFactory(organization=organization, company=company)
    TicketFactory(organization=organization, contact=contact)
    Contact.objects.filter(pk=contact.pk).update(company=None)
    assert authenticated_client.get(f"{_detail(company)}tickets/").data == []


# Query counts


def _queries(client, url, **params) -> int:
    with CaptureQueriesContext(connection) as queries:
        assert client.get(url, params).status_code == 200
    return len(queries)


def test_list_has_no_n_plus_one(authenticated_client, organization):
    def add_companies(count):
        for _ in range(count):
            company = CompanyFactory(organization=organization)
            contact = ContactFactory(organization=organization, company=company)
            TicketFactory(organization=organization, contact=contact)

    add_companies(2)
    few = _queries(authenticated_client, URL)
    add_companies(10)
    assert _queries(authenticated_client, URL) == few
    assert few <= 2


def test_contacts_have_no_n_plus_one(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    url = f"{_detail(company)}contacts/"

    def add_contacts(count):
        for _ in range(count):
            contact = ContactFactory(organization=organization, company=company)
            TicketFactory(organization=organization, contact=contact)

    add_contacts(2)
    few = _queries(authenticated_client, url)
    add_contacts(10)
    assert _queries(authenticated_client, url) == few
    assert few <= 2


def test_tickets_have_no_n_plus_one(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    url = f"{_detail(company)}tickets/"

    def add_tickets(count):
        for _ in range(count):
            ticket = TicketFactory(
                organization=organization,
                contact=ContactFactory(organization=organization, company=company),
                assigned_agent=UserFactory(organization=organization),
            )
            ticket.tags.add(TagFactory(organization=organization))

    add_tickets(2)
    few = _queries(authenticated_client, url)
    add_tickets(10)
    assert _queries(authenticated_client, url) == few
    assert few <= 3
