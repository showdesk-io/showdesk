"""Tests for ticket models."""

import pytest

from apps.tickets.models import Ticket, TicketMessage
from tests.factories import (
    TagFactory,
    TicketFactory,
    TicketMessageFactory,
)


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
        msg1 = TicketMessageFactory(ticket=ticket)
        msg2 = TicketMessageFactory(ticket=ticket)
        assert ticket.messages.count() == 2
