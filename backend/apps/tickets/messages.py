"""Writing a requester's message, shared by the widget and the conversation page."""

from django.db import transaction

from apps.contacts.models import Contact

from .models import Ticket, TicketMessage, WidgetSession

# Attempts at locking a ticket with the contact it has, should it change meanwhile.
_LOCK_ATTEMPTS = 3


class MessageRefused(Exception):
    """The ticket takes no more messages from its requester: its contact was anonymized."""


def lock_ticket_with_contact(ticket_id) -> tuple[Ticket | None, Contact | None]:
    """Lock a ticket's contact, then the ticket, in this transaction.

    In the order ``anonymize_contact`` takes them, contact first: an anonymization
    either commits before, and the contact reads anonymized here, or waits for this
    transaction, and then scrubs what it wrote. Return the locked ticket, None if
    it's gone, and its contact.
    """
    for _ in range(_LOCK_ATTEMPTS):
        contact_id = (
            Ticket.objects.filter(pk=ticket_id)
            .values_list("contact_id", flat=True)
            .first()
        )
        contact = (
            Contact.objects.select_for_update(no_key=True).filter(pk=contact_id).first()
            if contact_id
            else None
        )
        ticket = (
            Ticket.objects.select_for_update(no_key=True).filter(pk=ticket_id).first()
        )
        if ticket is None or ticket.contact_id == contact_id:
            return ticket, contact
    raise MessageRefused


def create_user_message(
    ticket, *, only_contacts_session: bool = False, **fields
) -> TicketMessage:
    """Create a requester's message on the session its ticket is on now.

    A login may have moved the ticket since the request found it through the anonymous
    session. Under this lock, either the login is over and the message follows the
    ticket, or it's still to come and it will move the committed message.

    ``only_contacts_session`` leaves the message off a session that isn't the ticket
    contact's, for a writer who isn't that session (the conversation page).

    Raise ``MessageRefused`` if the ticket's contact is anonymized.
    """
    with transaction.atomic():
        locked, contact = lock_ticket_with_contact(ticket.pk)
        if locked is None or (contact is not None and contact.is_anonymized):
            raise MessageRefused
        session_id = locked.widget_session_id
        if (
            only_contacts_session
            and session_id
            and not WidgetSession.objects.filter(
                pk=session_id, contact_id=locked.contact_id, contact_id__isnull=False
            ).exists()
        ):
            session_id = None
        return TicketMessage.objects.create(
            ticket=ticket,
            widget_session_id=session_id,
            sender_type=TicketMessage.SenderType.USER,
            **fields,
        )
