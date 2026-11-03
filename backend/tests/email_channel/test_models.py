"""Mailboxes and stored inbound emails."""

import re

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.email_channel.models import Mailbox
from tests.factories import (
    InboundEmailFactory,
    MailboxFactory,
    OrganizationFactory,
    TeamFactory,
)

pytestmark = pytest.mark.django_db


def test_mailbox_local_part_is_generated_from_the_slug_and_is_not_guessable(
    settings,
):
    settings.INBOUND_EMAIL_DOMAIN = "in.example.com"
    org = OrganizationFactory(slug="acme")
    first = Mailbox.objects.create(organization=org, name="Support")
    second = Mailbox.objects.create(organization=org, name="Billing")
    assert re.fullmatch(r"acme-[a-z0-9]{10}", first.local_part)
    assert first.local_part != second.local_part
    assert first.inbound_address == f"{first.local_part}@in.example.com"

    previous = first.local_part
    first.regenerate_address()
    first.refresh_from_db()
    assert first.local_part != previous
    assert first.local_part.startswith("acme-")


def test_mailbox_public_address_is_lowercased_and_unique():
    mailbox = MailboxFactory(public_address="Support@Acme.Example")
    assert mailbox.public_address == "support@acme.example"
    MailboxFactory(public_address="")
    MailboxFactory(public_address="")
    with pytest.raises(IntegrityError), transaction.atomic():
        MailboxFactory(public_address="SUPPORT@acme.example")


def test_mailbox_default_team_must_belong_to_the_organization():
    mailbox = MailboxFactory.build(
        organization=OrganizationFactory(), default_team=TeamFactory()
    )
    with pytest.raises(ValidationError) as error:
        mailbox.clean()
    assert "default_team" in error.value.message_dict


def test_mailbox_public_address_cannot_be_on_the_inbound_domain(settings):
    # It would compete with the inbound addresses of other organizations.
    settings.INBOUND_EMAIL_DOMAIN = "in.example.com"
    mailbox = MailboxFactory.build(
        organization=OrganizationFactory(), public_address="other-abc@IN.example.com"
    )
    with pytest.raises(ValidationError) as error:
        mailbox.clean()
    assert "public_address" in error.value.message_dict


def test_same_message_id_is_unique_per_mailbox_and_without_one():
    mailbox = MailboxFactory()
    InboundEmailFactory(mailbox=mailbox, message_id="<a@x>")
    InboundEmailFactory(mailbox=MailboxFactory(), message_id="<a@x>")
    with pytest.raises(IntegrityError), transaction.atomic():
        InboundEmailFactory(mailbox=mailbox, message_id="<a@x>")
    InboundEmailFactory(mailbox=None, message_id="<a@x>")
    with pytest.raises(IntegrityError), transaction.atomic():
        InboundEmailFactory(mailbox=None, message_id="<a@x>")
