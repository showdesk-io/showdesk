"""Tests for Contact and Company models."""

import pytest
from django.db import IntegrityError

from tests.factories import CompanyFactory, ContactFactory, OrganizationFactory

pytestmark = pytest.mark.django_db


def test_contact_email_unique_per_org():
    contact = ContactFactory(email="alice@startup.com")
    with pytest.raises(IntegrityError):
        ContactFactory(organization=contact.organization, email="alice@startup.com")


def test_contact_same_email_allowed_in_other_org():
    ContactFactory(email="alice@startup.com")
    ContactFactory(organization=OrganizationFactory(), email="alice@startup.com")


def test_contact_blank_email_not_unique():
    org = OrganizationFactory()
    ContactFactory(organization=org, email="")
    ContactFactory(organization=org, email="")


def test_contact_external_id_unique_per_org():
    contact = ContactFactory(external_id="user_1")
    with pytest.raises(IntegrityError):
        ContactFactory(organization=contact.organization, external_id="user_1")


def test_contact_email_is_lowercased_on_save():
    assert ContactFactory(email="Alice@Startup.COM").email == "alice@startup.com"


def test_contact_display_name_falls_back_to_email():
    assert ContactFactory(name="", email="bob@x.io").display_name == "bob@x.io"
    assert ContactFactory(name="Bob", email="bob2@x.io").display_name == "Bob"


def test_company_domain_unique_per_org_and_lowercased():
    company = CompanyFactory(domain="Startup.com")
    assert company.domain == "startup.com"
    with pytest.raises(IntegrityError):
        CompanyFactory(organization=company.organization, domain="startup.com")
