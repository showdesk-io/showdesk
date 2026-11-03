"""Celery tasks for ticket notifications.

Handles email notifications for ticket lifecycle events:
- New ticket created (notify assigned agent or all org agents)
- New reply on ticket (notify requester or agent depending on author)
- Ticket assigned (notify the assigned agent)
- Ticket resolved (notify the requester)
"""

import logging
from email.utils import parseaddr

from celery import shared_task
from django.conf import settings
from redis.exceptions import RedisError

from apps.core.email import send_branded_email
from apps.core.text import one_line
from apps.tickets.models import requester_can_be_emailed, requester_reply_address

logger = logging.getLogger(__name__)

SITE_URL = getattr(settings, "SITE_URL", "http://localhost")
# A reply mail finding its ticket's previous one still being sent waits this long.
REPLY_LOCK_RETRY_SECONDS = 15
# A reply mail that can't take its lock in a cache outage tries again, for an hour.
REPLY_LOCK_OUTAGE_RETRY_SECONDS = 60
REPLY_LOCK_OUTAGE_MAX_RETRIES = 60


def _ticket_url(ticket) -> str:
    """Build the frontend URL for a ticket."""
    return f"{SITE_URL}/tickets/{ticket.id}"


def _priority_label(ticket) -> str:
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
def send_ticket_created_email(self, ticket_id: str) -> None:
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
        logger.exception("Failed to send email for ticket %s", ticket.reference)
        raise self.retry(exc=exc)


def _attachments(message, attached=()) -> list[dict]:
    """The message's files as a mail names them: never by a storage URL.

    ``attached`` are those the mail carries.
    """
    return [
        {
            "filename": att.filename,
            "size": att.file_size,
            "attached": att.pk in attached,
        }
        for att in message.attachments.all()
    ]


def _reply_entry(message, author_label: str, attached=()) -> dict:
    return {
        "author_label": author_label,
        "author_initial": (author_label[:1] or "?").upper(),
        "body": message.body,
        "attachments": _attachments(message, attached),
    }


def _load_message(message_id: str):
    from apps.tickets.models import TicketMessage

    try:
        return TicketMessage.objects.select_related(
            "ticket",
            "ticket__organization",
            "ticket__assigned_agent",
            "ticket__contact",
            "ticket__mailbox",
            "author",
        ).get(id=message_id)
    except TicketMessage.DoesNotExist:
        logger.warning("Message %s not found, skipping email.", message_id)
        return None


def _requester_address(ticket) -> str:
    """Where an agent's reply on ``ticket`` is emailed, or "" if it isn't.

    An unsubscribed contact only gets the replies of a ticket they opened by email.
    """
    from apps.email_channel.outbound import suppressed_by_unsubscribe

    if suppressed_by_unsubscribe(ticket):
        return ""
    return requester_reply_address(ticket)


def _email_requester(task, message, address: str) -> None:
    """Email ``address`` the unread replies up to ``message``, ``message``'s mail.

    One reply mail at a time per ticket, so that two close replies don't both
    carry the same unread ones: a task finding the ticket busy comes back shortly.
    """
    from apps.email_channel import outbound

    ticket = message.ticket
    try:
        locked = outbound.lock_replies(ticket)
    except RedisError as exc:
        # Without the lock, two mails could carry the same replies: wait for the cache.
        logger.warning("Reply lock unavailable for ticket %s: %s", ticket.pk, exc)
        raise task.retry(
            countdown=REPLY_LOCK_OUTAGE_RETRY_SECONDS,
            max_retries=REPLY_LOCK_OUTAGE_MAX_RETRIES,
        ) from exc
    if not locked:
        raise task.retry(countdown=REPLY_LOCK_RETRY_SECONDS, max_retries=None)
    try:
        _send_requester_mail(task, message, address)
    finally:
        outbound.unlock_replies(ticket)


def _send_requester_mail(task, message, address: str) -> None:
    """Build and send ``message``'s mail; its Message-ID is the same on a retry."""
    from apps.email_channel import outbound
    from apps.email_channel.tokens import outbound_message_id
    from apps.tickets.models import TicketMessage

    # Another task may have sent it while this one waited for the ticket.
    message.refresh_from_db(fields=["email_delivery_status"])
    if message.email_delivery_status == TicketMessage.DeliveryStatus.SENT:
        return
    ticket = message.ticket
    replies = outbound.unread_replies(message)
    files, attached = outbound.mail_attachments(replies)
    entries = [
        _reply_entry(reply, outbound.sender_label(reply, address), attached)
        for reply in replies
    ]
    conversation_url = outbound.conversation_url(ticket, address)
    # The history recalls what the contact said: only for the contact's address.
    history = [
        {
            "author_label": outbound.sender_label(earlier, address),
            "body": earlier.body,
            "created_at": earlier.created_at,
        }
        for earlier in (
            outbound.context_messages(replies[0]) if conversation_url else ()
        )
    ]
    author_label = entries[-1]["author_label"]
    intro = (
        f"{author_label} replied to your support ticket."
        if len(entries) == 1
        else f"You have {len(entries)} new replies on your support ticket."
    )

    message_id = outbound_message_id(message)
    if message.external_id != message_id:
        TicketMessage.objects.filter(pk=message.pk).update(external_id=message_id)
    headers = {
        "Message-ID": message_id,
        **outbound.threading_headers(ticket, before=message.created_at),
    }

    try:
        send_branded_email(
            template="ticket_reply",
            subject=f"Re: [{ticket.reference}] {ticket.title}",
            to=[address],
            organization=ticket.organization,
            from_email=outbound.from_address(ticket),
            reply_to=outbound.reply_to(ticket),
            headers=headers,
            context={
                "ticket": ticket,
                "ticket_url": conversation_url or _ticket_url(ticket),
                "replies": entries,
                "history": history,
                "reply_marker": outbound.reply_marker(),
                "author_label": author_label,
                "intro": intro,
                "cta_label": "View conversation",
                "files_not_attached": any(
                    not file["attached"]
                    for entry in entries
                    for file in entry["attachments"]
                ),
                "files_url": conversation_url,
            },
            attachments=files,
        )
    except Exception as exc:
        logger.exception("Failed to send reply email for %s", ticket.reference)
        if task.request.retries >= task.max_retries:
            TicketMessage.objects.filter(pk=message.pk).update(
                email_delivery_status=TicketMessage.DeliveryStatus.FAILED
            )
        raise task.retry(exc=exc)
    TicketMessage.objects.filter(pk__in=[reply.pk for reply in replies]).update(
        email_delivery_status=TicketMessage.DeliveryStatus.SENT
    )
    logger.info("Sent reply email for %s.", ticket.reference)


def _is_agent_reply(message) -> bool:
    from apps.tickets.models import TicketMessage

    author = message.author
    return message.channel == TicketMessage.Channel.AGENT or bool(
        author and author.is_agent
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_reply_email(self, message_id: str) -> None:
    """Notify the relevant party when a reply is added.

    - If an agent replies -> email the requester, with the replies still unread
    - If the requester replies -> notify the assigned agent (or all agents)
    - Internal notes are never emailed externally
    """
    from apps.organizations.models import User
    from apps.tickets.models import TicketMessage

    message = _load_message(message_id)
    if message is None:
        return

    if message.message_type == TicketMessage.MessageType.INTERNAL_NOTE:
        logger.debug("Skipping email for internal note %s.", message_id)
        return

    ticket = message.ticket

    if _is_agent_reply(message):
        address = _requester_address(ticket)
        if not address:
            logger.info("No requester to email for ticket %s.", ticket.reference)
            return
        _email_requester(self, message, address)
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
        return
    # A mail's own sender, who can be someone in copy rather than the requester.
    sender_name, sender_address = parseaddr(message.external_sender)
    author_label = (
        one_line(sender_name)
        or sender_address
        or ticket.requester_name
        or ticket.requester_email
        or "Requester"
    )

    try:
        send_branded_email(
            template="ticket_reply",
            subject=f"Re: [{ticket.reference}] {ticket.title}",
            to=recipients,
            organization=ticket.organization,
            context={
                "ticket": ticket,
                "ticket_url": _ticket_url(ticket),
                "replies": [_reply_entry(message, author_label)],
                "author_label": author_label,
                "intro": f"{author_label} replied on ticket {ticket.reference}.",
                "cta_label": "Open ticket",
            },
        )
        logger.info(
            "Sent reply email for %s to %d recipients.",
            ticket.reference,
            len(recipients),
        )
    except Exception as exc:
        logger.exception("Failed to send reply email for %s", ticket.reference)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_unread_reply_email(self, message_id: str) -> None:
    """Email an agent's reply the requester left unread in the widget.

    Nothing if it was read, or if a later reply's own task will carry it.
    """
    from apps.email_channel import outbound
    from apps.tickets.models import TicketMessage

    message = _load_message(message_id)
    if (
        message is None
        or message.message_type == TicketMessage.MessageType.INTERNAL_NOTE
        or message.email_delivery_status == TicketMessage.DeliveryStatus.SENT
        or outbound.read_in_widget(message)
        or outbound.carried_by_later_reply(message)
    ):
        return
    address = _requester_address(message.ticket)
    if address:
        _email_requester(self, message, address)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_assigned_email(self, ticket_id: str) -> None:
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
        logger.exception("Failed to send assignment email for %s", ticket.reference)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_resolved_email(self, ticket_id: str) -> None:
    """Notify the requester when their ticket is resolved, on the ticket's thread."""
    from apps.email_channel import outbound
    from apps.email_channel.tokens import resolution_message_id
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related(
            "organization", "contact", "mailbox"
        ).get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    if not requester_can_be_emailed(ticket) or outbound.suppressed_by_unsubscribe(
        ticket
    ):
        return

    try:
        send_branded_email(
            template="ticket_resolved",
            subject=f"[{ticket.reference}] Your ticket has been resolved",
            to=[ticket.requester_email],
            organization=ticket.organization,
            from_email=outbound.from_address(ticket),
            reply_to=outbound.reply_to(ticket),
            headers={
                "Message-ID": resolution_message_id(ticket),
                **outbound.threading_headers(ticket),
            },
            context={
                "ticket": ticket,
                "requester_name": ticket.requester_name,
            },
        )
    except Exception as exc:
        logger.exception("Failed to send resolved email for %s", ticket.reference)
        raise self.retry(exc=exc)


@shared_task
def send_widget_email_code(session_id: str, email: str) -> None:
    """Mail a widget session the code proving ``email``, if there's anything to see.

    The route queues this for every request, so its answer and its time say nothing
    of the address. Here: only while the session still has that email and no proof
    of it, and only when the proof would open conversations it can't see (§6.2,
    Decision A). The code is good for this session and its organization alone. It's
    generated once: a failed send is retried with it (``deliver_widget_email_code``).
    """
    from apps.organizations.models import OTPCode
    from apps.tickets.access import email_proof_would_open
    from apps.tickets.models import WidgetSession, has_proof, normalized_email

    session = (
        WidgetSession.objects.select_related("organization", "contact")
        .filter(pk=session_id)
        .first()
    )
    if (
        session is None
        or not email
        or normalized_email(session.email) != email
        or has_proof(session)
        or not email_proof_would_open(session, email)
    ):
        return
    otp = OTPCode.generate(
        email,
        purpose=OTPCode.Purpose.WIDGET_EMAIL,
        organization=session.organization,
        widget_session=session,
    )
    deliver_widget_email_code.delay(str(otp.pk))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def deliver_widget_email_code(self, otp_id: str) -> None:
    """Send a widget email code, again on failure, while it's still to be used.

    By id: the code itself never goes through the broker.
    """
    from apps.organizations.models import OTPCode

    otp = (
        OTPCode.objects.select_related("organization")
        .filter(
            pk=otp_id,
            purpose=OTPCode.Purpose.WIDGET_EMAIL,
            used_at__isnull=True,
            organization__isnull=False,
        )
        .first()
    )
    if otp is None:
        return
    organization = otp.organization
    try:
        send_branded_email(
            template="widget_email_code",
            subject=f"Your code to see your conversations with {organization.name}",
            to=[otp.email],
            organization=organization,
            context={
                "organization": organization,
                "code": otp.code,
                "expiry_minutes": getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60,
            },
        )
    except Exception as exc:
        logger.exception("Failed to send a widget email code")
        raise self.retry(exc=exc)


# How long an agent's upload waits for the reply that names it.
ORPHAN_UPLOAD_AFTER_HOURS = 24


@shared_task
def purge_orphan_agent_uploads() -> int:
    """Delete agents' uploads no reply took within a day, with their files.

    The agent's app uploads a reply's files first: if the reply was never posted,
    nothing shows them. The files go once the deletion is committed. Return how
    many went.
    """
    from datetime import timedelta

    from django.db import transaction
    from django.utils import timezone

    from apps.tickets.models import TicketAttachment

    with transaction.atomic():
        orphans = list(
            TicketAttachment.objects.select_for_update(skip_locked=True).filter(
                awaiting_message=True,
                message__isnull=True,
                uploaded_by__isnull=False,
                created_at__lt=timezone.now()
                - timedelta(hours=ORPHAN_UPLOAD_AFTER_HOURS),
            )
        )
        files = [(a.file.storage, a.file.name) for a in orphans if a.file]
        TicketAttachment.objects.filter(pk__in=[a.pk for a in orphans]).delete()

        def delete_files() -> None:
            for storage, name in files:
                try:
                    storage.delete(name)
                except Exception:
                    logger.exception("Couldn't delete the orphan upload %s", name)

        transaction.on_commit(delete_files)
    return len(orphans)
