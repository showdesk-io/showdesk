"""Report rows that link across organizations, without changing anything.

Usage:
    python manage.py audit_tenant_links

Prints a count per kind of link, then the ids of the rows concerned (for a
many-to-many link, both ids). It prints ids only, never personal data, and
exits 0 whatever it finds: reading the result is up to whoever runs it.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.core.management.base import BaseCommand
from django.db.models import F

from apps.knowledge_base.models import Article
from apps.organizations.models import Team, User
from apps.tickets.models import Ticket, TicketAttachment, TicketMessage


def _foreign_key(model, field: str) -> Iterable:
    """Rows of ``model`` whose ``field`` isn't in their organization.

    ``exclude`` keeps a related row with no organization: it isn't in theirs.
    """
    return (
        model.objects.filter(**{f"{field}__isnull": False})
        .exclude(**{f"{field}__organization_id": F("organization_id")})
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _many_to_many(model, field: str, target: str) -> Iterable:
    """(row id, target id) pairs of ``model.field`` outside the row's organization."""
    owner = model._meta.model_name
    return (
        getattr(model, field)
        .through.objects.exclude(
            **{f"{target}__organization_id": F(f"{owner}__organization_id")}
        )
        .order_by(f"{owner}_id", f"{target}_id")
        .values_list(f"{owner}_id", f"{target}_id")
    )


def _message_authors() -> Iterable:
    """Staff messages signed outside the ticket's organization.

    Superusers impersonate organizations and end users write from the widget:
    neither says anything about tenant isolation.
    """
    return (
        TicketMessage.objects.filter(
            author__role__in=[User.Role.AGENT, User.Role.ADMIN],
            author__is_superuser=False,
        )
        .exclude(author__organization_id=F("ticket__organization_id"))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _attachment_messages() -> Iterable:
    """Attachments of a message that belongs to another ticket."""
    return (
        TicketAttachment.objects.filter(message__isnull=False)
        .exclude(message__ticket_id=F("ticket_id"))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


class Command(BaseCommand):
    help = "Read-only: print the ids of rows linking across organizations."

    def handle(self, *args, **options) -> None:
        checks = {
            "ticket.assigned_agent": _foreign_key(Ticket, "assigned_agent"),
            "ticket.assigned_team": _foreign_key(Ticket, "assigned_team"),
            "ticket.requester": _foreign_key(Ticket, "requester"),
            "ticket.sla_policy": _foreign_key(Ticket, "sla_policy"),
            "ticket.tags": _many_to_many(Ticket, "tags", "tag"),
            "team.lead": _foreign_key(Team, "lead"),
            "team.members": _many_to_many(Team, "members", "user"),
            "article.category": _foreign_key(Article, "category"),
            "article.author": _foreign_key(Article, "author"),
            "ticket_message.author": _message_authors(),
            "ticket_attachment.message": _attachment_messages(),
        }

        total = 0
        for name, rows in checks.items():
            rows = list(rows)
            total += len(rows)
            self.stdout.write(f"{name}: {len(rows)}")
            for row in rows:
                ids = row if isinstance(row, tuple) else (row,)
                self.stdout.write("  " + " ".join(str(value) for value in ids))

        self.stdout.write(f"cross_org_links: {total}")
        superusers = User.objects.filter(
            is_superuser=True, organization__isnull=False
        ).count()
        self.stdout.write(f"superusers_with_organization: {superusers}")
