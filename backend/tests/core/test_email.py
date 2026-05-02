"""Tests for the branded email helper and ticket-related email tasks.

Verifies that every transactional email ships an HTML alternative alongside
the plain-text body and that the key context (reference, code, links) ends
up in both renderings.
"""

import pytest
from django.core import mail

from apps.core.email import send_branded_email
from apps.tickets.tasks import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_reply_email,
    send_ticket_resolved_email,
)
from tests.factories import (
    OrganizationFactory,
    TicketAttachmentFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)


pytestmark = pytest.mark.django_db


def _alt(message):
    """Return the HTML alternative payload of an EmailMultiAlternatives."""
    assert message.alternatives, "missing HTML alternative"
    body, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    return body


def test_send_branded_email_attaches_html_alternative():
    send_branded_email(
        template="otp_code",
        subject="Showdesk login code",
        to=["user@example.com"],
        context={
            "kicker": "Sign in",
            "heading": "Your code",
            "intro": "Use it to log in.",
            "code": "123456",
            "expiry_minutes": 10,
        },
    )
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.subject == "Showdesk login code"
    assert msg.to == ["user@example.com"]
    # Plain text body
    assert "123456" in msg.body
    assert "<html" not in msg.body
    # HTML alternative
    html = _alt(msg)
    assert html.startswith("<!DOCTYPE html>")
    assert "123456" in html


def test_send_branded_email_skips_when_no_recipients():
    send_branded_email(
        template="otp_code",
        subject="No-op",
        to=[None, ""],
        context={
            "kicker": "x",
            "heading": "x",
            "intro": "x",
            "code": "0",
            "expiry_minutes": 1,
        },
    )
    assert mail.outbox == []


def test_ticket_created_email_renders_for_assigned_agent():
    org = OrganizationFactory()
    agent = UserFactory(organization=org, role="agent", email="agent@example.com")
    ticket = TicketFactory(organization=org, assigned_agent=agent)

    send_ticket_created_email(ticket.id)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["agent@example.com"]
    assert ticket.reference in msg.subject
    assert ticket.reference in msg.body
    html = _alt(msg)
    assert ticket.reference in html
    assert ticket.title in html


def test_ticket_reply_email_to_requester_when_agent_replies():
    org = OrganizationFactory()
    agent = UserFactory(organization=org, role="agent", first_name="Alice")
    ticket = TicketFactory(
        organization=org,
        assigned_agent=agent,
        requester_email="end@example.com",
    )
    message = TicketMessageFactory(
        ticket=ticket, author=agent, body="Have you tried X?"
    )

    send_ticket_reply_email(message.id)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["end@example.com"]
    assert "Have you tried X?" in msg.body
    html = _alt(msg)
    assert "Have you tried X?" in html
    assert "Alice" in html


def test_ticket_reply_email_skips_internal_notes():
    org = OrganizationFactory()
    agent = UserFactory(organization=org, role="agent")
    ticket = TicketFactory(organization=org, assigned_agent=agent)
    note = TicketMessageFactory(
        ticket=ticket,
        author=agent,
        body="not for the customer",
        message_type="internal_note",
    )

    send_ticket_reply_email(note.id)

    assert mail.outbox == []


def test_ticket_assigned_email_goes_to_assignee():
    org = OrganizationFactory()
    agent = UserFactory(organization=org, role="agent", email="me@example.com")
    ticket = TicketFactory(organization=org, assigned_agent=agent)

    send_ticket_assigned_email(ticket.id)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["me@example.com"]
    assert ticket.reference in msg.subject
    html = _alt(msg)
    assert ticket.title in html


def test_ticket_resolved_email_addresses_requester():
    org = OrganizationFactory(name="Acme")
    ticket = TicketFactory(
        organization=org,
        requester_email="end@example.com",
        requester_name="Jane",
    )

    send_ticket_resolved_email(ticket.id)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["end@example.com"]
    assert "resolved" in msg.subject.lower()
    html = _alt(msg)
    assert "Acme" in html
    assert "Jane" in html


# ── Per-org branding overrides ────────────────────────────────────────


def test_email_from_name_overrides_display_name_in_from_header():
    org = OrganizationFactory(email_from_name="Acme Support")

    send_branded_email(
        template="otp_code",
        subject="x",
        to=["user@example.com"],
        organization=org,
        context={
            "kicker": "x",
            "heading": "x",
            "intro": "x",
            "code": "0",
            "expiry_minutes": 1,
        },
    )

    assert mail.outbox[0].from_email.startswith("Acme Support <")


def test_from_header_falls_back_to_brand_name_when_email_from_name_is_blank():
    org = OrganizationFactory(email_from_name="")

    send_branded_email(
        template="otp_code",
        subject="x",
        to=["user@example.com"],
        organization=org,
        context={
            "kicker": "x",
            "heading": "x",
            "intro": "x",
            "code": "0",
            "expiry_minutes": 1,
        },
    )

    # No org override -> default brand name (Showdesk) wraps the address.
    from_header = mail.outbox[0].from_email
    assert "Showdesk" in from_header or from_header.startswith("Showdesk")


def test_ticket_reply_email_renders_body_with_line_breaks_and_links():
    """Plain-text ``\\n`` becomes ``<br>``, raw URLs become ``<a>`` tags."""
    org = OrganizationFactory()
    agent = UserFactory(organization=org, role="agent", first_name="Alice")
    ticket = TicketFactory(
        organization=org,
        assigned_agent=agent,
        requester_email="end@example.com",
    )
    body = "Line one.\nLine two.\nVisit https://example.com for details."
    message = TicketMessageFactory(ticket=ticket, author=agent, body=body)

    send_ticket_reply_email(message.id)

    html = _alt(mail.outbox[0])
    # linebreaksbr -> <br>; urlize -> <a href="...">
    assert "<br>" in html
    assert 'href="https://example.com"' in html


def test_ticket_reply_email_lists_attachments_in_html_and_text():
    org = OrganizationFactory()
    agent = UserFactory(organization=org, role="agent")
    ticket = TicketFactory(
        organization=org,
        assigned_agent=agent,
        requester_email="end@example.com",
    )
    message = TicketMessageFactory(ticket=ticket, author=agent, body="See attached.")
    TicketAttachmentFactory(
        ticket=ticket,
        message=message,
        filename="screenshot.png",
        content_type="image/png",
        file_size=204800,
    )
    TicketAttachmentFactory(
        ticket=ticket,
        message=message,
        filename="logs.txt",
        content_type="text/plain",
        file_size=512,
    )

    send_ticket_reply_email(message.id)

    msg = mail.outbox[0]
    assert "screenshot.png" in msg.body
    assert "logs.txt" in msg.body
    html = _alt(msg)
    assert "screenshot.png" in html
    assert "logs.txt" in html
    # Pluralised header rendered.
    assert "2 attachments" in html


def test_primary_color_override_lands_in_html_body():
    org = OrganizationFactory(primary_color="#FF00AA")

    send_branded_email(
        template="otp_code",
        subject="x",
        to=["user@example.com"],
        organization=org,
        context={
            "kicker": "x",
            "heading": "x",
            "intro": "x",
            "code": "0",
            "expiry_minutes": 1,
        },
    )

    html = _alt(mail.outbox[0])
    assert "#FF00AA" in html or "#ff00aa" in html.lower()
