"""Render and send a branded email template with sample data.

Usage:
    python manage.py preview_email --list
    python manage.py preview_email ticket_reply --to me@example.com
    python manage.py preview_email otp_code --to me@example.com --org acme

Sends through the regular ``send_branded_email`` helper so the rendered
output matches production exactly (CTA buttons, From: header formatting,
per-org branding overrides). In dev with the Mailpit SMTP backend the
mail lands in http://localhost:18025; in tests / EMAIL_BACKEND=locmem
it lands in ``django.core.mail.outbox``.

Sample contexts intentionally include URLs and multi-line bodies so
designers can see how line breaks, autolinks, and attachment lists
render.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from django.core.management.base import BaseCommand, CommandError

from apps.core.email import send_branded_email


def _fake_org(name: str = "Acme Inc") -> SimpleNamespace:
    """Stand-in for ``ticket.organization``. ``ticket.organization.name``
    is the only attribute templates touch on this object.
    """
    return SimpleNamespace(name=name)


def _fake_ticket(**overrides: Any) -> SimpleNamespace:
    base = {
        "title": "Cannot upload my profile picture",
        "reference": "ACM-1042",
        "requester_name": "Jane Doe",
        "requester_email": "jane@example.com",
        "organization": _fake_org(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# Each entry returns (subject, context_dict). Functions (not dicts) so the
# fake objects are constructed afresh per invocation -- handy if a sample
# ever needs to mutate state during rendering.
SAMPLES: dict[str, Callable[[], tuple[str, dict[str, Any]]]] = {
    "ticket_created": lambda: (
        "[ACM-1042] New ticket: Cannot upload my profile picture",
        {
            "ticket": _fake_ticket(),
            "ticket_url": "https://app.showdesk.io/tickets/ACM-1042",
            "description": (
                "Hi team,\n\nWhen I try to upload a JPG larger than 2 MB I get "
                "a generic 'something went wrong' toast and nothing happens.\n\n"
                "Steps to reproduce: https://example.com/repro"
            ),
            "meta_rows": [
                {"label": "Priority", "value": "High"},
                {"label": "Source", "value": "Widget"},
                {"label": "Browser", "value": "Chrome 124 / macOS"},
            ],
            "priority_label": "High",
        },
    ),
    "ticket_reply": lambda: (
        "Re: [ACM-1042] Cannot upload my profile picture",
        {
            "ticket": _fake_ticket(),
            "ticket_url": "https://app.showdesk.io/tickets/ACM-1042",
            "message_body": (
                "Thanks for the report!\n\nWe pushed a fix this morning -- "
                "could you try again and let us know?\n\nDetails: "
                "https://status.example.com/incident/482"
            ),
            "author_label": "Alice",
            "author_initial": "A",
            "intro": "Alice replied to your support ticket.",
            "cta_label": "View conversation",
            "attachments": [
                {
                    "filename": "screenshot.png",
                    "url": "https://example.com/preview/screenshot.png",
                    "size": 204800,
                },
                {
                    "filename": "console-log.txt",
                    "url": "https://example.com/preview/console-log.txt",
                    "size": 1280,
                },
            ],
        },
    ),
    "ticket_assigned": lambda: (
        "[ACM-1042] Ticket assigned to you: Cannot upload my profile picture",
        {
            "ticket": _fake_ticket(),
            "ticket_url": "https://app.showdesk.io/tickets/ACM-1042",
            "meta_rows": [
                {"label": "Priority", "value": "High"},
                {"label": "Requester", "value": "Jane Doe"},
            ],
            "priority_label": "High",
        },
    ),
    "ticket_resolved": lambda: (
        "[ACM-1042] Your ticket has been resolved",
        {
            "ticket": _fake_ticket(),
            "requester_name": "Jane",
        },
    ),
    "otp_code": lambda: (
        "Showdesk login code: 482917",
        {
            "kicker": "Sign in",
            "heading": "Your Showdesk login code",
            "intro": "Use the code below to finish signing in.",
            "code": "482917",
            "expiry_minutes": 10,
        },
    ),
    "agent_invitation": lambda: (
        "You've been invited to Acme on Showdesk",
        {
            "first_name": "Bob",
            "email": "bob@example.com",
            "org_name": "Acme",
            "login_url": "https://app.showdesk.io/login",
        },
    ),
    "signup_welcome": lambda: (
        "Welcome to Showdesk",
        {
            "first_name": "Jane",
            "email": "jane@example.com",
            "org_name": "Acme",
        },
    ),
    "join_request_submitted": lambda: (
        "New join request for Acme",
        {
            "org_name": "Acme",
            "requester_name": "Jane Doe",
            "requester_email": "jane@example.com",
        },
    ),
    "join_request_approved": lambda: (
        "You're in -- welcome to Acme",
        {
            "first_name": "Jane",
            "email": "jane@example.com",
            "org_name": "Acme",
            "login_url": "https://app.showdesk.io/login",
        },
    ),
    "join_request_rejected": lambda: (
        "About your request to join Acme",
        {
            "org_name": "Acme",
            "requester_name": "Jane Doe",
        },
    ),
    "domain_verified": lambda: (
        "acme.com is verified on Showdesk",
        {
            "org_name": "Acme",
            "domain": "acme.com",
        },
    ),
    "domain_ownership_transferred": lambda: (
        "acme.com no longer belongs to your organization",
        {
            "losing_org_name": "Acme",
            "new_owner_name": "Acme Corp",
            "domain": "acme.com",
        },
    ),
}


class Command(BaseCommand):
    help = (
        "Render any branded email template with sample data and send it. "
        "Use --list to see available templates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "template",
            nargs="?",
            help="Template name (e.g. ticket_reply). Omit with --list.",
        )
        parser.add_argument(
            "--to",
            default="preview@example.com",
            help="Recipient address. Defaults to preview@example.com.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List available templates and exit.",
        )
        parser.add_argument(
            "--org",
            default=None,
            help=(
                "Slug of an Organization whose branding (logo, primary_color, "
                "email_from_name) should be applied. Lets you preview how the "
                "email looks for a specific tenant."
            ),
        )

    def handle(self, *args, **options):
        if options["list"]:
            self.stdout.write(self.style.MIGRATE_HEADING("Available templates:"))
            for name in sorted(SAMPLES):
                self.stdout.write(f"  {name}")
            return

        name = options["template"]
        if not name:
            raise CommandError(
                "Provide a template name (or pass --list). "
                f"Available: {', '.join(sorted(SAMPLES))}."
            )
        if name not in SAMPLES:
            raise CommandError(
                f"Unknown template '{name}'. Available: {', '.join(sorted(SAMPLES))}."
            )

        organization = None
        if options["org"]:
            from apps.organizations.models import Organization

            try:
                organization = Organization.objects.get(slug=options["org"])
            except Organization.DoesNotExist as exc:
                raise CommandError(
                    f"Organization with slug '{options['org']}' not found."
                ) from exc

        subject, context = SAMPLES[name]()
        send_branded_email(
            template=name,
            subject=f"[PREVIEW] {subject}",
            to=[options["to"]],
            context=context,
            organization=organization,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent preview of '{name}' to {options['to']}"
                + (f" (branded for org '{organization.slug}')" if organization else "")
                + "."
            )
        )
