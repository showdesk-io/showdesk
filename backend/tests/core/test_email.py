"""Tests for the branded email helper and ticket-related email tasks.

Verifies that every transactional email ships an HTML alternative alongside
the plain-text body and that the key context (reference, code, links) ends
up in both renderings.
"""

import pytest
from django.core import mail

from apps.core.email import send_branded_email
from apps.tickets.models import TicketMessage
from apps.tickets.tasks import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_reply_email,
    send_ticket_resolved_email,
)
from tests.factories import (
    ContactFactory,
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


def test_send_branded_email_attaches_files():
    send_branded_email(
        template="contact_export_ready",
        subject="Hi",
        to=["user@example.com"],
        context={"contact_name": "A"},
        attachments=[("a.zip", b"PK", "application/zip")],
    )
    assert mail.outbox[0].attachments == [("a.zip", b"PK", "application/zip")]
    assert _alt(mail.outbox[0])


def test_send_branded_email_has_no_attachments_by_default():
    send_branded_email(
        template="contact_export_ready",
        subject="Hi",
        to=["user@example.com"],
        context={"contact_name": "A"},
    )
    assert mail.outbox[0].attachments == []


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


@pytest.fixture
def mail_ticket():
    org = OrganizationFactory()
    return (
        UserFactory(organization=org, role="agent"),
        TicketFactory(organization=org, requester_email="end@example.com"),
    )


def _undeliverable_cases(ticket):
    """Each way a requester can no longer be emailed."""
    anonymized = ContactFactory(organization=ticket.organization, is_anonymized=True)
    return {
        "contact-anonymized": {"contact": anonymized},
        "address-anonymized": {"requester_email": "anonymized-1@example.invalid"},
        "address-other-case": {"requester_email": "Anonymized-1@EXAMPLE.invalid"},
    }


@pytest.mark.parametrize(
    "case", ["contact-anonymized", "address-anonymized", "address-other-case"]
)
def test_agent_reply_isnt_emailed_to_an_anonymized_requester(mail_ticket, case):
    agent, ticket = mail_ticket
    for field, value in _undeliverable_cases(ticket)[case].items():
        setattr(ticket, field, value)
    ticket.save()
    message = TicketMessageFactory(ticket=ticket, author=agent, body="Hello")

    send_ticket_reply_email(message.id)

    assert mail.outbox == []


@pytest.mark.parametrize(
    "case", ["contact-anonymized", "address-anonymized", "address-other-case"]
)
def test_resolved_ticket_isnt_emailed_to_an_anonymized_requester(mail_ticket, case):
    _, ticket = mail_ticket
    for field, value in _undeliverable_cases(ticket)[case].items():
        setattr(ticket, field, value)
    ticket.save()

    send_ticket_resolved_email(ticket.id)

    assert mail.outbox == []


def test_requester_of_a_regular_contact_is_still_emailed(mail_ticket):
    agent, ticket = mail_ticket
    ticket.contact = ContactFactory(organization=ticket.organization)
    ticket.save()
    message = TicketMessageFactory(ticket=ticket, author=agent, body="Hello")

    send_ticket_reply_email(message.id)
    send_ticket_resolved_email(ticket.id)

    assert [message.to for message in mail.outbox] == [["end@example.com"]] * 2


def test_a_visitor_at_that_domain_with_a_regular_contact_is_still_emailed(mail_ticket):
    _, ticket = mail_ticket
    ticket.contact = ContactFactory(organization=ticket.organization)
    ticket.requester_email = "visitor@example.invalid"
    ticket.save()

    send_ticket_resolved_email(ticket.id)

    assert [message.to for message in mail.outbox] == [["visitor@example.invalid"]]


def test_anonymized_requesters_reply_still_reaches_agents(mail_ticket):
    agent, ticket = mail_ticket
    ticket.contact = ContactFactory(
        organization=ticket.organization, is_anonymized=True
    )
    ticket.assigned_agent = agent
    ticket.save()
    message = TicketMessageFactory(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        body="Hello",
    )

    send_ticket_reply_email(message.id)

    assert [message.to for message in mail.outbox] == [[agent.email]]


@pytest.fixture
def blank_requester_ticket(mail_ticket):
    agent, ticket = mail_ticket
    ticket.requester_email = ""
    ticket.save()
    return agent, ticket


def _reply_recipients(agent, ticket):
    message = TicketMessageFactory(ticket=ticket, author=agent, body="Hello")
    send_ticket_reply_email(message.id)
    return [message.to for message in mail.outbox]


@pytest.mark.parametrize(
    ("fields", "address"),
    [
        ({"email": "held@x.io"}, "held@x.io"),
        ({"declared_email": "said@x.io"}, "said@x.io"),
        ({"email": "held@x.io", "declared_email": "said@x.io"}, "held@x.io"),
    ],
)
def test_agent_reply_falls_back_on_the_address_of_the_contact(
    blank_requester_ticket, fields, address
):
    agent, ticket = blank_requester_ticket
    ticket.contact = ContactFactory(
        **{"email": "", "external_id": "u1", **fields},
        organization=ticket.organization,
    )
    ticket.save()

    assert _reply_recipients(agent, ticket) == [[address]]


def test_agent_reply_prefers_the_address_of_the_ticket(mail_ticket):
    agent, ticket = mail_ticket
    ticket.contact = ContactFactory(organization=ticket.organization, email="held@x.io")
    ticket.save()

    assert _reply_recipients(agent, ticket) == [["end@example.com"]]


def test_agent_reply_isnt_emailed_without_any_address(blank_requester_ticket):
    agent, ticket = blank_requester_ticket
    ticket.contact = ContactFactory(
        organization=ticket.organization, email="", external_id="u1"
    )
    ticket.save()

    assert _reply_recipients(agent, ticket) == []


def test_agent_reply_isnt_emailed_without_a_contact(blank_requester_ticket):
    agent, ticket = blank_requester_ticket

    assert _reply_recipients(agent, ticket) == []


def test_agent_reply_doesnt_fall_back_on_an_anonymized_contact(blank_requester_ticket):
    agent, ticket = blank_requester_ticket
    ticket.contact = ContactFactory(
        organization=ticket.organization,
        email="anonymized-1@example.invalid",
        declared_email="stale@x.io",
        is_anonymized=True,
    )
    ticket.save()

    assert _reply_recipients(agent, ticket) == []


def test_agent_reply_doesnt_fall_back_on_who_logged_in_after_it_was_written(
    blank_requester_ticket,
):
    """On a shared computer, whoever logs in isn't necessarily who wrote the ticket."""
    agent, ticket = blank_requester_ticket
    ticket.contact = ContactFactory(organization=ticket.organization, email="held@x.io")
    ticket.context_metadata = {"pre_login_anonymous": True}
    ticket.save()

    assert _reply_recipients(agent, ticket) == []


def test_unsubscribing_doesnt_stop_a_reply_whichever_address_it_goes_to(
    blank_requester_ticket,
):
    """A reply to their own ticket is essential, and nothing enforces it yet anyway."""
    agent, ticket = blank_requester_ticket
    ticket.contact = ContactFactory(
        organization=ticket.organization, email="held@x.io", is_unsubscribed=True
    )
    ticket.save()

    assert _reply_recipients(agent, ticket) == [["held@x.io"]]
