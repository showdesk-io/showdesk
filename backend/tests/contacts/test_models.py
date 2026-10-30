"""Tests for the contacts app models."""

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.forms import modelform_factory
from django.utils import timezone

from apps.contacts.models import (
    Company,
    CompanyAttributeDef,
    Contact,
    ContactAttributeDef,
)
from apps.tickets.models import Ticket, WidgetSession
from tests.factories import (
    CompanyFactory,
    ContactAttributeDefFactory,
    ContactFactory,
    ContactNoteFactory,
    OrganizationFactory,
    TicketFactory,
)

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


def test_contact_email_is_normalized_on_save():
    contact = ContactFactory(email="  Alice@Startup.COM ")
    contact.refresh_from_db()
    assert contact.email == "alice@startup.com"


def test_contact_declared_email_is_normalized_on_save_and_clean():
    contact = ContactFactory(declared_email="  Alice@Startup.COM ")
    contact.refresh_from_db()
    assert contact.declared_email == "alice@startup.com"
    unsaved = Contact(declared_email=" Bob@X.io ")
    unsaved.clean()
    assert unsaved.declared_email == "bob@x.io"


def test_contact_declared_email_is_not_unique():
    first = ContactFactory(declared_email="same@x.io", email="")
    ContactFactory(
        organization=first.organization, declared_email="same@x.io", email=""
    )


def test_contact_display_name_falls_back_to_email():
    assert ContactFactory(name="", email="bob@x.io").display_name == "bob@x.io"
    assert ContactFactory(name="Bob", email="bob2@x.io").display_name == "Bob"


def test_contact_display_name_falls_back_to_external_id():
    contact = ContactFactory(name="", email="", external_id="user_1")
    assert contact.display_name == "user_1"


def test_contact_display_name_falls_back_to_anonymous():
    contact = ContactFactory(name="", email="", external_id="")
    assert contact.display_name == "Anonymous contact"


def test_contact_ordering_puts_never_seen_last():
    org = OrganizationFactory()
    seen = ContactFactory(organization=org, last_seen_at=timezone.now())
    never_seen = ContactFactory(organization=org, last_seen_at=None)
    assert list(Contact.objects.filter(organization=org)) == [seen, never_seen]


def test_contact_clean_normalizes_email():
    contact = Contact(email="  Alice@X.IO ")
    contact.clean()
    assert contact.email == "alice@x.io"


def test_contact_full_clean_rejects_case_variant_email():
    existing = ContactFactory(email="alice@x.io")
    contact = Contact(organization=existing.organization, email="Alice@X.io")
    with pytest.raises(ValidationError):
        contact.full_clean()


def test_contact_model_form_rejects_case_variant_email():
    existing = ContactFactory(email="alice@x.io")
    form_class = modelform_factory(Contact, fields=["organization", "email"])
    form = form_class(
        data={"organization": existing.organization.pk, "email": "Alice@X.io"}
    )
    assert not form.is_valid()
    assert Contact.objects.filter(organization=existing.organization).count() == 1


def test_contact_clean_rejects_company_from_other_org():
    org = OrganizationFactory()
    foreign_company = CompanyFactory(organization=OrganizationFactory())
    contact = Contact(organization=org, company=foreign_company)
    with pytest.raises(ValidationError) as exc_info:
        contact.clean()
    assert "company" in exc_info.value.message_dict


def test_contact_clean_accepts_company_from_same_org():
    company = CompanyFactory()
    Contact(organization=company.organization, company=company).clean()


def test_company_domain_is_normalized_on_save():
    company = CompanyFactory(domain="  Startup.COM ")
    company.refresh_from_db()
    assert company.domain == "startup.com"


def test_company_domain_unique_per_org():
    company = CompanyFactory(domain="startup.com")
    with pytest.raises(IntegrityError):
        CompanyFactory(organization=company.organization, domain="startup.com")


def test_company_domain_duplicate_differing_only_by_case():
    company = CompanyFactory(domain="startup.com")
    with pytest.raises(IntegrityError):
        CompanyFactory(organization=company.organization, domain="STARTUP.com")


def test_company_same_domain_allowed_in_other_org():
    CompanyFactory(domain="startup.com")
    CompanyFactory(organization=OrganizationFactory(), domain="startup.com")


def test_company_blank_domain_not_unique():
    org = OrganizationFactory()
    CompanyFactory(organization=org, domain="")
    CompanyFactory(organization=org, domain="")


def test_company_external_id_unique_per_org():
    company = CompanyFactory(external_id="acct_1")
    with pytest.raises(IntegrityError):
        CompanyFactory(organization=company.organization, external_id="acct_1")


def test_company_blank_external_id_not_unique():
    org = OrganizationFactory()
    CompanyFactory(organization=org, external_id="")
    CompanyFactory(organization=org, external_id="")


def test_company_clean_normalizes_domain():
    company = Company(domain="  X.IO ")
    company.clean()
    assert company.domain == "x.io"


def test_company_full_clean_rejects_case_variant_domain():
    existing = CompanyFactory(domain="x.io")
    company = Company(
        organization=existing.organization, name="Duplicate", domain="X.io"
    )
    with pytest.raises(ValidationError):
        company.full_clean()


def test_company_model_form_rejects_case_variant_domain():
    existing = CompanyFactory(domain="x.io")
    form_class = modelform_factory(Company, fields=["organization", "name", "domain"])
    form = form_class(
        data={
            "organization": existing.organization.pk,
            "name": "Duplicate",
            "domain": "X.io",
        }
    )
    assert not form.is_valid()
    assert Company.objects.filter(organization=existing.organization).count() == 1


def test_company_ordering_breaks_name_ties_by_id():
    org = OrganizationFactory()
    companies = [CompanyFactory(organization=org, name="Same") for _ in range(5)]
    ordered_ids = sorted(company.pk for company in companies)
    assert [
        company.pk for company in Company.objects.filter(organization=org)
    ] == ordered_ids


def test_attribute_key_unique_per_org():
    attr = ContactAttributeDefFactory(key="plan")
    with pytest.raises(IntegrityError):
        ContactAttributeDefFactory(organization=attr.organization, key="plan")


def test_attribute_same_key_allowed_in_other_org():
    ContactAttributeDefFactory(key="plan")
    ContactAttributeDefFactory(organization=OrganizationFactory(), key="plan")


def test_company_attribute_key_unique_per_org():
    org = OrganizationFactory()
    CompanyAttributeDef.objects.create(
        organization=org, key="plan", label="Plan", type="string"
    )
    with pytest.raises(IntegrityError):
        CompanyAttributeDef.objects.create(
            organization=org, key="plan", label="Other", type="string"
        )


def test_contact_and_company_attribute_keys_are_independent():
    attr = ContactAttributeDefFactory(key="plan")
    CompanyAttributeDef.objects.create(
        organization=attr.organization, key="plan", label="Plan", type="string"
    )


def test_attribute_limit_constant():
    assert ContactAttributeDef.MAX_PER_ORGANIZATION == 50
    assert CompanyAttributeDef.MAX_PER_ORGANIZATION == 50


def test_attribute_ordering_by_position_then_label_then_id():
    org = OrganizationFactory()
    second = ContactAttributeDefFactory(organization=org, position=1, label="A")
    first = ContactAttributeDefFactory(organization=org, position=0, label="Z")
    # Ids are random UUIDs: pin them so that id order contradicts label order.
    label_a = ContactAttributeDefFactory(
        organization=org, position=2, label="A", id=uuid.UUID(int=2)
    )
    label_b = ContactAttributeDefFactory(
        organization=org, position=2, label="B", id=uuid.UUID(int=1)
    )
    ties = [
        ContactAttributeDefFactory(organization=org, position=3, label="Same")
        for _ in range(5)
    ]
    expected = [
        first.pk,
        second.pk,
        label_a.pk,
        label_b.pk,
        *sorted(attr.pk for attr in ties),
    ]
    assert [
        attr.pk for attr in ContactAttributeDef.objects.filter(organization=org)
    ] == expected


def test_contact_note_str():
    note = ContactNoteFactory(body="Called them")
    assert note.contact.display_name in str(note)


def test_contact_note_survives_author_deletion():
    note = ContactNoteFactory()
    note.author.delete()
    note.refresh_from_db()
    assert note.author is None


def test_contact_note_without_author_passes_validation():
    note = ContactNoteFactory()
    note.author.delete()
    note.refresh_from_db()
    note.full_clean()


def test_ticket_contact_set_null_on_contact_delete():
    contact = ContactFactory()
    ticket = TicketFactory(organization=contact.organization, contact=contact)
    contact.delete()
    ticket.refresh_from_db()
    assert ticket.contact is None


def test_widget_session_contact_set_null_on_contact_delete():
    contact = ContactFactory()
    session = WidgetSession.objects.create(
        organization=contact.organization, contact=contact
    )
    contact.delete()
    session.refresh_from_db()
    assert session.contact is None


def test_contact_reverse_relations_to_tickets_and_sessions():
    contact = ContactFactory()
    ticket = TicketFactory(organization=contact.organization, contact=contact)
    session = WidgetSession.objects.create(
        organization=contact.organization, contact=contact
    )
    assert list(contact.tickets.all()) == [ticket]
    assert list(contact.sessions.all()) == [session]


def test_widget_session_email_verified_at_defaults_to_none():
    session = WidgetSession.objects.create(organization=OrganizationFactory())
    session.refresh_from_db()
    assert session.email_verified_at is None


def test_ticket_contact_from_another_org_is_rejected():
    ticket = TicketFactory(contact=ContactFactory())
    with pytest.raises(ValidationError) as excinfo:
        ticket.full_clean()
    assert list(excinfo.value.message_dict) == ["contact"]


def test_ticket_contact_from_same_org_is_accepted():
    contact = ContactFactory()
    ticket = TicketFactory(organization=contact.organization, contact=contact)
    ticket.full_clean()


def test_ticket_without_contact_is_accepted():
    TicketFactory().full_clean()


def test_ticket_form_reports_foreign_contact_on_the_field():
    form_class = modelform_factory(Ticket, fields=["organization", "contact"])
    ticket = TicketFactory()
    form = form_class(
        {"organization": ticket.organization_id, "contact": ContactFactory().pk},
        instance=ticket,
    )
    assert not form.is_valid()
    assert list(form.errors) == ["contact"]
