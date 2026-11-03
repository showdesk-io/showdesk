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

from apps.contacts.models import Contact
from apps.contacts.services import session_external_id

from .models import Ticket, WidgetSession, normalized_email, proof_holds


def contact_history_opens(session) -> bool:
    """Tell if this session may see every ticket of its contact.

    A signed external id on that contact, or a proof of the address the contact
    holds, made for that address. A proof stored elsewhere opens nothing here, and
    neither does one of an address the session or the contact no longer has.
    """
    contact = session.contact
    if contact is None or contact.is_anonymized:
        return False
    if session.external_user_id:
        return contact.external_id == session.external_user_id
    return proof_holds(session, contact)


def session_tickets(session) -> QuerySet[Ticket]:
    """The tickets ``session`` may open, in its organization."""
    query = Q(widget_session=session)
    if session.external_user_id:
        query |= Q(external_user_id=session.external_user_id)
    if contact_history_opens(session):
        query |= Q(contact_id=session.contact_id)
    return Ticket.objects.filter(query, organization_id=session.organization_id)


def writable_from(session, ticket) -> bool:
    """Tell if ``session``, which sees ``ticket``, may also write on it.

    Its own ticket, or one opened by email. A ticket another session opened only if
    that session is entitled too: a message there reaches the session that opened
    it, which may be anyone who once typed this address in the widget.
    """
    if ticket.widget_session_id in (None, session.pk):
        return True
    opener = ticket.widget_session
    if session.external_user_id and opener.external_user_id == session.external_user_id:
        return True
    return opener.contact_id == ticket.contact_id and contact_history_opens(opener)


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
        if email := normalized_email(contact.email):
            queries.append(
                Q(
                    contact=contact,
                    external_user_id="",
                    email_verified_at__isnull=False,
                    email_verified_for=email,
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


def email_proof_would_open(session, email: str) -> bool:
    """Tell if proving ``email`` would show ``session`` conversations it can't see.

    Those of the contact holding the address, when the proof would reach it: an
    anonymous session links to that contact, an identified one only takes an
    email-only contact's history into its own contact with no email (Contacts design
    §3 rule 1), and only with an external id the service would use. Anywhere else, a
    code would prove nothing.
    """
    org_id = session.organization_id
    holder = Contact.objects.filter(
        organization_id=org_id, email=email, is_anonymized=False
    ).first()
    if holder is None:
        return False
    if session.external_user_id:
        external_id = session_external_id(session)
        if not external_id:
            return False
        own = Contact.objects.filter(
            organization_id=org_id, external_id=external_id
        ).first()
        reunites = not holder.external_id and (own is None or not own.email)
        if (own is None or own.pk != holder.pk) and not reunites:
            return False
    return (
        Ticket.objects.filter(organization_id=org_id, contact=holder)
        .exclude(pk__in=session_tickets(session).values("pk"))
        .exists()
    )
