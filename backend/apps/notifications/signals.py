"""Signals for sending real-time notifications via WebSocket."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.tickets.access import ticket_session_ids

logger = logging.getLogger(__name__)


def notify_ticket_update(ticket) -> None:
    """Send a ticket update notification to the organization channel."""
    channel_layer = get_channel_layer()
    group_name = f"org_{ticket.organization_id}"

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "ticket_update",
            "data": {
                "event": "ticket.updated",
                "ticket_id": str(ticket.id),
                "reference": ticket.reference,
                "status": ticket.status,
                "priority": ticket.priority,
            },
        },
    )


def notify_new_ticket(ticket) -> None:
    """Send a new ticket notification to the organization channel."""
    channel_layer = get_channel_layer()
    group_name = f"org_{ticket.organization_id}"

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "ticket_new",
            "data": {
                "event": "ticket.created",
                "ticket_id": str(ticket.id),
                "reference": ticket.reference,
                "title": ticket.title,
                "priority": ticket.priority,
            },
        },
    )


def notify_new_message(message) -> None:
    """Send a new message notification to the organization channel.

    Also broadcasts to the group of each widget session that sees the ticket (the
    one that opened it, and those entitled to its contact's history), so the
    end-user receives agent replies in real-time.
    """
    channel_layer = get_channel_layer()
    group_name = f"org_{message.ticket.organization_id}"
    logger.info(
        "notify_new_message: publishing to %s (message=%s sender=%s type=%s)",
        group_name,
        message.id,
        message.sender_type,
        message.message_type,
    )

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "ticket_message",
            "data": {
                "event": "message.created",
                "ticket_id": str(message.ticket_id),
                "message_id": str(message.id),
                "reference": message.ticket.reference,
                "message_type": message.message_type,
            },
        },
    )

    # Broadcast to widget session for real-time chat (never send internal notes)
    if message.message_type == "internal_note":
        return
    event = {
        "type": "widget_message",
        "data": {
            "event": "message.created",
            "ticket_id": str(message.ticket_id),
            "message_id": str(message.id),
            "body": message.body,
            "body_type": getattr(message, "body_type", "text"),
            "sender_type": getattr(message, "sender_type", "agent"),
            "sender_name": message.sender_name,
            "created_at": message.created_at.isoformat(),
        },
    }
    for session_id in ticket_session_ids(message.ticket):
        async_to_sync(channel_layer.group_send)(f"widget_session_{session_id}", event)


def notify_message_deleted(ticket, message_id: str) -> None:
    """Notify agent dashboard and widget that a message was deleted."""
    channel_layer = get_channel_layer()

    # Notify agents
    async_to_sync(channel_layer.group_send)(
        f"org_{ticket.organization_id}",
        {
            "type": "ticket_message_deleted",
            "data": {
                "event": "message.deleted",
                "ticket_id": str(ticket.id),
                "message_id": message_id,
                "reference": ticket.reference,
            },
        },
    )

    # And every widget session that sees the ticket, so it can take the message off.
    for session_id in ticket_session_ids(ticket):
        async_to_sync(channel_layer.group_send)(
            f"widget_session_{session_id}",
            {
                "type": "widget_message",
                "data": {
                    "event": "message.deleted",
                    "ticket_id": str(ticket.id),
                    "message_id": message_id,
                },
            },
        )
