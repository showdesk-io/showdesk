"""Tests for the validation of custom attribute values."""

import pytest

from apps.contacts.attributes import clean_attributes
from apps.contacts.models import ContactAttributeDef
from tests.factories import ContactFactory, OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def defs():
    org = OrganizationFactory()
    for key, type_, options in [
        ("plan", "enum", ["free", "pro"]),
        ("seats", "number", []),
        ("beta", "boolean", []),
        ("signup", "date", []),
        ("site", "url", []),
        ("role", "string", []),
    ]:
        ContactAttributeDef.objects.create(
            organization=org, key=key, label=key, type=type_, options=options
        )
    ContactAttributeDef.objects.create(
        organization=org, key="old", label="old", type="string", is_archived=True
    )
    return ContactAttributeDef.objects.filter(organization=org)


def test_valid_values_are_kept_and_coerced(defs):
    cleaned = clean_attributes(
        defs,
        {
            "plan": "pro",
            "seats": "12",
            "beta": True,
            "signup": "2026-01-15T10:00:00Z",
            "site": "https://acme.io",
            "role": 42,
        },
    )
    assert cleaned == {
        "plan": "pro",
        "seats": 12,
        "beta": True,
        "signup": "2026-01-15",
        "site": "https://acme.io",
        "role": "42",
    }


@pytest.mark.parametrize(
    "traits",
    [
        {"plan": "enterprise"},
        {"plan": ["pro"]},
        {"seats": "many"},
        {"seats": True},
        {"seats": []},
        {"seats": "NaN"},
        {"seats": "inf"},
        {"seats": "1e999"},
        {"seats": 10**400},
        {"beta": "yes"},
        {"signup": "not a date"},
        {"signup": "2026-13-45"},
        {"signup": "2026-01-15T25:00:00"},
        {"site": "javascript:alert(1)"},
        {"site": "https://acme.io/\x00"},
        {"role": {"a": 1}},
        {"role": ["a"]},
        {"role": "a\x00b"},
        {"role": "\ud800"},
        {"unknown": "x"},
        {"unknown": None},
        {"old": "x"},
    ],
)
def test_invalid_or_unknown_values_are_dropped(defs, traits):
    assert clean_attributes(defs, traits) == {}


def test_none_clears_a_value(defs):
    assert clean_attributes(defs, {"plan": None}) == {"plan": None}


def test_invalid_value_does_not_drop_the_valid_ones(defs):
    assert clean_attributes(defs, {"plan": "pro", "seats": "many"}) == {"plan": "pro"}


def test_decimal_number_is_kept_as_a_float(defs):
    assert clean_attributes(defs, {"seats": "1.5"}) == {"seats": 1.5}


def test_long_string_is_truncated(defs):
    assert clean_attributes(defs, {"role": "x" * 2000}) == {"role": "x" * 1000}


@pytest.mark.parametrize("values", [None, {}, [], ["plan"], "plan", 3])
def test_anything_but_a_non_empty_dict_cleans_to_nothing(defs, values):
    assert clean_attributes(defs, values) == {}


@pytest.mark.parametrize(
    "traits",
    [
        {"seats": "NaN"},
        {"seats": "1e999"},
        {"seats": 1e308},
        {"role": "a\x00b"},
        {"role": "\ud800"},
        {"site": "https://acme.io/\x00"},
    ],
)
def test_cleaned_values_can_be_stored(defs, traits):
    contact = ContactFactory(
        organization=defs.first().organization,
        attributes=clean_attributes(defs, traits),
    )
    contact.refresh_from_db()
