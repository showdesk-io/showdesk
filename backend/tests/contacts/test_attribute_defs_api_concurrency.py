"""Attribute definitions API against real concurrent transactions."""

import pytest

from apps.contacts.models import ContactAttributeDef
from tests.contacts.test_contacts_api_concurrency import _race
from tests.factories import ContactAttributeDefFactory

pytestmark = pytest.mark.django_db(transaction=True)


def test_create_losing_the_key_race_at_the_constraint_is_400(
    admin_client, organization
):
    res = _race(
        lambda: ContactAttributeDefFactory(organization=organization, key="plan"),
        lambda: admin_client.post(
            "/api/v1/contact-attributes/",
            {"key": "plan", "label": "Plan", "type": "string"},
            format="json",
        ),
    )

    assert res.status_code == 400
    assert "key" in res.data
    assert ContactAttributeDef.objects.filter(organization=organization).count() == 1
