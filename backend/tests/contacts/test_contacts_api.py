"""Contacts API: scoping, filters, edits, permissions and query counts."""

import json
import warnings
from datetime import timedelta

import pytest
from django.core.paginator import UnorderedObjectListWarning
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact, ContactNote
from apps.contacts.serializers import ContactSerializer
from apps.contacts.views import ContactViewSet
from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from tests.factories import (
    AdminFactory,
    CompanyFactory,
    ContactAttributeDefFactory,
    ContactFactory,
    ContactNoteFactory,
    EndUserFactory,
    OrganizationFactory,
    TagFactory,
    TicketFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/contacts/"


def _ids(res) -> list[str]:
    return [row["id"] for row in res.data["results"]]


def _detail(contact) -> str:
    return f"{URL}{contact.id}/"


# Listing and scoping


def test_list_is_scoped_to_org(authenticated_client, organization):
    mine = ContactFactory(organization=organization)
    ContactFactory(organization=OrganizationFactory())
    res = authenticated_client.get(URL)
    assert res.status_code == 200
    assert _ids(res) == [str(mine.id)]


def test_list_includes_counts(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=organization, contact=contact, status="open")
    TicketFactory(organization=organization, contact=contact, status="closed")
    row = authenticated_client.get(URL).data["results"][0]
    assert (row["open_tickets_count"], row["tickets_count"]) == (1, 2)
    assert row["email_verified"] is False


def test_list_is_ordered_by_default(authenticated_client, organization):
    """The ticket counts' GROUP BY makes Django drop ``Meta.ordering``."""
    now = timezone.now()
    never = ContactFactory(organization=organization, last_seen_at=None)
    old = ContactFactory(
        organization=organization, last_seen_at=now - timedelta(days=1)
    )
    new = ContactFactory(organization=organization, last_seen_at=now)
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnorderedObjectListWarning)
        res = authenticated_client.get(URL)
    assert _ids(res) == [str(new.id), str(old.id), str(never.id)]


def test_page_size_is_capped(authenticated_client, organization):
    ContactFactory.create_batch(3, organization=organization)
    assert len(authenticated_client.get(URL, {"page_size": 2}).data["results"]) == 2
    res = authenticated_client.get(URL, {"page_size": 100000})
    assert res.status_code == 200
    assert res.data["count"] == 3


def test_page_size_above_the_cap_returns_the_cap(authenticated_client, organization):
    ContactFactory.create_batch(101, organization=organization, email="")
    res = authenticated_client.get(URL, {"page_size": 100000})
    assert len(res.data["results"]) == 100


def test_ordering_keeps_never_seen_contacts_last(authenticated_client, organization):
    now = timezone.now()
    never = ContactFactory(organization=organization, last_seen_at=None)
    old = ContactFactory(
        organization=organization, last_seen_at=now - timedelta(days=1)
    )
    new = ContactFactory(organization=organization, last_seen_at=now)
    for ordering, expected in (
        ("-last_seen_at", [new, old, never]),
        ("last_seen_at", [old, new, never]),
    ):
        res = authenticated_client.get(URL, {"ordering": ordering})
        assert _ids(res) == [str(c.id) for c in expected]


def test_unknown_ordering_field_is_ignored(authenticated_client, organization):
    ContactFactory(organization=organization)
    for ordering in ("organization__api_token", "garbage", "-tickets__id"):
        res = authenticated_client.get(URL, {"ordering": ordering})
        assert res.status_code == 200
        assert res.data["count"] == 1


# Filters


def test_search_and_attribute_filter(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, key="plan", type="string")
    ContactFactory(organization=organization, name="Alice", attributes={"plan": "pro"})
    ContactFactory(organization=organization, name="Bob", attributes={"plan": "free"})
    assert len(authenticated_client.get(URL, {"search": "ali"}).data["results"]) == 1
    res = authenticated_client.get(URL, {"attr.plan": "pro"})
    assert [c["name"] for c in res.data["results"]] == ["Alice"]


def test_search_covers_external_id(authenticated_client, organization):
    contact = ContactFactory(organization=organization, external_id="host-42")
    ContactFactory(organization=organization)
    assert _ids(authenticated_client.get(URL, {"search": "host-42"})) == [
        str(contact.id)
    ]


def test_search_with_a_nul_character_is_a_400(authenticated_client, organization):
    ContactFactory(organization=organization)
    assert authenticated_client.get(URL, {"search": "a\x00b"}).status_code == 400


def test_email_verified_filter(authenticated_client, organization):
    proven = ContactFactory(organization=organization, email_verified_at=timezone.now())
    unproven = ContactFactory(organization=organization)
    assert _ids(authenticated_client.get(URL, {"email_verified": "true"})) == [
        str(proven.id)
    ]
    assert _ids(authenticated_client.get(URL, {"email_verified": "false"})) == [
        str(unproven.id)
    ]
    assert authenticated_client.get(URL, {"email_verified": "x"}).data["count"] == 2


def test_last_seen_filters(authenticated_client, organization):
    now = timezone.now()
    old = ContactFactory(
        organization=organization, last_seen_at=now - timedelta(days=10)
    )
    new = ContactFactory(organization=organization, last_seen_at=now)
    cut = (now - timedelta(days=1)).isoformat()
    assert _ids(authenticated_client.get(URL, {"last_seen_after": cut})) == [
        str(new.id)
    ]
    assert _ids(authenticated_client.get(URL, {"last_seen_before": cut})) == [
        str(old.id)
    ]


@pytest.mark.parametrize(
    ("param", "value"),
    [
        ("last_seen_after", "garbage"),
        ("last_seen_before", "2026-13-45T00:00:00Z"),
        ("last_seen_after", "9999-12-31T23:59:59-23:59"),
        ("last_seen_before", "0001-01-01T00:00:00+23:59"),
    ],
)
def test_invalid_or_extreme_date_filter_is_no_error(
    authenticated_client, organization, param, value
):
    ContactFactory(organization=organization)
    assert authenticated_client.get(URL, {param: value}).status_code == 200


def test_naive_date_filter_needs_no_timezone(authenticated_client, organization):
    contact = ContactFactory(organization=organization, last_seen_at=timezone.now())
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        res = authenticated_client.get(URL, {"last_seen_after": "2000-01-01T00:00:00"})
    assert _ids(res) == [str(contact.id)]


def test_company_filter(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    linked = ContactFactory(organization=organization, company=company)
    ContactFactory(organization=organization)
    assert _ids(authenticated_client.get(URL, {"company": str(company.id)})) == [
        str(linked.id)
    ]


@pytest.mark.parametrize("value", ["not-a-uuid", "", "1", "a\x00b"])
def test_invalid_company_filter_is_ignored(authenticated_client, organization, value):
    ContactFactory(organization=organization)
    res = authenticated_client.get(URL, {"company": value})
    assert res.status_code == 200
    assert res.data["count"] == 1


def test_company_of_another_org_filters_nothing_in(authenticated_client, organization):
    other_org = OrganizationFactory()
    company = CompanyFactory(organization=other_org)
    ContactFactory(organization=other_org, company=company)
    ContactFactory(organization=organization)
    assert _ids(authenticated_client.get(URL, {"company": str(company.id)})) == []


def test_filters_dont_reach_another_org(authenticated_client, organization):
    ContactFactory(
        organization=OrganizationFactory(),
        name="Secret",
        attributes={"plan": "secret"},
    )
    for params in ({"search": "Secret"}, {"attr.plan": "secret"}):
        assert _ids(authenticated_client.get(URL, params)) == []


@pytest.mark.parametrize(
    "key",
    ["attr.a__b", "attr.", "attr.a.b", "attr.plan\n", "attr.a'b"],
)
def test_unsafe_attribute_keys_are_ignored(authenticated_client, organization, key):
    """No JSON path nor lookup: they filter nothing, and are never an error."""
    ContactFactory(organization=organization, attributes={"a": {"b": "x"}, "plan": "p"})
    ContactFactory(organization=organization, attributes={"plan": "q"})
    res = authenticated_client.get(URL, {key: "x"})
    assert res.status_code == 200
    assert res.data["count"] == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [("has_key", "plan"), ("isnull", "garbage"), ("regex", "(")],
)
def test_lookup_names_are_plain_keys(authenticated_client, organization, name, value):
    """``attributes__has_key=plan`` would be a lookup: this has to read the key."""
    ContactFactory(organization=organization, attributes={"plan": "pro"})
    res = authenticated_client.get(URL, {f"attr.{name}": value})
    assert res.status_code == 200
    assert _ids(res) == []


def test_a_key_named_like_a_lookup_can_be_filtered(authenticated_client, organization):
    contact = ContactFactory(organization=organization, attributes={"contains": "x"})
    ContactFactory(organization=organization, attributes={"contains": "y"})
    assert _ids(authenticated_client.get(URL, {"attr.contains": "x"})) == [
        str(contact.id)
    ]


def test_attribute_filter_is_an_exact_match(authenticated_client, organization):
    ContactFactory(organization=organization, attributes={"plan": "pro"})
    for value in ("pr", "PRO", "pro ", "%", "null"):
        assert _ids(authenticated_client.get(URL, {"attr.plan": value})) == []


def test_attribute_filter_reads_the_stored_types(authenticated_client, organization):
    contact = ContactFactory(
        organization=organization,
        attributes={
            "seats": 3,
            "ratio": 0.5,
            "vip": True,
            "label": "true",
            "code": "7",
        },
    )
    ContactFactory(organization=organization, attributes={"seats": 4, "vip": False})
    for key, value in (
        ("seats", "3"),
        ("ratio", "0.5"),
        ("vip", "true"),
        ("label", "true"),
        ("code", "7"),
    ):
        assert _ids(authenticated_client.get(URL, {f"attr.{key}": value})) == [
            str(contact.id)
        ]


def test_attribute_filter_doesnt_match_a_stored_null(
    authenticated_client, organization
):
    ContactFactory(organization=organization, attributes={"plan": None})
    assert _ids(authenticated_client.get(URL, {"attr.plan": "null"})) == []


@pytest.mark.parametrize("value", ["a\x00b", "9" * 5000, "1e999"])
def test_unusual_attribute_values_are_no_error(
    authenticated_client, organization, value
):
    ContactFactory(organization=organization, attributes={"plan": "pro"})
    res = authenticated_client.get(URL, {"attr.plan": value})
    assert res.status_code == 200
    assert _ids(res) == []


def test_filters_dont_apply_to_a_single_contact(authenticated_client, organization):
    contact = ContactFactory(organization=organization, name="Alice")
    res = authenticated_client.get(_detail(contact), {"search": "nobody"})
    assert res.status_code == 200


def test_patch_out_of_the_filter_it_was_sent_with_is_no_error(
    authenticated_client, organization
):
    before = CompanyFactory(organization=organization)
    after = CompanyFactory(organization=organization)
    contact = ContactFactory(organization=organization, company=before)
    res = authenticated_client.patch(
        f"{_detail(contact)}?company={before.id}",
        {"company": str(after.id)},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["company"] == after.id


# Create


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": "", "email": "", "phone": ""},
        {"name": "   ", "phone": "  "},
        {"job_title": "CTO", "attributes": {}},
    ],
)
def test_create_without_name_email_or_phone_is_400(
    authenticated_client, organization, body
):
    res = authenticated_client.post(URL, body, format="json")
    assert res.status_code == 400
    assert "non_field_errors" in res.data
    assert not Contact.objects.filter(organization=organization).exists()


@pytest.mark.parametrize(
    "body", [{"name": "Alice"}, {"email": "a@x.io"}, {"phone": "+33"}]
)
def test_create_with_any_of_name_email_or_phone(authenticated_client, body):
    assert authenticated_client.post(URL, body, format="json").status_code == 201


def test_patch_doesnt_require_a_name_email_or_phone(authenticated_client, organization):
    """A widget contact can have nothing but its external id, and stays editable."""
    contact = ContactFactory(
        organization=organization, name="", email="", external_id="u1"
    )
    res = authenticated_client.patch(
        _detail(contact), {"job_title": "CTO"}, format="json"
    )
    assert res.status_code == 200


def test_create_validates_attributes(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, key="seats", type="number")
    res = authenticated_client.post(
        URL,
        {"email": "New@X.io", "attributes": {"seats": "3"}},
        format="json",
    )
    assert res.status_code == 201
    assert res.data["email"] == "new@x.io"
    assert res.data["attributes"] == {"seats": 3}
    assert res.data["tickets_count"] == 0


def test_create_duplicate_email_is_400(authenticated_client, organization):
    ContactFactory(organization=organization, email="dup@x.io")
    res = authenticated_client.post(URL, {"email": "DUP@X.io"}, format="json")
    assert res.status_code == 400
    assert "email" in res.data


def test_same_email_in_another_org_is_allowed(authenticated_client):
    ContactFactory(organization=OrganizationFactory(), email="dup@x.io")
    res = authenticated_client.post(URL, {"email": "dup@x.io"}, format="json")
    assert res.status_code == 201


def test_create_ignores_server_side_fields(authenticated_client, organization):
    other = OrganizationFactory()
    res = authenticated_client.post(
        URL,
        {
            "email": "a@x.io",
            "organization": str(other.id),
            "external_id": "u1",
            "declared_email": "d@x.io",
            "email_verified_at": "2026-01-01T00:00:00Z",
            "is_anonymized": True,
            "last_seen_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 201
    contact = Contact.objects.get(pk=res.data["id"])
    assert contact.organization == organization
    assert contact.external_id == ""
    assert contact.declared_email == ""
    assert contact.email_verified_at is None
    assert contact.is_anonymized is False
    assert contact.last_seen_at is None


def test_create_with_a_company_of_another_org_is_400(
    authenticated_client, organization
):
    company = CompanyFactory(organization=OrganizationFactory())
    res = authenticated_client.post(
        URL, {"email": "a@x.io", "company": str(company.id)}, format="json"
    )
    assert res.status_code == 400
    assert "company" in res.data
    assert not Contact.objects.filter(organization=organization).exists()


# Patch


def test_patch_merges_attributes(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, key="plan", type="string")
    ContactAttributeDefFactory(organization=organization, key="role", type="string")
    contact = ContactFactory(organization=organization, attributes={"plan": "pro"})
    res = authenticated_client.patch(
        _detail(contact), {"attributes": {"role": "cto"}}, format="json"
    )
    assert res.data["attributes"] == {"plan": "pro", "role": "cto"}


def test_patch_copes_with_any_stored_attributes(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, key="role", type="string")
    contact = ContactFactory(organization=organization)
    Contact.objects.filter(pk=contact.pk).update(attributes=[1])
    res = authenticated_client.patch(
        _detail(contact), {"attributes": {"role": "cto"}}, format="json"
    )
    assert res.status_code == 200
    assert res.data["attributes"] == {"role": "cto"}


@pytest.mark.parametrize("value", [[], None])
def test_attributes_must_be_an_object(authenticated_client, organization, value):
    contact = ContactFactory(organization=organization, attributes={"plan": "pro"})
    res = authenticated_client.patch(
        _detail(contact), {"attributes": value}, format="json"
    )
    assert res.status_code == 400
    assert "attributes" in res.data
    contact.refresh_from_db()
    assert contact.attributes == {"plan": "pro"}
    res = authenticated_client.post(
        URL, {"email": "n@x.io", "attributes": value}, format="json"
    )
    assert res.status_code == 400


def test_email_verified_is_read_only(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    authenticated_client.patch(
        _detail(contact), {"email_verified_at": "2026-01-01T00:00:00Z"}, format="json"
    )
    contact.refresh_from_db()
    assert contact.email_verified_at is None


def test_declared_email_is_read_only_and_searchable(authenticated_client, organization):
    contact = ContactFactory(
        organization=organization, email="", declared_email="d@x.io"
    )
    res = authenticated_client.patch(
        _detail(contact), {"declared_email": "other@x.io"}, format="json"
    )
    assert res.data["declared_email"] == "d@x.io"
    contact.refresh_from_db()
    assert contact.declared_email == "d@x.io"
    assert _ids(authenticated_client.get(URL, {"search": "d@x.io"})) == [
        str(contact.id)
    ]


def test_changing_email_clears_verification(authenticated_client, organization):
    contact = ContactFactory(
        organization=organization, email_verified_at=timezone.now()
    )
    res = authenticated_client.patch(
        _detail(contact), {"email": "other@x.io"}, format="json"
    )
    assert res.data["email_verified"] is False
    contact.refresh_from_db()
    assert contact.email == "other@x.io"
    assert contact.email_verified_at is None


def test_blanking_email_clears_verification(authenticated_client, organization):
    contact = ContactFactory(
        organization=organization, email_verified_at=timezone.now()
    )
    res = authenticated_client.patch(_detail(contact), {"email": ""}, format="json")
    assert res.status_code == 200
    contact.refresh_from_db()
    assert (contact.email, contact.email_verified_at) == ("", None)


def test_same_email_in_another_case_keeps_verification(
    authenticated_client, organization
):
    contact = ContactFactory(
        organization=organization, email="a@x.io", email_verified_at=timezone.now()
    )
    res = authenticated_client.patch(
        _detail(contact), {"email": " A@X.io "}, format="json"
    )
    assert res.status_code == 200
    contact.refresh_from_db()
    assert contact.email == "a@x.io"
    assert contact.email_verified_at is not None


def test_patch_to_an_email_in_use_is_400(authenticated_client, organization):
    verified_at = timezone.now()
    ContactFactory(organization=organization, email="dup@x.io")
    contact = ContactFactory(
        organization=organization, email="a@x.io", email_verified_at=verified_at
    )
    for email in ("dup@x.io", "DUP@x.IO"):
        res = authenticated_client.patch(
            _detail(contact), {"email": email}, format="json"
        )
        assert res.status_code == 400
        assert "email" in res.data
    contact.refresh_from_db()
    assert (contact.email, contact.email_verified_at) == ("a@x.io", verified_at)


def test_lost_email_race_is_400(authenticated_client, organization, monkeypatch):
    """The check passed, then another request took the email: see also the real
    race in test_contacts_api_concurrency.py."""
    monkeypatch.setattr(ContactSerializer, "validate", lambda self, attrs: attrs)
    ContactFactory(organization=organization, email="dup@x.io")
    contact = ContactFactory(organization=organization, email="a@x.io")
    res = authenticated_client.patch(
        _detail(contact), {"email": "dup@x.io"}, format="json"
    )
    assert res.status_code == 400
    assert "email" in res.data
    res = authenticated_client.post(URL, {"email": "dup@x.io"}, format="json")
    assert res.status_code == 400
    assert "email" in res.data


@pytest.mark.parametrize(
    "external_id", ["new", "email:a@x.io", "company\nacme", "x" * 300]
)
def test_external_id_is_read_only(authenticated_client, organization, external_id):
    """It would give the widget user of that id access to this contact's history."""
    contact = ContactFactory(organization=organization, external_id="u1")
    res = authenticated_client.patch(
        _detail(contact), {"external_id": external_id}, format="json"
    )
    assert res.status_code == 200
    assert res.data["external_id"] == "u1"
    contact.refresh_from_db()
    assert contact.external_id == "u1"


def test_is_unsubscribed_is_editable_and_is_anonymized_isnt(
    authenticated_client, organization
):
    contact = ContactFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(contact),
        {"is_unsubscribed": True, "is_anonymized": True},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["is_unsubscribed"] is True
    assert res.data["is_anonymized"] is False
    contact.refresh_from_db()
    assert (contact.is_unsubscribed, contact.is_anonymized) == (True, False)


def test_company_can_be_set_and_cleared(authenticated_client, organization):
    company = CompanyFactory(organization=organization)
    contact = ContactFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(contact), {"company": str(company.id)}, format="json"
    )
    assert res.data["company"] == company.id
    assert res.data["company_detail"]["name"] == company.name
    res = authenticated_client.patch(_detail(contact), {"company": None}, format="json")
    assert res.data["company"] is None
    assert res.data["company_detail"] is None


def test_company_of_another_org_is_like_an_unknown_one(
    authenticated_client, organization
):
    """Same answer in both cases, so it doesn't tell which ids exist elsewhere."""
    contact = ContactFactory(organization=organization)
    foreign = CompanyFactory(organization=OrganizationFactory())
    res = authenticated_client.patch(
        _detail(contact), {"company": str(foreign.id)}, format="json"
    )
    assert res.status_code == 400
    contact.refresh_from_db()
    assert contact.company is None
    unknown = authenticated_client.patch(
        _detail(contact),
        {"company": "00000000-0000-4000-8000-000000000000"},
        format="json",
    )
    assert unknown.status_code == 400
    assert res.data["company"][0].replace(str(foreign.id), "") == unknown.data[
        "company"
    ][0].replace("00000000-0000-4000-8000-000000000000", "")


@pytest.mark.parametrize("value", ["not-a-uuid", []])
def test_malformed_company_is_400(authenticated_client, organization, value):
    contact = ContactFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(contact), {"company": value}, format="json"
    )
    assert res.status_code == 400


@pytest.mark.parametrize("body", [{"name": "a\x00b"}, {"email": None}])
def test_invalid_fields_are_400(authenticated_client, organization, body):
    contact = ContactFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(contact), json.dumps(body), content_type="application/json"
    )
    assert res.status_code == 400


@pytest.mark.parametrize("body", [[], "text", 1, None])
def test_a_body_that_isnt_an_object_is_400(authenticated_client, organization, body):
    contact = ContactFactory(organization=organization)
    for res in (
        authenticated_client.patch(
            _detail(contact), json.dumps(body), content_type="application/json"
        ),
        authenticated_client.post(
            f"{_detail(contact)}notes/",
            json.dumps(body),
            content_type="application/json",
        ),
    ):
        assert res.status_code == 400


def test_agent_patch_on_an_anonymized_contact_is_409(
    authenticated_client, organization
):
    contact = ContactFactory(organization=organization, name="Gone", is_anonymized=True)
    res = authenticated_client.patch(_detail(contact), {"name": "Alice"}, format="json")
    assert res.status_code == 409
    contact.refresh_from_db()
    assert contact.name == "Gone"


def test_admin_patch_on_an_anonymized_contact_is_409(admin_client, organization):
    contact = ContactFactory(organization=organization, is_anonymized=True)
    res = admin_client.patch(_detail(contact), {"name": "Alice"}, format="json")
    assert res.status_code == 409


def test_anonymized_contact_answers_409_before_validating(
    authenticated_client, organization
):
    ContactFactory(organization=organization, email="dup@x.io")
    contact = ContactFactory(organization=organization, is_anonymized=True)
    res = authenticated_client.patch(
        _detail(contact), {"email": "dup@x.io"}, format="json"
    )
    assert res.status_code == 409


def _stale(monkeypatch, contact):
    """Make the view work from ``contact`` as it was read before later changes."""
    monkeypatch.setattr(ContactViewSet, "get_object", lambda self: contact)


def test_patch_read_before_an_anonymization_cant_undo_it(
    authenticated_client, organization, monkeypatch
):
    contact = ContactFactory(organization=organization, name="Alice", phone="+33")
    _stale(monkeypatch, contact)
    Contact.objects.filter(pk=contact.pk).update(
        name="Anonymized contact", phone="", is_anonymized=True
    )
    res = authenticated_client.patch(
        _detail(contact), {"job_title": "CTO"}, format="json"
    )
    assert res.status_code == 409
    row = Contact.objects.get(pk=contact.pk)
    assert (row.name, row.phone, row.job_title) == ("Anonymized contact", "", "")


def test_patch_writes_only_its_fields_and_merges_on_the_current_row(
    authenticated_client, organization, monkeypatch
):
    ContactAttributeDefFactory(organization=organization, key="plan", type="string")
    ContactAttributeDefFactory(organization=organization, key="role", type="string")
    contact = ContactFactory(organization=organization, phone="+33", attributes={})
    _stale(monkeypatch, contact)
    Contact.objects.filter(pk=contact.pk).update(
        phone="+44", attributes={"plan": "pro"}
    )
    res = authenticated_client.patch(
        _detail(contact), {"attributes": {"role": "cto"}}, format="json"
    )
    assert res.status_code == 200
    row = Contact.objects.get(pk=contact.pk)
    assert row.phone == "+44"
    assert row.attributes == {"plan": "pro", "role": "cto"}


def test_patch_response_keeps_the_ticket_counts(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=organization, contact=contact, status="open")
    res = authenticated_client.patch(_detail(contact), {"name": "A"}, format="json")
    assert (res.data["tickets_count"], res.data["open_tickets_count"]) == (1, 1)


def test_patch_changing_nothing_writes_nothing(authenticated_client, organization):
    contact = ContactFactory(organization=organization, name="Alice")
    before = contact.updated_at
    for body in ({}, {"name": "Alice"}):
        res = authenticated_client.patch(_detail(contact), body, format="json")
        assert res.status_code == 200
    contact.refresh_from_db()
    assert contact.updated_at == before


def test_put_isnt_offered(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    res = authenticated_client.put(_detail(contact), {"name": "A"}, format="json")
    assert res.status_code == 405


# Delete


def test_delete_locks_the_contact_before_touching_its_sessions(
    admin_client, organization
):
    contact = ContactFactory(organization=organization)
    WidgetSession.objects.create(organization=organization, contact=contact)
    with CaptureQueriesContext(connection) as queries:
        assert admin_client.delete(_detail(contact)).status_code == 204
    sql = [query["sql"] for query in queries]
    lock = next(
        i
        for i, q in enumerate(sql)
        if q.startswith("SELECT") and '"contacts_contact"' in q and "FOR UPDATE" in q
    )
    first_write = next(
        i
        for i, q in enumerate(sql)
        if q.startswith(
            ('UPDATE "tickets_widgetsession"', 'DELETE FROM "contacts_contact"')
        )
    )
    assert lock < first_write


def test_delete_requires_admin(authenticated_client, admin_client, organization):
    contact = ContactFactory(organization=organization)
    assert authenticated_client.delete(_detail(contact)).status_code == 403
    assert Contact.objects.filter(pk=contact.pk).exists()
    assert admin_client.delete(_detail(contact)).status_code == 204
    assert not Contact.objects.filter(pk=contact.pk).exists()


def test_delete_keeps_the_tickets(admin_client, organization):
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(organization=organization, contact=contact)
    ContactNoteFactory(contact=contact)
    assert admin_client.delete(_detail(contact)).status_code == 204
    ticket.refresh_from_db()
    assert ticket.contact is None
    assert not ContactNote.objects.exists()


# Other organizations, permissions


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("patch", ""),
        ("delete", ""),
        ("get", "tickets/"),
        ("get", "notes/"),
        ("post", "notes/"),
    ],
)
def test_other_org_contact_is_404(admin_client, method, path):
    other = ContactFactory(organization=OrganizationFactory(), name="Theirs")
    res = getattr(admin_client, method)(
        f"{_detail(other)}{path}", {"name": "Mine", "body": "x"}, format="json"
    )
    assert res.status_code == 404
    other.refresh_from_db()
    assert other.name == "Theirs"
    assert not other.notes.exists()


@pytest.mark.parametrize("pk", ["not-a-uuid", "1", "a%00b"])
def test_malformed_id_is_404(authenticated_client, pk):
    assert authenticated_client.get(f"{URL}{pk}/").status_code == 404


def test_anonymous_request_is_refused(organization):
    contact = ContactFactory(organization=organization)
    client = APIClient()
    assert client.get(URL).status_code == 401
    assert client.get(_detail(contact)).status_code == 401


def test_end_users_are_refused(organization):
    """A customer of the organization must not read its customer directory."""
    contact = ContactFactory(organization=organization)
    client = APIClient()
    client.force_authenticate(EndUserFactory(organization=organization))
    assert client.get(URL).status_code == 403
    assert client.get(_detail(contact)).status_code == 403
    assert client.post(URL, {"email": "a@x.io"}, format="json").status_code == 403
    assert client.get(f"{_detail(contact)}tickets/").status_code == 403


def test_a_user_without_organization_is_refused():
    client = APIClient()
    client.force_authenticate(UserFactory(organization=None, is_superuser=True))
    assert client.get(URL).status_code == 403
    assert client.post(URL, {"email": "a@x.io"}, format="json").status_code == 403


def test_the_organization_header_only_works_for_superusers(
    authenticated_client, organization
):
    other = OrganizationFactory()
    ContactFactory(organization=other)
    mine = ContactFactory(organization=organization)
    res = authenticated_client.get(URL, HTTP_X_SHOWDESK_ORG=str(other.id))
    assert _ids(res) == [str(mine.id)]


def test_a_superuser_impersonates_with_the_header():
    other = OrganizationFactory()
    theirs = ContactFactory(organization=other)
    client = APIClient()
    client.force_authenticate(UserFactory(organization=None, is_superuser=True))
    res = client.get(URL, HTTP_X_SHOWDESK_ORG=str(other.id))
    assert _ids(res) == [str(theirs.id)]
    res = client.post(
        URL, {"email": "a@x.io"}, format="json", HTTP_X_SHOWDESK_ORG=str(other.id)
    )
    assert res.status_code == 201
    assert Contact.objects.get(pk=res.data["id"]).organization == other


@pytest.fixture
def superuser_client(organization) -> APIClient:
    """A superuser whose own organization is ``organization``."""
    client = APIClient()
    client.force_authenticate(UserFactory(organization=organization, is_superuser=True))
    return client


def test_impersonation_refuses_a_company_of_the_superusers_own_org(
    superuser_client, organization
):
    other = OrganizationFactory()
    contact = ContactFactory(organization=other)
    own_company = CompanyFactory(organization=organization)
    res = superuser_client.patch(
        _detail(contact),
        {"company": str(own_company.id)},
        format="json",
        HTTP_X_SHOWDESK_ORG=str(other.id),
    )
    assert res.status_code == 400
    assert "company" in res.data
    contact.refresh_from_db()
    assert contact.company is None


def test_impersonation_accepts_a_company_of_the_impersonated_org(superuser_client):
    other = OrganizationFactory()
    contact = ContactFactory(organization=other)
    company = CompanyFactory(organization=other)
    res = superuser_client.patch(
        _detail(contact),
        {"company": str(company.id)},
        format="json",
        HTTP_X_SHOWDESK_ORG=str(other.id),
    )
    assert res.status_code == 200
    assert res.data["company"] == company.id


def test_impersonation_validates_attributes_on_the_impersonated_org(
    superuser_client, organization
):
    other = OrganizationFactory()
    ContactAttributeDefFactory(organization=other, key="tier")
    ContactAttributeDefFactory(organization=organization, key="mine")
    contact = ContactFactory(organization=other)
    res = superuser_client.patch(
        _detail(contact),
        {"attributes": {"tier": "gold"}},
        format="json",
        HTTP_X_SHOWDESK_ORG=str(other.id),
    )
    assert res.status_code == 200
    assert res.data["attributes"] == {"tier": "gold"}
    res = superuser_client.patch(
        _detail(contact),
        {"attributes": {"mine": "x"}},
        format="json",
        HTTP_X_SHOWDESK_ORG=str(other.id),
    )
    assert res.status_code == 400
    assert "mine" in res.data["attributes"]


@pytest.mark.parametrize(
    "header", ["not-a-uuid", "00000000-0000-4000-8000-000000000000"]
)
@pytest.mark.parametrize(
    "url", [URL, "/api/v1/companies/", "/api/v1/contact-attributes/"]
)
def test_impersonating_an_org_that_doesnt_resolve_is_400(
    superuser_client, organization, header, url
):
    ContactFactory(organization=organization)
    res = superuser_client.get(url, HTTP_X_SHOWDESK_ORG=header)
    assert res.status_code == 400


def test_impersonating_an_org_that_doesnt_resolve_writes_nothing(
    superuser_client, organization
):
    res = superuser_client.post(
        URL, {"email": "a@x.io"}, format="json", HTTP_X_SHOWDESK_ORG="not-a-uuid"
    )
    assert res.status_code == 400
    assert not Contact.objects.filter(organization=organization).exists()


def test_the_organization_header_of_a_non_superuser_is_ignored_even_if_malformed(
    authenticated_client, organization
):
    contact = ContactFactory(organization=organization)
    res = authenticated_client.get(URL, HTTP_X_SHOWDESK_ORG="not-a-uuid")
    assert _ids(res) == [str(contact.id)]


def test_impersonating_superuser_can_delete(superuser_client):
    other = OrganizationFactory()
    contact = ContactFactory(organization=other)
    res = superuser_client.delete(_detail(contact), HTTP_X_SHOWDESK_ORG=str(other.id))
    assert res.status_code == 204
    assert not Contact.objects.filter(pk=contact.pk).exists()


def test_attribute_defined_only_in_another_org_is_refused(
    authenticated_client, organization
):
    ContactAttributeDefFactory(organization=OrganizationFactory(), key="tier")
    contact = ContactFactory(organization=organization)
    res = authenticated_client.patch(
        _detail(contact), {"attributes": {"tier": "gold"}}, format="json"
    )
    assert res.status_code == 400
    assert "tier" in res.data["attributes"]
    res = authenticated_client.post(
        URL, {"email": "n@x.io", "attributes": {"tier": "gold"}}, format="json"
    )
    assert res.status_code == 400
    assert "tier" in res.data["attributes"]


@pytest.mark.parametrize(
    "attributes",
    [
        {"seats": "many"},  # Invalid.
        {"seats": 3, "junk": 1},  # Unknown, next to a valid one.
        {"old": "x"},  # Archived.
        {"role": "a\x00b"},  # Not storable.
        {"a\x00b": 1},  # A key that couldn't be sent back as it is.
        {"\ud800": 1},
    ],
)
def test_attributes_that_cant_be_stored_as_sent_are_400(
    authenticated_client, organization, attributes
):
    ContactAttributeDefFactory(organization=organization, key="seats", type="number")
    ContactAttributeDefFactory(organization=organization, key="role")
    ContactAttributeDefFactory(organization=organization, key="old", is_archived=True)
    contact = ContactFactory(organization=organization, attributes={"seats": 1})
    res = authenticated_client.patch(
        _detail(contact),
        json.dumps({"attributes": attributes}),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "attributes" in res.json()
    contact.refresh_from_db()
    assert contact.attributes == {"seats": 1}
    res = authenticated_client.post(
        URL,
        json.dumps({"email": "n@x.io", "attributes": attributes}),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "attributes" in res.json()
    assert not Contact.objects.filter(email="n@x.io").exists()


def test_invalid_attributes_of_an_anonymized_contact_are_a_409(
    authenticated_client, organization
):
    contact = ContactFactory(organization=organization, is_anonymized=True)
    res = authenticated_client.patch(
        _detail(contact), {"attributes": {"junk": 1}}, format="json"
    )
    assert res.status_code == 409


def test_patch_moves_updated_at(authenticated_client, organization):
    contact = ContactFactory(organization=organization, name="Alice")
    before = contact.updated_at
    res = authenticated_client.patch(_detail(contact), {"name": "Bob"}, format="json")
    assert res.status_code == 200
    contact.refresh_from_db()
    assert contact.updated_at > before


# Tickets and notes


def test_tickets_and_notes(authenticated_client, organization, agent):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=organization, contact=contact)
    ContactNoteFactory(contact=contact, author=agent)
    assert len(authenticated_client.get(f"{_detail(contact)}tickets/").data) == 1
    res = authenticated_client.post(
        f"{_detail(contact)}notes/", {"body": "VIP"}, format="json"
    )
    assert res.status_code == 201
    assert res.data["author_name"]
    assert len(authenticated_client.get(f"{_detail(contact)}notes/").data) == 2


def test_tickets_are_newest_first_with_their_message_count(
    authenticated_client, organization
):
    contact = ContactFactory(organization=organization)
    old = TicketFactory(organization=organization, contact=contact)
    new = TicketFactory(organization=organization, contact=contact)
    TicketMessage.objects.create(ticket=new, body="1")
    TicketMessage.objects.create(ticket=new, body="2")
    Ticket.objects.filter(pk=old.pk).update(
        updated_at=timezone.now() - timedelta(days=1)
    )
    Ticket.objects.filter(pk=new.pk).update(updated_at=timezone.now())
    rows = authenticated_client.get(f"{_detail(contact)}tickets/").data
    assert [row["id"] for row in rows] == [str(new.id), str(old.id)]
    assert [row["message_count"] for row in rows] == [2, 0]


def test_tickets_exclude_those_of_another_org(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=OrganizationFactory(), contact=contact)
    assert authenticated_client.get(f"{_detail(contact)}tickets/").data == []


def test_note_author_comes_from_the_request(authenticated_client, organization, agent):
    contact = ContactFactory(organization=organization)
    someone_else = AdminFactory(organization=organization)
    res = authenticated_client.post(
        f"{_detail(contact)}notes/",
        {
            "body": "VIP",
            "author": str(someone_else.id),
            "contact": str(ContactFactory(organization=organization).id),
        },
        format="json",
    )
    assert res.status_code == 201
    note = ContactNote.objects.get(pk=res.data["id"])
    assert note.author == agent
    assert note.contact == contact
    assert res.data["author_name"] == agent.get_full_name()


@pytest.mark.parametrize("body", [{}, {"body": ""}, {"body": "a\x00b"}, {"body": []}])
def test_invalid_note_is_400(authenticated_client, organization, body):
    contact = ContactFactory(organization=organization)
    res = authenticated_client.post(f"{_detail(contact)}notes/", body, format="json")
    assert res.status_code == 400
    assert not contact.notes.exists()


def test_invalid_note_on_an_anonymized_contact_is_a_409(
    authenticated_client, organization
):
    contact = ContactFactory(organization=organization, is_anonymized=True)
    res = authenticated_client.post(
        f"{_detail(contact)}notes/", {"body": ""}, format="json"
    )
    assert res.status_code == 409


def test_notes_are_newest_first(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    first = ContactNoteFactory(contact=contact)
    second = ContactNoteFactory(contact=contact)
    rows = authenticated_client.get(f"{_detail(contact)}notes/").data
    assert [row["id"] for row in rows] == [str(second.id), str(first.id)]


def test_a_note_cant_be_added_to_an_anonymized_contact(
    authenticated_client, organization
):
    contact = ContactFactory(organization=organization, is_anonymized=True)
    res = authenticated_client.post(
        f"{_detail(contact)}notes/", {"body": "VIP"}, format="json"
    )
    assert res.status_code == 409
    assert not contact.notes.exists()
    assert authenticated_client.get(f"{_detail(contact)}notes/").status_code == 200


# Query counts


def _queries(client, url, **params) -> int:
    with CaptureQueriesContext(connection) as queries:
        assert client.get(url, params).status_code == 200
    return len(queries)


def test_list_has_no_n_plus_one(authenticated_client, organization):
    def add_contacts(count):
        for _ in range(count):
            contact = ContactFactory(
                organization=organization,
                company=CompanyFactory(organization=organization),
            )
            TicketFactory(organization=organization, contact=contact)

    add_contacts(2)
    few = _queries(authenticated_client, URL)
    add_contacts(10)
    assert _queries(authenticated_client, URL) == few
    assert few <= 2


def test_tickets_have_no_n_plus_one(authenticated_client, organization, agent):
    contact = ContactFactory(organization=organization)
    url = f"{_detail(contact)}tickets/"

    def add_tickets(count):
        for _ in range(count):
            ticket = TicketFactory(
                organization=organization,
                contact=contact,
                assigned_agent=UserFactory(organization=organization),
            )
            ticket.tags.add(
                TagFactory(organization=organization),
                TagFactory(organization=organization),
            )
            TicketMessage.objects.create(ticket=ticket, body="Hi")

    add_tickets(2)
    few = _queries(authenticated_client, url)
    add_tickets(10)
    assert _queries(authenticated_client, url) == few
    assert few <= 3


def test_notes_have_no_n_plus_one(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    url = f"{_detail(contact)}notes/"

    def add_notes(count):
        for _ in range(count):
            ContactNoteFactory(
                contact=contact, author=UserFactory(organization=organization)
            )

    add_notes(2)
    few = _queries(authenticated_client, url)
    add_notes(10)
    assert _queries(authenticated_client, url) == few
    assert few <= 2
