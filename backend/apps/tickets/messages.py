"""Writing a requester's message, shared by the widget and the conversation page."""

from django.db import transaction

from .models import Ticket, TicketMessage


def create_user_message(ticket, **fields) -> TicketMessage:
    """Create a requester's message on the session its ticket is on now.

    A login may have moved the ticket since the request found it through the anonymous
    session. Under this lock, either the login is over and the message follows the
    ticket, or it's still to come and it will move the committed message.
    """
    with transaction.atomic():
        session_id = (
            Ticket.objects.select_for_update(no_key=True)
            .values_list("widget_session_id", flat=True)
            .get(pk=ticket.pk)
        )
        return TicketMessage.objects.create(
            ticket=ticket,
            widget_session_id=session_id,
            sender_type=TicketMessage.SenderType.USER,
            **fields,
        )
