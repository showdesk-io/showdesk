"""Tests for ticket models."""

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.tickets.models import Ticket, TicketMessage, WidgetSession
from tests.factories import (
    ContactFactory,
    MailboxFactory,
    OrganizationFactory,
    TagFactory,
    TicketFactory,
    TicketMessageFactory,
)

BEFORE_CHANNEL_BACKFILL = ("tickets", "0012_email_channel_fields")
CHANNEL_BACKFILL = ("tickets", "0013_backfill_message_channel")


@pytest.mark.django_db
class TestTicket:
    """Tests for the Ticket model."""

    def test_create_ticket(self) -> None:
        """Test basic ticket creation."""
        ticket = TicketFactory(title="Test issue", reference="SD-0001")
        assert ticket.title == "Test issue"
        assert ticket.reference == "SD-0001"
        assert ticket.status == Ticket.Status.OPEN
        assert ticket.priority == Ticket.Priority.MEDIUM

    def test_ticket_str(self) -> None:
        """Test string representation."""
        ticket = TicketFactory(reference="SD-0042", title="Bug in login")
        assert str(ticket) == "SD-0042: Bug in login"

    def test_ticket_with_tags(self) -> None:
        """Test adding tags to a ticket."""
        ticket = TicketFactory()
        tag1 = TagFactory(organization=ticket.organization, name="bug")
        tag2 = TagFactory(organization=ticket.organization, name="urgent")
        ticket.tags.set([tag1, tag2])
        assert ticket.tags.count() == 2

    def test_ticket_status_choices(self) -> None:
        """Test all status values are valid."""
        for status_value, _ in Ticket.Status.choices:
            ticket = TicketFactory(status=status_value)
            assert ticket.status == status_value

    def test_ticket_priority_choices(self) -> None:
        """Test all priority values are valid."""
        for priority_value, _ in Ticket.Priority.choices:
            ticket = TicketFactory(priority=priority_value)
            assert ticket.priority == priority_value

    def test_ticket_context_fields(self) -> None:
        """Test technical context fields are stored."""
        ticket = TicketFactory(
            context_url="https://example.com/page",
            context_browser="Firefox",
            context_os="Linux",
            context_screen_resolution="2560x1440",
            context_metadata={"locale": "en-US"},
        )
        assert ticket.context_url == "https://example.com/page"
        assert ticket.context_metadata == {"locale": "en-US"}

    def test_mailbox_must_belong_to_the_organization(self) -> None:
        ticket = TicketFactory.build(
            organization=OrganizationFactory(), mailbox=MailboxFactory()
        )
        with pytest.raises(ValidationError) as error:
            ticket.clean()
        assert "mailbox" in error.value.message_dict


@pytest.mark.django_db
class TestTicketMessage:
    """Tests for the TicketMessage model."""

    def test_create_reply(self) -> None:
        """Test creating a public reply."""
        message = TicketMessageFactory(
            body="Thanks for reporting!",
            message_type=TicketMessage.MessageType.REPLY,
        )
        assert message.message_type == "reply"
        assert message.body == "Thanks for reporting!"

    def test_create_internal_note(self) -> None:
        """Test creating an internal note."""
        message = TicketMessageFactory(
            body="This looks like a DB issue.",
            message_type=TicketMessage.MessageType.INTERNAL_NOTE,
        )
        assert message.message_type == "internal_note"

    def test_message_belongs_to_ticket(self) -> None:
        """Test the ticket-message relationship."""
        ticket = TicketFactory()
        TicketMessageFactory(ticket=ticket)
        TicketMessageFactory(ticket=ticket)
        assert ticket.messages.count() == 2

    def test_sender_name_of_an_email_message_is_its_external_sender(self) -> None:
        contact = ContactFactory(name="Ann Example")
        ticket = TicketFactory(organization=contact.organization, contact=contact)

        def user_message(**fields) -> TicketMessage:
            return TicketMessageFactory(
                ticket=ticket,
                author=None,
                sender_type=TicketMessage.SenderType.USER,
                **fields,
            )

        third_party = user_message(
            channel=TicketMessage.Channel.EMAIL,
            external_sender='"Bob Other" <bob@example.org>',
        )
        unnamed = user_message(
            channel=TicketMessage.Channel.EMAIL, external_sender="bob@example.org"
        )
        session = WidgetSession.objects.create(
            organization=ticket.organization, name="Widget Ann"
        )
        assert third_party.sender_name == "Bob Other"
        assert unnamed.sender_name == "bob@example.org"
        assert user_message(widget_session=session).sender_name == "Widget Ann"
        assert user_message().sender_name == "Ann Example"


@pytest.mark.django_db(transaction=True)
def test_backfill_sets_the_channel_from_the_sender_type() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CHANNEL_BACKFILL])
    try:
        # The models of that time: today's may have columns the tables don't have.
        historical = executor.loader.project_state(BEFORE_CHANNEL_BACKFILL).apps
        ticket = historical.get_model("tickets", "Ticket").objects.create(
            organization_id=OrganizationFactory().pk, reference="SD-0001", title="Old"
        )
        user, agent, system = (
            historical.get_model("tickets", "TicketMessage").objects.create(
                ticket_id=ticket.pk, sender_type=sender_type
            )
            for sender_type in ("user", "agent", "system")
        )
        executor = MigrationExecutor(connection)
        executor.migrate([CHANNEL_BACKFILL])
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
    channels = dict(
        TicketMessage.objects.filter(ticket_id=ticket.pk).values_list("pk", "channel")
    )
    assert channels == {user.pk: "widget", agent.pk: "agent", system.pk: "system"}
