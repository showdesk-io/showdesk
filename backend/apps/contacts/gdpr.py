"""GDPR operations on contacts (export, anonymization)."""

import logging
import uuid

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.tickets.models import Ticket, TicketAttachment, TicketMessage
from apps.videos.models import VideoRecording

from .models import Contact

logger = logging.getLogger(__name__)

REMOVED_TITLE = "[Removed at the contact's request]"
REMOVED_BODY = "[Content removed at the contact's request]"
KEPT_CONTEXT_KEYS = {"browser", "os", "language", "timezone", "screen_resolution"}


def _delete_files_after_commit(files) -> None:
    """Delete ``files`` from their storage once the transaction holds.

    A storage has no rollback, and it's the one thing here that can fail for its own
    reasons: the failure of a file is logged with what it takes to remove it by hand.
    """
    to_delete = [(file.storage, file.name) for file in files if file]

    def delete() -> None:
        for storage, name in to_delete:
            try:
                storage.delete(name)
            except Exception:
                logger.exception("Couldn't delete the anonymized file %s", name)

    transaction.on_commit(delete)


def _delete_uploads(contact: Contact) -> None:
    """Delete what the contact uploaded on their tickets, rows and files.

    The widget uploads without a user, and so does anyone once their account is gone:
    a file with no uploader goes as well, rather than stay if it was the contact's.
    An agent's own files stay, like their replies.
    """
    attachments = TicketAttachment.objects.filter(ticket__contact=contact).filter(
        Q(uploaded_by__isnull=True) | Q(uploaded_by=F("ticket__requester"))
    )
    videos = VideoRecording.objects.filter(ticket__contact=contact).filter(
        Q(recorded_by__isnull=True) | Q(recorded_by=F("ticket__requester"))
    )
    _delete_files_after_commit(
        [
            *(attachment.file for attachment in attachments),
            *(
                file
                for video in videos
                for file in (video.original_file, video.processed_file, video.thumbnail)
            ),
        ]
    )
    attachments.delete()
    videos.delete()


def _scrub_tickets(contact: Contact) -> None:
    now = timezone.now()
    tickets = list(contact.tickets.all())
    for ticket in tickets:
        # Widget endpoints look a ticket up by session: this stops an open tab,
        # including one on a session since moved to another contact, adding to it.
        ticket.widget_session = None
        # The widget copies the first message into these two.
        ticket.title = REMOVED_TITLE
        ticket.description = REMOVED_BODY
        ticket.requester_email = contact.email
        ticket.requester_name = contact.name
        ticket.external_user_id = ""
        ticket.context_url = ""
        ticket.context_user_agent = ""
        # A whitelist: it also takes the ``pre_login_*`` trace of the login.
        metadata = ticket.context_metadata
        ticket.context_metadata = {
            key: value
            for key, value in (metadata if isinstance(metadata, dict) else {}).items()
            if key in KEPT_CONTEXT_KEYS
        }
        ticket.updated_at = now
    Ticket.objects.bulk_update(
        tickets,
        [
            "widget_session",
            "title",
            "description",
            "requester_email",
            "requester_name",
            "external_user_id",
            "context_url",
            "context_user_agent",
            "context_metadata",
            "updated_at",
        ],
        batch_size=500,
    )


@transaction.atomic
def anonymize_contact(contact: Contact) -> Contact | None:
    """Irreversibly strip personal data while keeping the structure of the tickets.

    Return the anonymized row, as it already was if it had been anonymized before, or
    None if it no longer exists. What this leaves is listed in the design document,
    section 8.
    """
    # Same row lock as the identity service, which checks ``is_anonymized`` under it,
    # and same order, contact then sessions: without this, a widget session resolving
    # at the same time could save the personal data back over the anonymized row.
    contact = Contact.objects.select_for_update().filter(pk=contact.pk).first()
    if contact is None or contact.is_anonymized:
        return contact

    contact.email = f"anonymized-{uuid.uuid4().hex}@example.invalid"
    contact.email_verified_at = None
    contact.declared_email = ""
    contact.name = "Anonymized contact"
    contact.phone = ""
    contact.external_id = ""
    contact.avatar_url = ""
    contact.job_title = ""
    contact.locale = ""
    contact.timezone = ""
    contact.company = None  # A small company can tell who this was.
    contact.attributes = {}
    contact.is_anonymized = True
    contact.save()

    # Free text written by agents, which can hold personal data about the contact.
    contact.notes.all().delete()
    # Unlinked as well, so an open tab can't attach new data to this contact.
    contact.sessions.update(
        email="",
        name="",
        external_user_id="",
        email_verified_at=None,
        user_agent="",
        contact=None,
    )
    _delete_uploads(contact)
    TicketMessage.objects.filter(
        ticket__contact=contact, sender_type=TicketMessage.SenderType.USER
    ).update(
        body=REMOVED_BODY,
        body_type=TicketMessage.BodyType.TEXT,
        widget_session=None,
        updated_at=timezone.now(),
    )
    _scrub_tickets(contact)
    return contact
