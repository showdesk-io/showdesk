"""Which tickets a widget session sees, and which sessions see a ticket (§6.2).

A session sees the tickets it opened, those of its external user, and every ticket
of its contact once it's identified on that contact or proved the address the
contact holds. Every widget route taking a ticket id goes through
``session_tickets``: a session id is a bearer token, and nothing else it sends is
proof of anything.
"""

from functools import reduce
from operator import or_

from django.db.models import Q, QuerySet

from .models import Ticket, WidgetSession


def contact_history_opens(session) -> bool:
    """Tell if this session may see every ticket of its contact.

    A signed external id on that contact, or a proof of the address the contact
    holds. A proof stored elsewhere opens nothing here, and neither does one of an
    address the contact no longer holds.
    """
    contact = session.contact
    if contact is None or contact.is_anonymized:
        return False
    if session.external_user_id:
        return contact.external_id == session.external_user_id
    email = session.email.strip().lower()
    return bool(
        session.email_verified_at and email and email == contact.email.strip().lower()
    )


def session_tickets(session) -> QuerySet[Ticket]:
    """The tickets ``session`` may open, in its organization."""
    query = Q(widget_session=session)
    if session.external_user_id:
        query |= Q(external_user_id=session.external_user_id)
    if contact_history_opens(session):
        query |= Q(contact_id=session.contact_id)
    return Ticket.objects.filter(query, organization_id=session.organization_id)


def ticket_session_ids(ticket) -> list[str]:
    """The sessions whose ``session_tickets`` hold ``ticket``, where its replies show."""
    queries = []
    if ticket.widget_session_id:
        queries.append(Q(pk=ticket.widget_session_id))
    if ticket.external_user_id:
        queries.append(Q(external_user_id=ticket.external_user_id))
    contact = ticket.contact if ticket.contact_id else None
    if contact is not None and not contact.is_anonymized:
        if contact.external_id:
            queries.append(Q(contact=contact, external_user_id=contact.external_id))
        if contact.email:
            queries.append(
                Q(
                    contact=contact,
                    external_user_id="",
                    email_verified_at__isnull=False,
                    email__iexact=contact.email.strip(),
                )
            )
    if not queries:
        return []
    sessions = WidgetSession.objects.filter(
        reduce(or_, queries), organization_id=ticket.organization_id
    ).select_related("contact")
    return [
        str(session.pk)
        for session in sessions
        if session.pk == ticket.widget_session_id
        or (
            ticket.external_user_id
            and session.external_user_id == ticket.external_user_id
        )
        or contact_history_opens(session)
    ]
