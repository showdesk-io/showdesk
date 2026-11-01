"""The demo seed command must keep working as models evolve."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.contacts.gdpr import anonymize_contact
from apps.contacts.models import (
    Company,
    CompanyAttributeDef,
    Contact,
    ContactAttributeDef,
)
from apps.organizations.models import Organization, OrganizationDomain
from apps.tickets.models import Ticket


def _seed(*args):
    call_command("seed", *args, stdout=StringIO())


@pytest.mark.django_db
def test_seed_creates_demo_data_and_is_rerunnable():
    call_command("seed")
    call_command("seed")  # idempotent: second run must not fail

    org = Organization.objects.get(slug="acme-corp")
    assert OrganizationDomain.objects.filter(
        organization=org,
        domain="acme.example.com",
        status=OrganizationDomain.Status.VERIFIED,
    ).exists()


@pytest.mark.django_db
class TestContacts:
    def test_links_every_ticket_to_the_contact_of_its_requester(self):
        _seed()

        assert Ticket.objects.count() == 7
        for ticket in Ticket.objects.select_related("contact", "requester"):
            assert ticket.contact.email == ticket.requester.email
            assert ticket.contact.organization == ticket.organization
            assert ticket.contact.name == ticket.requester.get_full_name()
            assert ticket.contact.email_verified_at is None
            assert ticket.contact.last_seen_at is not None

    def test_puts_the_contacts_in_a_company_of_the_customer_domain(self):
        _seed()

        org = Organization.objects.get(slug="acme-corp")
        company = Company.objects.get(organization=org, domain="customer.example")
        assert Contact.objects.filter(organization=org).count() == 3
        assert company.contacts.count() == 3

    def test_defines_an_enum_and_a_number_attribute_with_valid_values(self):
        _seed()

        org = Organization.objects.get(slug="acme-corp")
        enum = ContactAttributeDef.objects.get(organization=org, type="enum")
        number = CompanyAttributeDef.objects.get(organization=org, type="number")
        enum.full_clean()
        number.full_clean()
        contacts = Contact.objects.filter(organization=org)
        assert all(contact.attributes[enum.key] in enum.options for contact in contacts)
        company = Company.objects.get(organization=org, domain="customer.example")
        assert isinstance(company.attributes[number.key], int)

    def test_a_second_run_adds_nothing_and_changes_nothing(self):
        _seed()

        def state():
            return (
                sorted(Contact.objects.values_list("pk", "updated_at", "attributes")),
                sorted(Company.objects.values_list("pk", "updated_at", "attributes")),
                ContactAttributeDef.objects.count(),
                CompanyAttributeDef.objects.count(),
                sorted(Ticket.objects.values_list("pk", "contact_id", "updated_at")),
            )

        before = state()
        _seed()
        assert state() == before

    def test_links_the_tickets_of_an_earlier_seed(self):
        _seed()
        Ticket.objects.update(contact=None)
        Contact.objects.all().delete()
        before = dict(Ticket.objects.values_list("pk", "updated_at"))

        _seed()

        assert not Ticket.objects.filter(contact__isnull=True).exists()
        assert dict(Ticket.objects.values_list("pk", "updated_at")) == before

    def test_keeps_what_was_edited_since(self):
        _seed()
        org = Organization.objects.get(slug="acme-corp")
        contact = Contact.objects.get(organization=org, email="jane@customer.example")
        contact.name = "Jane Edited"
        contact.attributes = {}
        contact.save()

        _seed()

        contact.refresh_from_db()
        assert contact.name == "Jane Edited"
        assert contact.attributes == {}

    def test_leaves_an_anonymized_contact_alone(self):
        _seed()
        contact = Contact.objects.get(email="jane@customer.example")
        anonymize_contact(contact)

        _seed()

        contact.refresh_from_db()
        assert contact.is_anonymized
        assert contact.attributes == {}
        assert not Contact.objects.filter(email="jane@customer.example").exists()

    def test_flush_starts_over(self):
        _seed()
        _seed("--flush")

        assert Contact.objects.count() == 3
        assert Company.objects.count() == 1
        assert not Ticket.objects.filter(contact__isnull=True).exists()
