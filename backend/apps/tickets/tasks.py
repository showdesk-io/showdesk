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
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

SITE_URL = getattr(settings, "SITE_URL", "http://localhost")


def _ticket_url(ticket) -> str:  # noqa: ANN001
    """Build the frontend URL for a ticket."""
    return f"{SITE_URL}/tickets/{ticket.id}"


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

    # Determine recipients
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

    subject = f"[{ticket.reference}] New ticket: {ticket.title}"
    body = (
        f"A new ticket has been submitted.\n\n"
        f"Reference: {ticket.reference}\n"
        f"Title: {ticket.title}\n"
        f"Priority: {ticket.get_priority_display()}\n"
        f"Source: {ticket.get_source_display()}\n"
        f"Requester: {ticket.requester_name} ({ticket.requester_email})\n\n"
        f"Description:\n{ticket.description[:500]}\n\n"
        f"View ticket: {_ticket_url(ticket)}\n"
    )

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
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

    # Never email internal notes
    if message.message_type == TicketMessage.MessageType.INTERNAL_NOTE:
        logger.debug("Skipping email for internal note %s.", message_id)
        return

    ticket = message.ticket
    author = message.author

    # Determine if author is an agent or the requester
    is_agent_reply = author and author.role in (User.Role.AGENT, User.Role.ADMIN)

    if is_agent_reply:
        # Agent replied -> notify requester
        if not ticket.requester_email:
            logger.info("No requester email for ticket %s.", ticket.reference)
            return
        recipients = [ticket.requester_email]
        subject = f"Re: [{ticket.reference}] {ticket.title}"
        body = (
            f"You have a new reply on your support ticket.\n\n"
            f"Reference: {ticket.reference}\n"
            f"Subject: {ticket.title}\n\n"
            f"Reply from {author.first_name or 'Support'}:\n"
            f"---\n{message.body}\n---\n\n"
            f"To reply, visit: {_ticket_url(ticket)}\n"
        )
    else:
        # Requester replied -> notify assigned agent or all agents
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

        requester_name = ticket.requester_name or ticket.requester_email
        subject = f"Re: [{ticket.reference}] {ticket.title}"
        body = (
            f"New reply from {requester_name} on ticket {ticket.reference}.\n\n"
            f"---\n{message.body}\n---\n\n"
            f"View ticket: {_ticket_url(ticket)}\n"
        )

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
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

    subject = f"[{ticket.reference}] Ticket assigned to you: {ticket.title}"
    body = (
        f"A ticket has been assigned to you.\n\n"
        f"Reference: {ticket.reference}\n"
        f"Title: {ticket.title}\n"
        f"Priority: {ticket.get_priority_display()}\n"
        f"Requester: {ticket.requester_name} ({ticket.requester_email})\n\n"
        f"View ticket: {_ticket_url(ticket)}\n"
    )

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ticket.assigned_agent.email],
            fail_silently=False,
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

    subject = f"[{ticket.reference}] Your ticket has been resolved"
    body = (
        f"Good news! Your support ticket has been resolved.\n\n"
        f"Reference: {ticket.reference}\n"
        f"Subject: {ticket.title}\n\n"
        f"If you still need help, you can reopen the ticket by replying.\n\n"
        f"-- The {ticket.organization.name} team\n"
    )

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ticket.requester_email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.error("Failed to send resolved email for %s: %s", ticket.reference, exc)
        raise self.retry(exc=exc)
