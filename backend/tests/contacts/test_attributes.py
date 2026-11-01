"""Tests for the validation of custom attribute values."""

import pytest
from django.core.exceptions import ValidationError

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
        {"seats": "many"},
        {"seats": True},
        {"seats": "1e999"},
        {"beta": "yes"},
        {"signup": "not a date"},
        {"signup": "2026-13-45"},
        {"site": "javascript:alert(1)"},
        {"role": {"a": 1}},
        {"unknown": "x"},
        {"old": "x"},
    ],
)
def test_invalid_or_unknown_values_are_dropped(defs, traits):
    assert clean_attributes(defs, traits) == {}


@pytest.mark.parametrize(
    "traits",
    [
        {"seats": "many"},
        {"unknown": "x"},
        {"unknown": None},
        {"old": "x"},
        {"role": "a\x00b"},
    ],
)
def test_strict_refuses_what_would_be_dropped(defs, traits):
    with pytest.raises(ValidationError) as exc:
        clean_attributes(defs, {"plan": "pro", **traits}, strict=True)
    assert list(exc.value.message_dict) == list(traits)


def test_strict_keeps_what_is_valid(defs):
    assert clean_attributes(
        defs, {"plan": "pro", "seats": "3", "role": None}, strict=True
    ) == {"plan": "pro", "seats": 3, "role": None}


def test_none_clears_a_value(defs):
    assert clean_attributes(defs, {"plan": None}) == {"plan": None}


def test_invalid_value_does_not_drop_the_valid_ones(defs):
    assert clean_attributes(defs, {"plan": "pro", "seats": "many"}) == {"plan": "pro"}


def test_decimal_number_is_kept_as_a_float(defs):
    assert clean_attributes(defs, {"seats": "1.5"}) == {"seats": 1.5}


def test_long_string_is_truncated(defs):
    assert clean_attributes(defs, {"role": "x" * 2000}) == {"role": "x" * 1000}


@pytest.mark.parametrize("values", [None, ["plan"], 3])
def test_anything_but_a_non_empty_dict_cleans_to_nothing(defs, values):
    assert clean_attributes(defs, values) == {}


@pytest.mark.parametrize(
    "traits",
    [{"seats": 1e308}, {"role": "a\x00b"}, {"role": "\ud800"}],
)
def test_cleaned_values_can_be_stored(defs, traits):
    contact = ContactFactory(
        organization=defs.first().organization,
        attributes=clean_attributes(defs, traits),
    )
    contact.refresh_from_db()


def _deeply_nested(depth: int = 200_000) -> list:
    value: list = []
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize(
    ("key", "value"),
    [("signup", {}), ("site", ["2026-01-15"]), ("plan", {"a": 1})],
)
def test_containers_are_dropped(defs, key, value):
    assert clean_attributes(defs, {key: value}) == {}


@pytest.mark.parametrize("key", ["role", "seats"])
def test_integer_beyond_the_digit_limit_is_dropped(defs, key):
    assert clean_attributes(defs, {key: 10**5000}) == {}


@pytest.mark.parametrize("key", ["role", "plan"])
def test_deeply_nested_value_does_not_overflow_the_stack(defs, key):
    assert clean_attributes(defs, {key: _deeply_nested()}) == {}


def _enum_defs(options):
    org = OrganizationFactory()
    ContactAttributeDef.objects.create(
        organization=org, key="plan", label="plan", type="enum", options=options
    )
    return ContactAttributeDef.objects.filter(organization=org)


@pytest.mark.parametrize(
    ("options", "value"),
    [(3, "pro"), ("free,pro", "e,p"), ({"pro": 1}, "pro")],
)
def test_enum_with_malformed_options_rejects_everything(options, value):
    assert clean_attributes(_enum_defs(options), {"plan": value}) == {}


@pytest.mark.parametrize(
    ("options", "value"),
    [
        ([["pro"]], ["pro"]),
        ([{"a": 1}], {"a": 1}),
        ([1, 2], True),
    ],
)
def test_enum_rejects_odd_values_equal_to_an_option(options, value):
    assert clean_attributes(_enum_defs(options), {"plan": value}) == {}


def test_enum_keeps_a_non_string_option():
    assert clean_attributes(_enum_defs([1, 2]), {"plan": 2}) == {"plan": 2}
