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

from apps.organizations.models import User, is_end_user_account
from apps.tickets.models import Ticket, TicketAttachment, TicketMessage
from apps.videos.models import VideoRecording

from .models import ANONYMIZED_EMAIL_DOMAIN, Contact

logger = logging.getLogger(__name__)

REMOVED_TITLE = "[Removed at the contact's request]"
REMOVED_BODY = "[Content removed at the contact's request]"
KEPT_CONTEXT_KEYS = {"browser", "os", "language", "timezone", "screen_resolution"}
MAX_KEPT_CONTEXT_LENGTH = 100
# What mail servers commonly accept, counted as sent: base64 adds a third.
MAX_EXPORT_ENCODED_BYTES = 20 * 1024 * 1024
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


def _the_requester(field: str) -> Q:
    """Match ``field`` being the ticket's requester, when that's the contact's account.

    An agent or admin of the organization filing a ticket for a contact stays an agent:
    what they write or upload there is their work, like any agent's.
    """
    return Q(**{field: F("ticket__requester")}) & ~Q(
        **{
            f"{field}__role__in": (User.Role.AGENT, User.Role.ADMIN),
            f"{field}__organization": F("ticket__organization"),
        }
    )


def _by_the_contact(field: str) -> Q:
    """Match an upload the contact made.

    The widget uploads without a user, and so does anyone once their account is gone:
    a file with no uploader counts as well, rather than stay if it was the contact's.
    """
    return Q(**{f"{field}__isnull": True}) | _the_requester(field)


def _contacts_recordings(videos):
    return videos.filter(_by_the_contact("recorded_by"))


def _delete_uploads(ticket_ids) -> None:
    """Delete what the contact uploaded on these tickets, rows and files.

    An agent's own files stay, like their replies. By primary key: a row added since
    they were read isn't lost while its file stays on the storage.
    """
    attachments = list(
        TicketAttachment.objects.filter(ticket__in=ticket_ids).filter(
            _by_the_contact("uploaded_by")
        )
    )
    videos = list(
        _contacts_recordings(VideoRecording.objects.filter(ticket__in=ticket_ids))
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
    TicketAttachment.objects.filter(pk__in=[row.pk for row in attachments]).delete()
    VideoRecording.objects.filter(pk__in=[row.pk for row in videos]).delete()


def _kept_metadata(metadata) -> dict:
    """Keep the whitelist, which also takes the ``pre_login_*`` trace of a login.

    A page can put anything in there: only a value that looks like what the key is for
    stays.
    """
    return {
        key: value
        for key, value in (metadata if isinstance(metadata, dict) else {}).items()
        if key in KEPT_CONTEXT_KEYS
        and isinstance(value, str)
        and len(value) <= MAX_KEPT_CONTEXT_LENGTH
        and "@" not in value
    }


def _kept_requester_id(ticket: Ticket):
    """Keep staff filing a ticket for a contact, but not an end user's account.

    ``requester_detail`` would show its name and email. The account itself stays, as
    it isn't the contact's to erase. Read before the scrub, ``_the_requester`` still
    finds its messages and uploads.
    """
    requester = ticket.requester
    if requester and is_end_user_account(requester.role, requester.is_superuser):
        return None
    return ticket.requester_id


def _scrubbed_ticket(contact: Contact, ticket: Ticket) -> dict:
    return {
        "requester_id": _kept_requester_id(ticket),
        # A ticket caught by its external id can be on an email-only contact, which
        # would go on naming that address next to the scrubbed ticket. One an agent
        # cleared stays cleared.
        "contact_id": contact.pk if ticket.contact_id else None,
        # Widget endpoints look a ticket up by session: this stops an open tab,
        # including one on a session since moved to another contact, adding to it.
        "widget_session_id": None,
        # The widget copies the first message into these two.
        "title": REMOVED_TITLE,
        "description": REMOVED_BODY,
        "requester_email": contact.email,
        "requester_name": contact.name,
        "external_user_id": "",
        "context_url": "",
        "context_user_agent": "",
        "context_metadata": _kept_metadata(ticket.context_metadata),
    }


def _scrub_tickets(contact: Contact, tickets) -> None:
    """Scrub the tickets that need it, so that doing it again changes nothing."""
    now = timezone.now()
    changed = []
    fields: set[str] = set()
    for ticket in tickets:
        scrubbed = _scrubbed_ticket(contact, ticket)
        fields.update(scrubbed)
        if all(getattr(ticket, field) == value for field, value in scrubbed.items()):
            continue
        for field, value in scrubbed.items():
            setattr(ticket, field, value)
        ticket.updated_at = now
        changed.append(ticket)
    Ticket.objects.bulk_update(changed, [*fields, "updated_at"], batch_size=500)


def _scrub_messages(ticket_ids) -> None:
    body_type = TicketMessage.BodyType.TEXT
    TicketMessage.objects.filter(
        Q(sender_type=TicketMessage.SenderType.USER) | _the_requester("author"),
        ticket__in=ticket_ids,
    ).exclude(body=REMOVED_BODY, body_type=body_type, widget_session=None).update(
        body=REMOVED_BODY,
        body_type=body_type,
        widget_session=None,
        updated_at=timezone.now(),
    )


def _tickets_of(contact: Contact, session_ids, external_id: str):
    """Return the contact's tickets, and those it wrote that don't say so.

    An agent can clear a ticket's contact. And ``widget_submit`` takes an external id
    unsigned and links by email alone: a ticket with this contact's id can be on no
    contact, or on an email-only one. It's scrubbed whichever: it would still match
    the id's history otherwise. To be read before the sessions are unlinked.
    """
    others = Q(contact__isnull=True, widget_session__in=session_ids)
    if external_id:
        others |= Q(external_user_id=external_id)
    return Ticket.objects.filter(
        Q(contact=contact) | (Q(organization_id=contact.organization_id) & others)
    )


def _scrub_contact(contact: Contact) -> None:
    email = contact.email
    if not (contact.is_anonymized and email.endswith(f"@{ANONYMIZED_EMAIL_DOMAIN}")):
        email = f"anonymized-{uuid.uuid4().hex}@{ANONYMIZED_EMAIL_DOMAIN}"
    scrubbed = {
        "email": email,
        "email_verified_at": None,
        "declared_email": "",
        "name": "Anonymized contact",
        "phone": "",
        "external_id": "",
        "avatar_url": "",
        "job_title": "",
        "locale": "",
        "timezone": "",
        "company_id": None,  # A small company can tell who this was.
        "attributes": {},
        "last_contacted_at": None,
        "is_anonymized": True,
    }
    changed = [
        field for field, value in scrubbed.items() if getattr(contact, field) != value
    ]
    for field in changed:
        setattr(contact, field, scrubbed[field])
    if changed:
        contact.save(update_fields=[*changed, "updated_at"])


@transaction.atomic
def anonymize_contact(contact: Contact) -> Contact | None:
    """Irreversibly strip personal data while keeping the structure of the tickets.

    Return the anonymized row, or None if it no longer exists. What this leaves is
    listed in the design document, section 8.

    On an already anonymized contact it does all of it again, keeping the anonymized
    email: that repairs what a request holding older data wrote since, and changes
    nothing, not even a date, if there's nothing to repair.
    """
    # Same row lock as the identity service, which checks ``is_anonymized`` under it,
    # and same order, contact then sessions: without this, a widget session resolving
    # at the same time could save the personal data back over the anonymized row.
    contact = Contact.objects.select_for_update().filter(pk=contact.pk).first()
    if contact is None:
        return None

    tickets = list(
        _tickets_of(
            contact,
            list(contact.sessions.values_list("pk", flat=True)),
            contact.external_id,
        ).select_related("requester")
    )
    ticket_ids = [ticket.pk for ticket in tickets]
    _scrub_contact(contact)

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
    _delete_uploads(ticket_ids)
    _scrub_messages(ticket_ids)
    _scrub_tickets(contact, tickets)
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


def export_fits_an_email(export: bytes) -> bool:
    """Tell if ``export`` is within the limit once base64 encoded, as an email sends it."""
    return 4 * ((len(export) + 2) // 3) <= MAX_EXPORT_ENCODED_BYTES


def build_contact_export(contact: Contact) -> bytes:
    """Return a ZIP of what the organization holds about ``contact``.

    Internal ticket notes stay out, and so do the files themselves: only their metadata
    goes. Agent notes about the contact are in, without who wrote them.
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
                # An agent's upload has no message, even for an internal note: only
                # the contact's own say nothing internal.
                TicketAttachment.objects.filter(
                    Q(message__isnull=True) & _by_the_contact("uploaded_by")
                    | Q(message__message_type=public)
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
