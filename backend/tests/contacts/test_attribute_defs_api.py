"""Custom attribute definitions API."""

import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.contacts.models import (
    CompanyAttributeDef,
    Contact,
    ContactAttributeDef,
    CustomAttributeDef,
)
from tests.factories import (
    CompanyAttributeDefFactory,
    ContactAttributeDefFactory,
    ContactFactory,
    EndUserFactory,
    OrganizationFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/contact-attributes/"
COMPANY_URL = "/api/v1/company-attributes/"
LIMIT = CustomAttributeDef.MAX_PER_ORGANIZATION


def _detail(definition) -> str:
    return f"{URL}{definition.id}/"


def _body(**overrides) -> dict:
    return {"key": "plan", "label": "Plan", "type": "string", **overrides}


def _post_json(client, body):
    return client.post(URL, json.dumps(body), content_type="application/json")


def _patch_json(client, definition, body):
    return client.patch(
        _detail(definition), json.dumps(body), content_type="application/json"
    )


# Reading


def test_agents_list_the_definitions_of_their_org_unpaginated(
    authenticated_client, organization
):
    mine = ContactAttributeDefFactory(organization=organization)
    ContactAttributeDefFactory(organization=OrganizationFactory())
    res = authenticated_client.get(URL)
    assert res.status_code == 200
    assert [row["id"] for row in res.data] == [str(mine.id)]
    assert authenticated_client.get(_detail(mine)).status_code == 200


def test_list_is_ordered_by_position_then_label(authenticated_client, organization):
    second = ContactAttributeDefFactory(
        organization=organization, position=1, label="A"
    )
    third = ContactAttributeDefFactory(organization=organization, position=1, label="B")
    first = ContactAttributeDefFactory(organization=organization, position=0, label="Z")
    res = authenticated_client.get(URL)
    assert [row["id"] for row in res.data] == [
        str(first.id),
        str(second.id),
        str(third.id),
    ]


def test_list_includes_the_archived_ones(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, is_archived=True)
    assert authenticated_client.get(URL).data[0]["is_archived"] is True


def test_query_params_dont_filter_the_list(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization)
    for params in ({"search": "nope"}, {"ordering": "organization__api_token"}):
        assert len(authenticated_client.get(URL, params).data) == 1


def test_list_has_no_n_plus_one(authenticated_client, organization):
    ContactAttributeDefFactory.create_batch(5, organization=organization)
    with CaptureQueriesContext(connection) as queries:
        authenticated_client.get(URL)
    assert len(queries) == 1


def test_company_attributes_are_a_separate_list(admin_client, organization):
    ContactAttributeDefFactory(organization=organization, key="plan")
    res = admin_client.post(COMPANY_URL, _body(), format="json")
    assert res.status_code == 201
    definition = CompanyAttributeDef.objects.get(pk=res.data["id"])
    assert definition.organization == organization
    assert [row["id"] for row in admin_client.get(COMPANY_URL).data] == [res.data["id"]]
    res = admin_client.patch(
        f"{COMPANY_URL}{definition.id}/", {"label": "Tier"}, format="json"
    )
    assert res.data["label"] == "Tier"
    assert admin_client.delete(f"{COMPANY_URL}{definition.id}/").status_code == 405


# Permissions


def test_agents_cant_write(authenticated_client, organization):
    definition = ContactAttributeDefFactory(organization=organization, label="Old")
    assert authenticated_client.post(URL, _body(), format="json").status_code == 403
    res = authenticated_client.patch(_detail(definition), {"label": "New"})
    assert res.status_code == 403
    definition.refresh_from_db()
    assert definition.label == "Old"
    assert authenticated_client.post(COMPANY_URL, _body()).status_code == 403


def test_agents_get_a_403_even_with_an_invalid_body(authenticated_client, organization):
    """Their answer doesn't tell them which keys already exist."""
    definition = ContactAttributeDefFactory(organization=organization, key="taken")
    res = authenticated_client.post(URL, _body(key="taken"), format="json")
    assert res.status_code == 403
    res = authenticated_client.patch(_detail(definition), {"key": "x"}, format="json")
    assert res.status_code == 403


def test_end_users_are_refused(organization):
    client = APIClient()
    client.force_authenticate(EndUserFactory(organization=organization))
    assert client.get(URL).status_code == 403
    assert client.post(URL, _body(), format="json").status_code == 403


def test_anonymous_request_is_refused():
    assert APIClient().get(URL).status_code == 401


def test_a_user_without_organization_is_refused():
    client = APIClient()
    client.force_authenticate(UserFactory(organization=None, is_superuser=True))
    assert client.get(URL).status_code == 403
    assert client.post(URL, _body(), format="json").status_code == 403


def test_other_org_definition_is_404(admin_client):
    other = ContactAttributeDefFactory(organization=OrganizationFactory(), label="Old")
    assert admin_client.get(_detail(other)).status_code == 404
    res = admin_client.patch(_detail(other), {"label": "New"}, format="json")
    assert res.status_code == 404
    other.refresh_from_db()
    assert other.label == "Old"


def test_delete_is_not_offered(admin_client, organization):
    definition = ContactAttributeDefFactory(organization=organization)
    assert admin_client.delete(_detail(definition)).status_code == 405
    assert ContactAttributeDef.objects.filter(pk=definition.pk).exists()


def test_put_is_not_offered(admin_client, organization):
    definition = ContactAttributeDefFactory(organization=organization)
    res = admin_client.put(_detail(definition), _body(), format="json")
    assert res.status_code == 405


# Creating


def test_admin_creates_a_definition(admin_client, organization):
    res = admin_client.post(
        URL,
        _body(description="d", position=3, organization=str(OrganizationFactory().id)),
        format="json",
    )
    assert res.status_code == 201
    definition = ContactAttributeDef.objects.get(pk=res.data["id"])
    assert definition.organization == organization
    assert definition.options == []
    assert (definition.description, definition.position) == ("d", 3)
    assert "is_required" not in res.data


@pytest.mark.parametrize("key", ["a", "plan", "plan_2", "a_b_c", "a_", "a" * 64, "z9"])
def test_valid_keys(admin_client, key):
    res = admin_client.post(URL, _body(key=key), format="json")
    assert res.status_code == 201
    assert res.data["key"] == key


@pytest.mark.parametrize(
    "key",
    [
        "",
        " ",
        "Plan",
        "PLAN",
        "1plan",
        "_plan",
        "my-plan",
        "my plan",
        "my.plan",
        "é",
        "a__b",
        "a___b",
        "plan__contains",
        "plan\n",
        " plan",
        "plan ",
        "a\x00",
        "a" * 65,
        None,
        [],
        {},
        True,
    ],
)
def test_invalid_keys_are_400(admin_client, organization, key):
    res = _post_json(admin_client, _body(key=key))
    assert res.status_code == 400
    assert "key" in res.data
    assert not ContactAttributeDef.objects.filter(organization=organization).exists()


def test_a_created_key_can_be_filtered_on(admin_client, organization):
    res = admin_client.post(URL, _body(key="a_plan_2"), format="json")
    assert res.status_code == 201
    contact = ContactFactory(organization=organization, attributes={"a_plan_2": "pro"})
    ContactFactory(organization=organization, attributes={"a_plan_2": "free"})
    rows = admin_client.get("/api/v1/contacts/", {"attr.a_plan_2": "pro"}).data
    assert [row["id"] for row in rows["results"]] == [str(contact.id)]


@pytest.mark.parametrize(
    "body",
    [
        {"key": None},
        {"label": ""},
        {"label": "x" * 121},
        {"label": "a\x00b"},
        {"type": "nope"},
        {"type": None},
        {"type": []},
        {"position": -1},
        {"position": "first"},
        {"is_archived": "maybe"},
    ],
)
def test_invalid_fields_are_400(admin_client, body):
    assert _post_json(admin_client, _body(**body)).status_code == 400


@pytest.mark.parametrize("field", ["key", "label", "type"])
def test_required_fields(admin_client, field):
    body = _body()
    del body[field]
    res = admin_client.post(URL, body, format="json")
    assert res.status_code == 400
    assert field in res.data


def test_duplicate_key_is_400(admin_client, organization):
    ContactAttributeDefFactory(organization=organization, key="plan")
    res = admin_client.post(URL, _body(), format="json")
    assert res.status_code == 400
    assert "key" in res.data


def test_an_archived_definition_keeps_its_key(admin_client, organization):
    """Its values are still stored: a new definition would take them over."""
    ContactAttributeDefFactory(organization=organization, key="plan", is_archived=True)
    res = admin_client.post(URL, _body(), format="json")
    assert res.status_code == 400
    assert "key" in res.data


def test_same_key_in_another_org_or_entity_is_allowed(admin_client, organization):
    ContactAttributeDefFactory(organization=OrganizationFactory(), key="plan")
    CompanyAttributeDefFactory(organization=organization, key="plan")
    assert admin_client.post(URL, _body(), format="json").status_code == 201


# Options


def test_enum_with_options(admin_client):
    res = admin_client.post(
        URL, _body(type="enum", options=["free", "pro"]), format="json"
    )
    assert res.status_code == 201
    assert res.data["options"] == ["free", "pro"]


@pytest.mark.parametrize(
    "options",
    [
        [],
        "free",
        {"a": 1},
        1,
        0,
        True,
        None,
        ["a", "a"],
        ["a", ""],
        ["a", "  "],
        ["a", 1],
        ["a", None],
        ["a", ["b"]],
        [{"a": 1}],
        ["a\x00b"],
        ["\ud800"],
    ],
)
def test_invalid_enum_options_are_400(admin_client, organization, options):
    res = _post_json(admin_client, _body(type="enum", options=options))
    assert res.status_code == 400
    assert "options" in res.data
    assert not ContactAttributeDef.objects.filter(organization=organization).exists()
    definition = ContactAttributeDefFactory(
        organization=organization, type="enum", options=["kept"]
    )
    assert (
        _patch_json(admin_client, definition, {"options": options}).status_code == 400
    )
    definition.refresh_from_db()
    assert definition.options == ["kept"]


def test_enum_needs_options(admin_client):
    res = admin_client.post(URL, _body(type="enum"), format="json")
    assert res.status_code == 400
    assert "options" in res.data


@pytest.mark.parametrize("type_", ["string", "number", "boolean", "date", "url"])
@pytest.mark.parametrize("options", [["a"], "a", {"a": 1}, {}, 1, 0, ""])
def test_options_are_refused_on_other_types(admin_client, type_, options):
    res = _post_json(admin_client, _body(type=type_, options=options))
    assert res.status_code == 400
    assert "options" in res.data


def test_no_options_on_other_types_is_fine(admin_client, organization):
    res = admin_client.post(URL, _body(options=[]), format="json")
    assert res.status_code == 201
    definition = ContactAttributeDef.objects.get(pk=res.data["id"])
    res = admin_client.patch(_detail(definition), {"options": []}, format="json")
    assert res.status_code == 200
    res = admin_client.patch(_detail(definition), {"options": ["a"]}, format="json")
    assert res.status_code == 400


def test_removing_an_option_leaves_stored_values_alone(admin_client, organization):
    definition = ContactAttributeDefFactory(
        organization=organization, key="plan", type="enum", options=["free", "pro"]
    )
    contact = ContactFactory(organization=organization, attributes={"plan": "pro"})
    res = admin_client.patch(_detail(definition), {"options": ["free"]}, format="json")
    assert res.status_code == 200
    assert res.data["options"] == ["free"]
    assert Contact.objects.get(pk=contact.pk).attributes == {"plan": "pro"}
    # A new write of the removed value is dropped, like any other invalid one.
    res = admin_client.patch(
        f"/api/v1/contacts/{contact.id}/",
        {"attributes": {"plan": "pro", "other": 1}},
        format="json",
    )
    assert res.data["attributes"] == {"plan": "pro"}


def test_patch_without_options_doesnt_check_the_stored_ones(admin_client, organization):
    """Stored before this validation: they mustn't stop the definition being archived."""
    definition = ContactAttributeDefFactory(
        organization=organization, type="enum", options="legacy"
    )
    res = admin_client.patch(_detail(definition), {"is_archived": True}, format="json")
    assert res.status_code == 200


# Patching


@pytest.mark.parametrize("key", ["other", "PLAN", "not valid"])
def test_key_is_immutable(admin_client, organization, key):
    definition = ContactAttributeDefFactory(organization=organization, key="plan")
    res = admin_client.patch(_detail(definition), {"key": key}, format="json")
    assert res.status_code == 400
    assert "key" in res.data
    definition.refresh_from_db()
    assert definition.key == "plan"


def test_type_is_immutable(admin_client, organization):
    definition = ContactAttributeDefFactory(organization=organization, type="string")
    res = admin_client.patch(_detail(definition), {"type": "number"}, format="json")
    assert res.status_code == 400
    assert "type" in res.data
    definition.refresh_from_db()
    assert definition.type == "string"


def test_a_definition_can_be_sent_back_unchanged(admin_client, organization):
    """A form sends every field: the same key and type are no change."""
    definition = ContactAttributeDefFactory(organization=organization)
    before = definition.updated_at
    res = admin_client.patch(
        _detail(definition),
        {"key": definition.key, "type": definition.type, "label": definition.label},
        format="json",
    )
    assert res.status_code == 200
    definition.refresh_from_db()
    assert definition.updated_at == before


def test_patch_writes_only_what_changed(admin_client, organization):
    definition = ContactAttributeDefFactory(organization=organization, label="Old")
    with CaptureQueriesContext(connection) as queries:
        res = admin_client.patch(_detail(definition), {"label": "New"}, format="json")
    assert res.status_code == 200
    update = next(
        query["sql"]
        for query in queries
        if query["sql"].startswith('UPDATE "contacts_contactattributedef"')
    )
    assert '"label"' in update
    assert '"options"' not in update


def test_archive_and_restore(admin_client, organization):
    definition = ContactAttributeDefFactory(organization=organization)
    res = admin_client.patch(_detail(definition), {"is_archived": True}, format="json")
    assert res.data["is_archived"] is True
    res = admin_client.patch(_detail(definition), {"is_archived": False}, format="json")
    assert res.data["is_archived"] is False


# Limit


def _fill(organization, count=LIMIT, **kwargs):
    ContactAttributeDefFactory.create_batch(count, organization=organization, **kwargs)


def test_creation_beyond_the_limit_is_400(admin_client, organization):
    _fill(organization, LIMIT - 1)
    assert admin_client.post(URL, _body(key="last"), format="json").status_code == 201
    res = admin_client.post(URL, _body(key="extra"), format="json")
    assert res.status_code == 400
    assert not ContactAttributeDef.objects.filter(key="extra").exists()


def test_the_limit_doesnt_count_archived_ones_or_others(admin_client, organization):
    _fill(organization, LIMIT - 1)
    _fill(organization, 2, is_archived=True)
    ContactAttributeDefFactory.create_batch(2, organization=OrganizationFactory())
    CompanyAttributeDefFactory.create_batch(2, organization=organization)
    assert admin_client.post(URL, _body(), format="json").status_code == 201


def test_an_archived_definition_can_be_created_at_the_limit(admin_client, organization):
    _fill(organization)
    res = admin_client.post(URL, _body(is_archived=True), format="json")
    assert res.status_code == 201


def test_unarchiving_counts_against_the_limit(admin_client, organization):
    _fill(organization)
    archived = ContactAttributeDefFactory(organization=organization, is_archived=True)
    res = admin_client.patch(_detail(archived), {"is_archived": False}, format="json")
    assert res.status_code == 400
    archived.refresh_from_db()
    assert archived.is_archived is True
    ContactAttributeDef.objects.filter(
        organization=organization, is_archived=False
    ).first().delete()
    res = admin_client.patch(_detail(archived), {"is_archived": False}, format="json")
    assert res.status_code == 200


def test_editing_an_active_definition_at_the_limit_is_fine(admin_client, organization):
    _fill(organization)
    definition = ContactAttributeDef.objects.filter(organization=organization).first()
    res = admin_client.patch(
        _detail(definition), {"label": "New", "is_archived": False}, format="json"
    )
    assert res.status_code == 200
