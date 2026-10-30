"""GDPR operations on contacts (export, anonymization)."""

import csv
import io
import json
import logging
import uuid
import zipfile

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.utils import timezone

from apps.tickets.models import Ticket, TicketAttachment, TicketMessage
from apps.videos.models import VideoRecording

from .models import Contact

logger = logging.getLogger(__name__)

REMOVED_TITLE = "[Removed at the contact's request]"
REMOVED_BODY = "[Content removed at the contact's request]"
KEPT_CONTEXT_KEYS = {"browser", "os", "language", "timezone", "screen_resolution"}
# What mail servers commonly accept, once the encoding has added its third.
MAX_EXPORT_ATTACHMENT_BYTES = 20 * 1024 * 1024
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


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


def _contacts_recordings(videos):
    return videos.filter(
        Q(recorded_by__isnull=True) | Q(recorded_by=F("ticket__requester"))
    )


def _delete_uploads(contact: Contact) -> None:
    """Delete what the contact uploaded on their tickets, rows and files.

    The widget uploads without a user, and so does anyone once their account is gone:
    a file with no uploader goes as well, rather than stay if it was the contact's.
    An agent's own files stay, like their replies.
    """
    attachments = TicketAttachment.objects.filter(ticket__contact=contact).filter(
        Q(uploaded_by__isnull=True) | Q(uploaded_by=F("ticket__requester"))
    )
    videos = _contacts_recordings(
        VideoRecording.objects.filter(ticket__contact=contact)
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


def _profile(contact: Contact) -> dict:
    fields = (
        "id",
        "name",
        "email",
        "email_verified_at",
        "declared_email",
        "external_id",
        "phone",
        "avatar_url",
        "job_title",
        "locale",
        "timezone",
        "first_seen_at",
        "last_seen_at",
        "last_contacted_at",
        "is_unsubscribed",
        "is_anonymized",
        "attributes",
        "created_at",
    )
    return {
        **{field: getattr(contact, field) for field in fields},
        "company": contact.company.name if contact.company else None,
        # About the contact, so theirs to read, unlike who at the organization wrote it.
        "notes": [
            {"body": note.body, "created_at": note.created_at}
            for note in contact.notes.order_by("created_at", "id")
        ],
    }


def _exported_ticket(ticket: Ticket) -> dict:
    fields = (
        "id",
        "reference",
        "title",
        "description",
        "status",
        "priority",
        "source",
        "requester_name",
        "requester_email",
        "external_user_id",
        "context_url",
        "context_user_agent",
        "context_os",
        "context_browser",
        "context_screen_resolution",
        "created_at",
        "resolved_at",
        "closed_at",
    )
    metadata = ticket.context_metadata
    return {
        **{field: getattr(ticket, field) for field in fields},
        "context_metadata": {
            key: value
            for key, value in (metadata if isinstance(metadata, dict) else {}).items()
            if not key.startswith("pre_login_")  # Our trace of a login, not theirs.
        },
        "messages": [
            {
                "sender_type": message.sender_type,
                "body": message.body,
                "body_type": message.body_type,
                "created_at": message.created_at,
            }
            for message in ticket.public_messages
        ],
        "attachments": [
            {
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "file_size": attachment.file_size,
                "created_at": attachment.created_at,
            }
            for attachment in ticket.public_attachments
        ],
        "recordings": [
            {
                "recording_type": video.recording_type,
                "duration_seconds": video.duration_seconds,
                "file_size": video.file_size,
                "transcription": video.transcription,
                "created_at": video.created_at,
            }
            for video in ticket.contacts_recordings
        ],
    }


def _csv_cell(value) -> str:
    """Return ``value`` as text a spreadsheet won't run as a formula."""
    if value is None:
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return f"'{text}" if text.startswith(_CSV_FORMULA_PREFIXES) else text


def _tickets_csv(tickets) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["reference", "title", "status", "created_at", "resolved_at"])
    for ticket in tickets:
        writer.writerow(
            _csv_cell(value)
            for value in (
                ticket.reference,
                ticket.title,
                ticket.status,
                ticket.created_at,
                ticket.resolved_at,
            )
        )
    return output.getvalue()


def _dumps(data) -> str:
    return json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)


def build_contact_export(contact: Contact) -> bytes:
    """Return a ZIP of what the organization holds about ``contact``.

    Internal notes stay out, and so do the files themselves: only their metadata goes.
    """
    public = TicketMessage.MessageType.REPLY
    tickets = list(
        Ticket.objects.filter(contact=contact, organization_id=contact.organization_id)
        .order_by("created_at", "id")
        .prefetch_related(
            Prefetch(
                "messages",
                TicketMessage.objects.filter(message_type=public).order_by(
                    "created_at", "id"
                ),
                to_attr="public_messages",
            ),
            Prefetch(
                "attachments",
                TicketAttachment.objects.filter(
                    Q(message__isnull=True) | Q(message__message_type=public)
                ).order_by("created_at", "id"),
                to_attr="public_attachments",
            ),
            Prefetch(
                "videos",
                _contacts_recordings(VideoRecording.objects.all()).order_by(
                    "created_at", "id"
                ),
                to_attr="contacts_recordings",
            ),
        )
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("contact.json", _dumps(_profile(contact)))
        archive.writestr(
            "tickets.json", _dumps([_exported_ticket(ticket) for ticket in tickets])
        )
        archive.writestr("tickets.csv", _tickets_csv(tickets))
    return buffer.getvalue()
