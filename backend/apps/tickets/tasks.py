"""Celery tasks for ticket notifications.

Handles email notifications for ticket lifecycle events:
- New ticket created (notify assigned agent or all org agents)
- New reply on ticket (notify requester or agent depending on author)
- Ticket assigned (notify the assigned agent)
- Ticket resolved (notify the requester)
"""

import logging

from celery import shared_task
from django.conf import settings

from apps.core.email import send_branded_email

logger = logging.getLogger(__name__)

SITE_URL = getattr(settings, "SITE_URL", "http://localhost")


def _ticket_url(ticket) -> str:  # noqa: ANN001
    """Build the frontend URL for a ticket."""
    return f"{SITE_URL}/tickets/{ticket.id}"


def _priority_label(ticket) -> str:  # noqa: ANN001
    """Resolve the human-readable priority name.

    Custom per-org priorities live in ``PriorityLevel``; built-in slugs map
    to ``Ticket.Priority`` labels; unknown slugs fall back to title case.
    """
    from apps.tickets.models import PriorityLevel, Ticket

    slug = ticket.priority or ""
    level = PriorityLevel.objects.filter(
        organization=ticket.organization_id, slug=slug
    ).first()
    if level:
        return level.name
    try:
        return Ticket.Priority(slug).label
    except ValueError:
        return slug.replace("_", " ").title() or "—"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_created_email(self, ticket_id: str) -> None:  # noqa: ANN001
    """Notify agents when a new ticket is created.

    If the ticket has an assigned agent, only that agent is notified.
    Otherwise, all active agents in the org receive the email.
    """
    from apps.organizations.models import User
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related("organization", "assigned_agent").get(
            id=ticket_id
        )
    except Ticket.DoesNotExist:
        logger.warning("Ticket %s not found, skipping email.", ticket_id)
        return

    if ticket.assigned_agent and ticket.assigned_agent.email:
        recipients = [ticket.assigned_agent.email]
    else:
        recipients = list(
            User.objects.filter(
                organization=ticket.organization,
                role__in=[User.Role.AGENT, User.Role.ADMIN],
                is_active=True,
            ).values_list("email", flat=True)
        )

    if not recipients:
        logger.info("No agents to notify for ticket %s.", ticket.reference)
        return

    description = (ticket.description or "").strip()
    if len(description) > 500:
        description = description[:500].rstrip() + "…"

    priority_label = _priority_label(ticket)
    meta_rows = [
        {"label": "Reference", "value": ticket.reference},
        {"label": "Priority", "value": priority_label},
        {"label": "Source", "value": ticket.get_source_display()},
        {
            "label": "Requester",
            "value": f"{ticket.requester_name} ({ticket.requester_email})",
        },
    ]

    try:
        send_branded_email(
            template="ticket_created",
            subject=f"[{ticket.reference}] New ticket: {ticket.title}",
            to=recipients,
            organization=ticket.organization,
            context={
                "ticket": ticket,
                "ticket_url": _ticket_url(ticket),
                "description": description,
                "meta_rows": meta_rows,
                "priority_label": priority_label,
            },
        )
        logger.info(
            "Sent new ticket email for %s to %d recipients.",
            ticket.reference,
            len(recipients),
        )
    except Exception as exc:
        logger.error("Failed to send email for ticket %s: %s", ticket.reference, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_reply_email(self, message_id: str) -> None:  # noqa: ANN001
    """Notify the relevant party when a reply is added.

    - If an agent replies -> notify the requester
    - If the requester replies -> notify the assigned agent (or all agents)
    - Internal notes are never emailed externally
    """
    from apps.organizations.models import User
    from apps.tickets.models import TicketMessage

    try:
        message = TicketMessage.objects.select_related(
            "ticket", "ticket__organization", "ticket__assigned_agent", "author"
        ).get(id=message_id)
    except TicketMessage.DoesNotExist:
        logger.warning("Message %s not found, skipping email.", message_id)
        return

    if message.message_type == TicketMessage.MessageType.INTERNAL_NOTE:
        logger.debug("Skipping email for internal note %s.", message_id)
        return

    ticket = message.ticket
    author = message.author
    is_agent_reply = author and author.role in (User.Role.AGENT, User.Role.ADMIN)

    if is_agent_reply:
        if not ticket.requester_email:
            logger.info("No requester email for ticket %s.", ticket.reference)
            return
        recipients = [ticket.requester_email]
        author_label = (
            (author.first_name or "").strip()
            or (author.email.split("@")[0] if author.email else "Support")
        )
        intro = f"{author_label} replied to your support ticket."
        cta_label = "View conversation"
    else:
        if ticket.assigned_agent and ticket.assigned_agent.email:
            recipients = [ticket.assigned_agent.email]
        else:
            recipients = list(
                User.objects.filter(
                    organization=ticket.organization,
                    role__in=[User.Role.AGENT, User.Role.ADMIN],
                    is_active=True,
                ).values_list("email", flat=True)
            )
        if not recipients:
            return
        author_label = ticket.requester_name or ticket.requester_email or "Requester"
        intro = f"{author_label} replied on ticket {ticket.reference}."
        cta_label = "Open ticket"

    initial = (author_label[:1] or "?").upper()

    attachments = [
        {
            "filename": att.filename,
            "url": att.file.url if att.file else "",
            "size": att.file_size,
        }
        for att in message.attachments.all()
    ]

    try:
        send_branded_email(
            template="ticket_reply",
            subject=f"Re: [{ticket.reference}] {ticket.title}",
            to=recipients,
            organization=ticket.organization,
            context={
                "ticket": ticket,
                "ticket_url": _ticket_url(ticket),
                "message_body": message.body,
                "author_label": author_label,
                "author_initial": initial,
                "intro": intro,
                "cta_label": cta_label,
                "attachments": attachments,
            },
        )
        logger.info(
            "Sent reply email for %s to %d recipients.",
            ticket.reference,
            len(recipients),
        )
    except Exception as exc:
        logger.error("Failed to send reply email for %s: %s", ticket.reference, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_assigned_email(self, ticket_id: str) -> None:  # noqa: ANN001
    """Notify an agent when a ticket is assigned to them."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related("assigned_agent", "organization").get(
            id=ticket_id
        )
    except Ticket.DoesNotExist:
        return

    if not ticket.assigned_agent or not ticket.assigned_agent.email:
        return

    priority_label = _priority_label(ticket)
    meta_rows = [
        {"label": "Reference", "value": ticket.reference},
        {"label": "Priority", "value": priority_label},
        {
            "label": "Requester",
            "value": f"{ticket.requester_name} ({ticket.requester_email})",
        },
    ]

    try:
        send_branded_email(
            template="ticket_assigned",
            subject=f"[{ticket.reference}] Ticket assigned to you: {ticket.title}",
            to=[ticket.assigned_agent.email],
            organization=ticket.organization,
            context={
                "ticket": ticket,
                "ticket_url": _ticket_url(ticket),
                "meta_rows": meta_rows,
                "priority_label": priority_label,
            },
        )
    except Exception as exc:
        logger.error(
            "Failed to send assignment email for %s: %s", ticket.reference, exc
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_resolved_email(self, ticket_id: str) -> None:  # noqa: ANN001
    """Notify the requester when their ticket is resolved."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related("organization").get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    if not ticket.requester_email:
        return

    try:
        send_branded_email(
            template="ticket_resolved",
            subject=f"[{ticket.reference}] Your ticket has been resolved",
            to=[ticket.requester_email],
            organization=ticket.organization,
            context={
                "ticket": ticket,
                "requester_name": ticket.requester_name,
            },
        )
    except Exception as exc:
        logger.error("Failed to send resolved email for %s: %s", ticket.reference, exc)
        raise self.retry(exc=exc)
