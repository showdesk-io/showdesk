"""Anonymization and export of a contact."""

import csv
import hashlib
import hmac
import io
import json
import zipfile
from unittest import mock

import pytest
from django.core import mail
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.contacts.gdpr import (
    REMOVED_BODY,
    REMOVED_TITLE,
    anonymize_contact,
    build_contact_export,
)
from apps.contacts.models import Contact
from apps.contacts.services import resolve_contact_for_widget_session
from apps.contacts.tasks import export_contact_data
from apps.tickets.models import Ticket, TicketAttachment, TicketMessage, WidgetSession
from apps.videos.models import VideoRecording
from tests.factories import (
    CompanyFactory,
    ContactFactory,
    ContactNoteFactory,
    EndUserFactory,
    OrganizationFactory,
    TicketAttachmentFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
    VideoRecordingFactory,
)

pytestmark = pytest.mark.django_db
SESSION_URL = "/api/v1/tickets/widget_session/"


def _url(contact, action: str) -> str:
    return f"/api/v1/contacts/{contact.id}/{action}/"


def _widget_headers(organization, session) -> dict:
    return {
        "HTTP_X_WIDGET_TOKEN": str(organization.api_token),
        "HTTP_X_WIDGET_SESSION": str(session.id),
    }


def _file(name: str = "secret.txt") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"personal data")


@pytest.fixture
def media(settings, tmp_path):
    """Local files, as the default storage needs an S3 server."""
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path)},
        },
    }
    return tmp_path


# Anonymization: what it scrubs


def test_anonymize_scrubs_the_contact(organization, agent):
    now = timezone.now()
    company = CompanyFactory(organization=organization)
    contact = ContactFactory(
        organization=organization,
        company=company,
        name="Alice",
        email="alice@x.io",
        email_verified_at=now,
        declared_email="other@x.io",
        external_id="u1",
        phone="+33",
        avatar_url="https://x.io/a.png",
        job_title="CTO",
        locale="fr",
        timezone="Europe/Paris",
        attributes={"plan": "pro"},
    )
    ContactNoteFactory(contact=contact, author=agent, body="Her husband is ill")

    anonymize_contact(contact)

    contact.refresh_from_db()
    assert contact.is_anonymized
    assert contact.email.startswith("anonymized-")
    assert contact.email.endswith("@example.invalid")
    assert contact.email_verified_at is None
    assert contact.name == "Anonymized contact"
    for field in (
        "declared_email",
        "external_id",
        "phone",
        "avatar_url",
        "job_title",
        "locale",
        "timezone",
    ):
        assert getattr(contact, field) == "", field
    assert contact.attributes == {}
    assert contact.company is None
    assert not contact.notes.exists()  # Free text: it can hold personal data.


def test_anonymize_scrubs_the_sessions(organization):
    contact = ContactFactory(organization=organization, external_id="u1")
    session = WidgetSession.objects.create(
        organization=organization,
        contact=contact,
        email="alice@x.io",
        name="Alice",
        external_user_id="u1",
        email_verified_at=timezone.now(),
        user_agent="Mozilla/5.0",
    )
    other = WidgetSession.objects.create(organization=organization, email="b@x.io")

    anonymize_contact(contact)

    session.refresh_from_db()
    assert (session.email, session.name, session.external_user_id) == ("", "", "")
    assert session.email_verified_at is None
    assert session.user_agent == ""
    assert session.contact is None
    other.refresh_from_db()
    assert other.email == "b@x.io"


def test_anonymize_scrubs_the_tickets(organization):
    contact = ContactFactory(organization=organization, external_id="u1")
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, external_user_id="u1"
    )
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        widget_session=session,
        title="Alice's invoice",  # The widget copies the first message here.
        description="My card number is 4242",
        requester_email="alice@x.io",
        requester_name="Alice",
        external_user_id="u1",
        context_url="https://app/x?token=1",
        context_user_agent="Mozilla/5.0",
        context_metadata={
            "browser": "Chrome",
            "url_params": {"t": 1},
            "pre_login_session_hash": "abc",
            "pre_login_sender": "x",
        },
    )
    before = ticket.updated_at

    anonymize_contact(contact)

    contact.refresh_from_db()
    ticket.refresh_from_db()
    assert ticket.contact == contact
    assert ticket.widget_session is None
    assert (ticket.title, ticket.description) == (REMOVED_TITLE, REMOVED_BODY)
    assert ticket.requester_email == contact.email
    assert ticket.requester_name == contact.name
    assert ticket.external_user_id == ""
    assert ticket.context_url == ""
    assert ticket.context_user_agent == ""
    assert ticket.context_metadata == {"browser": "Chrome"}
    assert ticket.updated_at > before


def test_anonymize_replaces_only_the_contacts_messages(organization, agent):
    contact = ContactFactory(organization=organization)
    session = WidgetSession.objects.create(organization=organization, contact=contact)
    ticket = TicketFactory(organization=organization, contact=contact, requester=None)
    other_ticket = TicketFactory(organization=organization, requester=None)
    mine = TicketMessageFactory(
        ticket=ticket,
        author=None,
        widget_session=session,
        sender_type=TicketMessage.SenderType.USER,
        body_type=TicketMessage.BodyType.IMAGE,
        body="secret",
    )
    reply = TicketMessageFactory(ticket=ticket, author=agent, body="reply")
    theirs = TicketMessageFactory(
        ticket=other_ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        body="kept",
    )

    anonymize_contact(contact)

    for message in (mine, reply, theirs):
        message.refresh_from_db()
    assert mine.body == REMOVED_BODY
    assert mine.body_type == TicketMessage.BodyType.TEXT  # Its media are gone.
    assert mine.widget_session is None  # No delete by an open tab, no sender name.
    assert reply.body == "reply"
    assert theirs.body == "kept"


def test_anonymize_leaves_the_requester_user_alone(organization):
    """Open issue in the design: an account isn't the Contact's to erase."""
    requester = EndUserFactory(organization=organization)
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=requester
    )
    anonymize_contact(contact)
    ticket.refresh_from_db()
    assert ticket.requester == requester


def test_anonymize_is_idempotent(organization, agent):
    contact = ContactFactory(organization=organization, email="a@x.io")
    session = WidgetSession.objects.create(organization=organization, contact=contact)
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        widget_session=session,
    )
    message = TicketMessageFactory(
        ticket=ticket, author=None, sender_type=TicketMessage.SenderType.USER
    )
    TicketMessageFactory(ticket=ticket, author=agent, body="Agent's")
    anonymize_contact(contact)
    contact.refresh_from_db()
    ticket.refresh_from_db()
    message.refresh_from_db()
    first = (contact.email, contact.updated_at, ticket.updated_at, message.updated_at)

    anonymize_contact(contact)

    contact.refresh_from_db()
    ticket.refresh_from_db()
    message.refresh_from_db()
    assert (
        contact.email,
        contact.updated_at,
        ticket.updated_at,
        message.updated_at,
    ) == first


def test_anonymizing_again_repairs_what_a_stale_write_restored(
    organization, media, django_capture_on_commit_callbacks
):
    """A request holding the row from before can save it back in full."""
    contact = ContactFactory(organization=organization, email="a@x.io", name="Alice")
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, email="a@x.io", name="Alice"
    )
    stale = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        widget_session=session,
        title="Alice's invoice",
        requester_email="a@x.io",
        requester_name="Alice",
    )
    message = TicketMessageFactory(
        ticket=stale,
        author=None,
        widget_session=session,
        sender_type=TicketMessage.SenderType.USER,
    )
    stale_title = stale.title
    anonymize_contact(contact)
    contact.refresh_from_db()
    anonymized_email = contact.email

    Ticket.objects.filter(pk=stale.pk).update(
        title=stale_title,
        requester_email="a@x.io",
        requester_name="Alice",
        widget_session=session,
    )
    TicketMessage.objects.filter(pk=message.pk).update(body="secret")
    Contact.objects.filter(pk=contact.pk).update(name="Alice", phone="+33")
    WidgetSession.objects.filter(pk=session.pk).update(contact=contact, email="a@x.io")
    upload = TicketAttachmentFactory(ticket=stale, uploaded_by=None, file=_file())
    path = media / upload.file.name

    with django_capture_on_commit_callbacks(execute=True):
        anonymize_contact(contact)

    contact.refresh_from_db()
    stale.refresh_from_db()
    message.refresh_from_db()
    session.refresh_from_db()
    assert contact.email == anonymized_email
    assert contact.name == "Anonymized contact"
    assert contact.phone == ""
    assert stale.title == REMOVED_TITLE
    assert stale.requester_email == anonymized_email
    assert stale.requester_name == "Anonymized contact"
    assert stale.widget_session is None
    assert message.body == REMOVED_BODY
    assert session.email == ""
    assert session.contact is None
    assert not TicketAttachment.objects.filter(pk=upload.pk).exists()
    assert not path.exists()


def test_anonymizing_again_replaces_a_real_email_a_stale_write_restored(organization):
    contact = ContactFactory(organization=organization, email="a@x.io")
    anonymize_contact(contact)
    Contact.objects.filter(pk=contact.pk).update(email="a@x.io")

    anonymize_contact(contact)

    contact.refresh_from_db()
    assert contact.email.startswith("anonymized-")
    assert contact.email.endswith("@example.invalid")


def test_anonymizing_again_scrubs_a_ticket_written_since(organization):
    """What a widget request past its session lookup can leave: see design, section 8."""
    contact = ContactFactory(organization=organization)
    anonymize_contact(contact)
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=None, title="Late"
    )
    anonymize_contact(contact)
    ticket.refresh_from_db()
    assert ticket.title == REMOVED_TITLE


def test_anonymizing_a_deleted_contact_does_nothing(organization):
    contact = ContactFactory(organization=organization)
    Contact.objects.filter(pk=contact.pk).delete()
    assert anonymize_contact(contact) is None


# Anonymization: files


def test_anonymize_deletes_the_contacts_files(
    organization, agent, media, django_capture_on_commit_callbacks
):
    requester = EndUserFactory(organization=organization)
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=requester
    )
    message = TicketMessageFactory(
        ticket=ticket, author=None, sender_type=TicketMessage.SenderType.USER
    )
    uploads = [
        # In a message, and with no message at all (widget_upload_attachment).
        TicketAttachmentFactory(
            ticket=ticket, message=message, uploaded_by=None, file=_file()
        ),
        TicketAttachmentFactory(ticket=ticket, uploaded_by=None, file=_file()),
        TicketAttachmentFactory(ticket=ticket, uploaded_by=requester, file=_file()),
    ]
    recordings = [
        VideoRecordingFactory(
            ticket=ticket,
            original_file=_file("a.webm"),
            processed_file=_file("b.mp4"),
            thumbnail=_file("c.jpg"),
        ),
        VideoRecordingFactory(
            ticket=ticket, recorded_by=requester, original_file=_file("d.webm")
        ),
    ]
    paths = [media / upload.file.name for upload in uploads]
    for recording in recordings:
        for field in (
            recording.original_file,
            recording.processed_file,
            recording.thumbnail,
        ):
            if field:
                paths.append(media / field.name)
    assert all(path.exists() for path in paths)
    agents_file = TicketAttachmentFactory(
        ticket=ticket, uploaded_by=agent, file=_file()
    )
    agents_video = VideoRecordingFactory(
        ticket=ticket, recorded_by=agent, original_file=_file("agent.webm")
    )
    other = TicketAttachmentFactory(
        ticket=TicketFactory(organization=organization),
        uploaded_by=None,
        file=_file(),
    )

    with django_capture_on_commit_callbacks(execute=True):
        anonymize_contact(contact)

    assert not any(path.exists() for path in paths)
    assert list(TicketAttachment.objects.order_by("id")) == sorted(
        [agents_file, other], key=lambda row: row.id
    )
    assert list(VideoRecording.objects.all()) == [agents_video]
    assert (media / agents_file.file.name).exists()
    assert (media / agents_video.original_file.name).exists()
    assert (media / other.file.name).exists()


def test_a_rolled_back_anonymization_keeps_the_files(
    organization, media, django_capture_on_commit_callbacks
):
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(organization=organization, contact=contact, requester=None)
    upload = TicketAttachmentFactory(ticket=ticket, uploaded_by=None, file=_file())

    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(ZeroDivisionError),
        transaction.atomic(),
    ):
        anonymize_contact(contact)
        raise ZeroDivisionError

    assert (media / upload.file.name).exists()
    assert TicketAttachment.objects.filter(pk=upload.pk).exists()


def test_a_file_that_cant_be_deleted_is_logged_and_stops_nothing(
    organization, media, django_capture_on_commit_callbacks, caplog
):
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(organization=organization, contact=contact, requester=None)
    upload = TicketAttachmentFactory(ticket=ticket, uploaded_by=None, file=_file())
    name = upload.file.name
    TicketAttachmentFactory(ticket=ticket, uploaded_by=None, file=_file())

    with (
        mock.patch.object(FileSystemStorage, "delete", side_effect=OSError) as delete,
        django_capture_on_commit_callbacks(execute=True),
    ):
        anonymize_contact(contact)

    assert delete.call_count == 2  # The first failure doesn't stop the next file.
    assert name in caplog.text
    contact.refresh_from_db()
    assert contact.is_anonymized


# Anonymization: an open tab, and what comes later


def test_open_tab_cant_attach_new_data_to_the_anonymized_contact(
    api_client, organization
):
    contact = ContactFactory(organization=organization, external_id="u1")
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, external_user_id="u1"
    )
    anonymize_contact(contact)
    session.refresh_from_db()
    assert resolve_contact_for_widget_session(session) is None
    res = api_client.post(
        "/api/v1/tickets/widget_message/",
        {"body": "Still here"},
        format="json",
        **_widget_headers(organization, session),
    )
    assert res.status_code == 201
    assert session.tickets.count() == 1
    assert session.tickets.get().contact is None
    assert not contact.tickets.exists()


def test_open_tab_cant_add_messages_to_a_ticket_of_the_anonymized_contact(
    api_client, organization
):
    contact = ContactFactory(organization=organization, external_id="u1")
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, external_user_id="u1"
    )
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        widget_session=session,
    )
    anonymize_contact(contact)
    headers = _widget_headers(organization, session)

    res = api_client.post(
        "/api/v1/tickets/widget_message/",
        {"body": "Still here", "ticket_id": str(ticket.id)},
        format="json",
        **headers,
    )
    assert res.status_code == 404
    res = api_client.post(
        "/api/v1/tickets/widget_message_attachment/",
        {"ticket_id": str(ticket.id), "file": _file("a.txt")},
        format="multipart",
        **headers,
    )
    assert res.status_code == 404
    assert not ticket.messages.exists()
    assert not ticket.attachments.exists()


def test_session_since_moved_to_another_contact_loses_the_ticket_too(
    api_client, organization
):
    contact = ContactFactory(organization=organization)
    moved_to = ContactFactory(organization=organization)
    session = WidgetSession.objects.create(organization=organization, contact=moved_to)
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        widget_session=session,
    )
    anonymize_contact(contact)
    res = api_client.post(
        "/api/v1/tickets/widget_message/",
        {"body": "Still here", "ticket_id": str(ticket.id)},
        format="json",
        **_widget_headers(organization, session),
    )
    assert res.status_code == 404
    session.refresh_from_db()
    assert session.contact == moved_to


def test_uploads_by_ticket_id_are_refused_on_an_anonymized_contact(
    api_client, organization, media
):
    """Those endpoints take a ticket id and no session at all."""
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(organization=organization, contact=contact, requester=None)
    anonymize_contact(contact)
    headers = {"HTTP_X_WIDGET_TOKEN": str(organization.api_token)}

    res = api_client.post(
        "/api/v1/tickets/widget_upload_attachment/",
        {"ticket": str(ticket.id), "file": _file("a.txt")},
        format="multipart",
        **headers,
    )
    assert res.status_code == 404
    assert not ticket.attachments.exists()
    res = api_client.post(
        "/api/v1/videos/widget_upload/",
        {
            "ticket": str(ticket.id),
            "original_file": SimpleUploadedFile(
                "a.webm", b"x", content_type="video/webm"
            ),
            "mime_type": "video/webm",
        },
        format="multipart",
        **headers,
    )
    assert res.status_code == 404
    assert not ticket.videos.exists()


def test_upload_by_ticket_id_still_works_on_other_tickets(
    api_client, organization, media
):
    ticket = TicketFactory(organization=organization, contact=None, requester=None)
    res = api_client.post(
        "/api/v1/tickets/widget_upload_attachment/",
        {"ticket": str(ticket.id), "file": _file("a.txt")},
        format="multipart",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
    )
    assert res.status_code == 201


def test_a_later_widget_init_cant_repopulate_the_anonymized_contact(api_client):
    organization = OrganizationFactory(widget_secret="s3cret")
    contact = ContactFactory(
        organization=organization,
        external_id="u1",
        email="alice@x.io",
        name="Alice",
    )
    old_session = WidgetSession.objects.create(
        organization=organization, contact=contact, external_user_id="u1"
    )
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        widget_session=old_session,
        external_user_id="u1",
    )
    anonymize_contact(contact)
    contact.refresh_from_db()
    scrubbed = (contact.email, contact.name, contact.external_id, contact.updated_at)
    headers = {"HTTP_X_WIDGET_TOKEN": str(organization.api_token)}
    signature = hmac.new(b"s3cret", b"u1", hashlib.sha256).hexdigest()

    # The same person signs in again, then the old tab resumes with an email.
    signed = api_client.post(
        SESSION_URL,
        {
            "external_user_id": "u1",
            "user_hash": signature,
            "name": "Alice",
            "email": "alice@x.io",
        },
        format="json",
        **headers,
    )
    assert signed.status_code == 201
    resumed = api_client.post(
        SESSION_URL,
        {"session_id": str(old_session.id), "email": "alice@x.io", "name": "Alice"},
        format="json",
        **headers,
    )
    assert resumed.status_code == 200

    contact.refresh_from_db()
    assert (
        contact.email,
        contact.name,
        contact.external_id,
        contact.updated_at,
    ) == scrubbed
    assert not contact.sessions.exists()
    new_session = WidgetSession.objects.get(id=signed.data["session_id"])
    assert new_session.contact != contact
    # They don't get the old conversation back either.
    res = api_client.get(
        "/api/v1/tickets/widget_history/",
        HTTP_X_WIDGET_SESSION=str(new_session.id),
        **headers,
    )
    assert res.status_code == 200
    assert str(ticket.id) not in {row["id"] for row in res.data}


# Anonymization: the endpoint


def test_anonymize_endpoint_is_for_admins(
    authenticated_client, admin_client, organization
):
    contact = ContactFactory(organization=organization, name="Alice")
    url = _url(contact, "anonymize")
    assert authenticated_client.post(url).status_code == 403
    contact.refresh_from_db()
    assert contact.name == "Alice"
    res = admin_client.post(url)
    assert res.status_code == 200
    assert res.data["is_anonymized"] is True
    assert res.data["name"] == "Anonymized contact"
    assert res.data["tickets_count"] == 0


def test_anonymize_endpoint_is_idempotent(admin_client, organization):
    contact = ContactFactory(organization=organization)
    url = _url(contact, "anonymize")
    first = admin_client.post(url)
    second = admin_client.post(url)
    assert second.status_code == 200
    assert second.data["email"] == first.data["email"]
    assert second.data["updated_at"] == first.data["updated_at"]


def test_anonymize_endpoint_is_organization_scoped(admin_client):
    other = ContactFactory(organization=OrganizationFactory(), name="Alice")
    assert admin_client.post(_url(other, "anonymize")).status_code == 404
    other.refresh_from_db()
    assert other.name == "Alice"


def test_an_anonymized_contact_can_no_longer_be_written_to(admin_client, organization):
    contact = ContactFactory(organization=organization)
    admin_client.post(_url(contact, "anonymize"))
    res = admin_client.patch(
        f"/api/v1/contacts/{contact.id}/", {"name": "Bob"}, format="json"
    )
    assert res.status_code == 409


# Export: the archive


def _read_export(contact) -> tuple[dict, list, list]:
    with zipfile.ZipFile(io.BytesIO(build_contact_export(contact))) as archive:
        assert sorted(archive.namelist()) == [
            "contact.json",
            "tickets.csv",
            "tickets.json",
        ]
        rows = list(csv.reader(io.StringIO(archive.read("tickets.csv").decode())))
        return (
            json.loads(archive.read("contact.json")),
            json.loads(archive.read("tickets.json")),
            rows,
        )


def test_export_holds_the_profile(organization, agent):
    company = CompanyFactory(organization=organization, name="Acme")
    contact = ContactFactory(
        organization=organization,
        company=company,
        name="Alice",
        email="alice@x.io",
        declared_email="other@x.io",
        external_id="u1",
        attributes={"plan": "pro"},
    )
    ContactNoteFactory(contact=contact, author=agent, body="Prefers mornings")

    profile, _, _ = _read_export(contact)

    assert profile["name"] == "Alice"
    assert profile["email"] == "alice@x.io"
    assert profile["declared_email"] == "other@x.io"
    assert profile["external_id"] == "u1"
    assert profile["attributes"] == {"plan": "pro"}
    assert profile["company"] == "Acme"
    assert [note["body"] for note in profile["notes"]] == ["Prefers mornings"]
    # The agent's identity is about the agent.
    assert agent.email not in json.dumps(profile)


def test_export_holds_tickets_without_what_is_internal(organization, agent):
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        title="Printer on fire",
        context_metadata={"browser": "Chrome", "pre_login_session_hash": "abc"},
    )
    TicketMessageFactory(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        body="Please help",
    )
    reply = TicketMessageFactory(ticket=ticket, author=agent, body="On it")
    note = TicketMessageFactory(
        ticket=ticket,
        author=agent,
        message_type=TicketMessage.MessageType.INTERNAL_NOTE,
        body="This one is a pain",
    )
    TicketAttachmentFactory(
        ticket=ticket, message=reply, uploaded_by=agent, filename="manual.pdf"
    )
    TicketAttachmentFactory(ticket=ticket, uploaded_by=None, filename="photo.png")
    TicketAttachmentFactory(
        ticket=ticket, message=note, uploaded_by=agent, filename="internal.pdf"
    )
    VideoRecordingFactory(ticket=ticket, transcription="It burns")
    VideoRecordingFactory(ticket=ticket, recorded_by=agent, transcription="Agent talk")

    _, tickets, _ = _read_export(contact)

    assert len(tickets) == 1
    exported = tickets[0]
    assert exported["reference"] == ticket.reference
    assert exported["title"] == "Printer on fire"
    assert exported["context_metadata"] == {"browser": "Chrome"}
    assert [m["body"] for m in exported["messages"]] == ["Please help", "On it"]
    assert {a["filename"] for a in exported["attachments"]} == {
        "manual.pdf",
        "photo.png",
    }
    assert [v["transcription"] for v in exported["recordings"]] == ["It burns"]
    text = json.dumps(tickets)
    assert "This one is a pain" not in text
    assert "internal.pdf" not in text
    assert "Agent talk" not in text
    assert agent.email not in text


def test_export_is_scoped_to_the_contact_and_its_organization(organization):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=organization, requester=None, title="Someone else")
    TicketFactory(
        organization=OrganizationFactory(),
        contact=contact,
        requester=None,
        title="Another organization",
    )
    _, tickets, rows = _read_export(contact)
    assert tickets == []
    assert rows == [["reference", "title", "status", "created_at", "resolved_at"]]


def test_export_csv_lists_the_tickets(organization):
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        title='A "quoted", title',
    )
    _, _, rows = _read_export(contact)
    assert rows[0] == ["reference", "title", "status", "created_at", "resolved_at"]
    assert rows[1] == [
        ticket.reference,
        'A "quoted", title',
        "open",
        ticket.created_at.isoformat(),
        "",
    ]


@pytest.mark.parametrize(
    "title",
    ['=HYPERLINK("http://evil","x")', "+1+1", "-1+1", "@SUM(A1)", "\t=1", "\r=1"],
)
def test_export_csv_escapes_formulas(organization, title):
    contact = ContactFactory(organization=organization)
    TicketFactory(
        organization=organization, contact=contact, requester=None, title=title
    )
    _, tickets, rows = _read_export(contact)
    assert rows[1][1] == f"'{title}"
    assert tickets[0]["title"] == title  # JSON isn't opened by a spreadsheet.


def test_export_of_a_contact_without_data(organization):
    contact = ContactFactory(organization=organization)
    profile, tickets, _ = _read_export(contact)
    assert profile["notes"] == []
    assert tickets == []


# Export: the endpoint and the task


@pytest.fixture
def eager_celery(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_export_endpoint_emails_the_admin_a_zip(
    admin_client, admin_user, organization, eager_celery
):
    contact = ContactFactory(organization=organization, name="Alice O'Brien")
    res = admin_client.post(_url(contact, "export"))
    assert res.status_code == 202
    assert res.data == {"status": "queued"}
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [admin_user.email]
    assert message.subject == "Contact export ready"
    assert "Alice O'Brien" in message.body  # Plain text isn't HTML-escaped.
    ((name, content, mimetype),) = message.attachments
    assert name == f"contact-{contact.id}.zip"
    assert mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert json.loads(archive.read("contact.json"))["name"] == "Alice O'Brien"


def test_export_email_escapes_the_name_in_html(admin_user, organization):
    contact = ContactFactory(organization=organization, name="<b>Alice</b>")
    export_contact_data(str(contact.id), str(admin_user.id))
    html = mail.outbox[0].alternatives[0][0]
    assert "<b>Alice</b>" not in html
    assert "&lt;b&gt;Alice&lt;/b&gt;" in html


def test_export_endpoint_is_for_admins(
    authenticated_client, organization, eager_celery
):
    contact = ContactFactory(organization=organization)
    assert authenticated_client.post(_url(contact, "export")).status_code == 403
    assert mail.outbox == []


def test_export_endpoint_is_organization_scoped(admin_client, eager_celery):
    other = ContactFactory(organization=OrganizationFactory())
    assert admin_client.post(_url(other, "export")).status_code == 404
    assert mail.outbox == []


def test_export_task_skips_a_contact_deleted_since(admin_user, organization, caplog):
    contact = ContactFactory(organization=organization)
    contact_id = str(contact.id)
    contact.delete()
    export_contact_data(contact_id, str(admin_user.id))
    assert mail.outbox == []
    assert contact_id in caplog.text


def test_export_task_skips_a_requester_deleted_since(organization):
    contact = ContactFactory(organization=organization)
    user = UserFactory(organization=organization)
    user_id = str(user.id)
    user.delete()
    export_contact_data(str(contact.id), user_id)
    assert mail.outbox == []


def test_export_too_large_to_attach_tells_the_admin_instead(
    admin_user, organization, monkeypatch, caplog
):
    monkeypatch.setattr("apps.contacts.gdpr.MAX_EXPORT_ATTACHMENT_BYTES", 10)
    contact = ContactFactory(organization=organization, name="Alice")
    export_contact_data(str(contact.id), str(admin_user.id))
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [admin_user.email]
    assert message.subject == "Contact export too large"
    assert message.attachments == []
    assert "too large" in message.body
    assert str(contact.id) in caplog.text


def test_export_at_the_size_limit_is_still_sent(admin_user, organization, monkeypatch):
    contact = ContactFactory(organization=organization)
    size = len(build_contact_export(contact))
    monkeypatch.setattr("apps.contacts.gdpr.MAX_EXPORT_ATTACHMENT_BYTES", size)
    export_contact_data(str(contact.id), str(admin_user.id))
    assert mail.outbox[0].subject == "Contact export ready"


def test_export_task_retries_a_failed_email(admin_user, organization):
    contact = ContactFactory(organization=organization)
    with (
        mock.patch(
            "apps.contacts.tasks.send_branded_email", side_effect=OSError("smtp")
        ),
        mock.patch.object(
            export_contact_data, "retry", side_effect=RuntimeError("retried")
        ) as retry,
        pytest.raises(RuntimeError, match="retried"),
    ):
        export_contact_data(str(contact.id), str(admin_user.id))
    retry.assert_called_once()


# What a login leaves behind


def _sign(value: str) -> str:
    return hmac.new(b"s3cret", value.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def secret_org():
    return OrganizationFactory(widget_secret="s3cret")


def _login(api_client, organization, session, external_user_id="u1"):
    res = api_client.post(
        SESSION_URL,
        {
            "session_id": str(session.id),
            "external_user_id": external_user_id,
            "user_hash": _sign(external_user_id),
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
    )
    assert res.status_code in (200, 201), res.data
    return WidgetSession.objects.get(id=res.data["session_id"])


def _anonymous_session(organization, **kwargs) -> tuple[Contact, WidgetSession]:
    contact = ContactFactory(organization=organization, email="alice@x.io", **kwargs)
    session = WidgetSession.objects.create(
        organization=organization,
        contact=contact,
        email="alice@x.io",
        name="Alice",
        user_agent="Mozilla/5.0",
        email_verified_at=None,
    )
    return contact, session


def test_login_blanks_the_session_it_leaves_behind(api_client, secret_org):
    _, session = _anonymous_session(secret_org)
    WidgetSession.objects.filter(pk=session.pk).update(email_verified_at=timezone.now())
    res = api_client.post(
        SESSION_URL,
        {
            "session_id": str(session.id),
            "external_user_id": "u1",
            "user_hash": _sign("u1"),
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=str(secret_org.api_token),
    )
    assert res.status_code == 201
    session.refresh_from_db()
    assert (session.name, session.email, session.user_agent) == ("", "", "")
    assert session.email_verified_at is None
    assert session.contact is None


def test_login_deletes_the_email_only_contact_left_empty(api_client, secret_org):
    contact, session = _anonymous_session(secret_org)
    ticket = TicketFactory(
        organization=secret_org,
        contact=contact,
        requester=None,
        widget_session=session,
    )
    identified = _login(api_client, secret_org, session)
    ticket.refresh_from_db()
    assert ticket.contact == identified.contact
    assert not Contact.objects.filter(pk=contact.pk).exists()


def test_login_deletes_a_contact_only_a_moved_ticket_was_on(api_client, secret_org):
    """The session may have changed contact since it wrote the ticket."""
    previous = ContactFactory(organization=secret_org, email="previous@x.io")
    _, session = _anonymous_session(secret_org)
    TicketFactory(
        organization=secret_org,
        contact=previous,
        requester=None,
        widget_session=session,
    )
    _login(api_client, secret_org, session)
    assert not Contact.objects.filter(pk=previous.pk).exists()


@pytest.mark.parametrize(
    "fields",
    [
        {"phone": "+33"},
        {"job_title": "CTO"},
        {"avatar_url": "https://x.io/a.png"},
        {"locale": "fr"},
        {"timezone": "Europe/Paris"},
        {"attributes": {"plan": "pro"}},
        {"is_unsubscribed": True},
        {"external_id": "other"},
    ],
    ids=lambda fields: next(iter(fields)),
)
def test_login_keeps_a_left_contact_holding_data_of_its_own(
    api_client, secret_org, fields
):
    contact, session = _anonymous_session(secret_org, **fields)
    _login(api_client, secret_org, session)
    assert Contact.objects.filter(pk=contact.pk).exists()


def test_login_keeps_a_left_contact_with_notes(api_client, secret_org):
    contact, session = _anonymous_session(secret_org)
    ContactNoteFactory(contact=contact, body="Call back")
    _login(api_client, secret_org, session)
    assert contact.notes.exists()


def test_login_keeps_a_left_contact_with_another_session(api_client, secret_org):
    contact, session = _anonymous_session(secret_org)
    other = WidgetSession.objects.create(organization=secret_org, contact=contact)
    _login(api_client, secret_org, session)
    other.refresh_from_db()
    assert other.contact == contact


def test_login_keeps_a_left_contact_with_another_ticket(api_client, secret_org):
    contact, session = _anonymous_session(secret_org)
    other = TicketFactory(organization=secret_org, contact=contact, requester=None)
    _login(api_client, secret_org, session)
    other.refresh_from_db()
    assert other.contact == contact


def test_login_keeps_the_contact_when_the_tickets_cant_move_to_another(
    api_client, secret_org
):
    contact, session = _anonymous_session(secret_org)
    ticket = TicketFactory(
        organization=secret_org,
        contact=contact,
        requester=None,
        widget_session=session,
    )
    # An anonymized contact holds this id: the identified session gets no contact.
    gone = ContactFactory(organization=secret_org, external_id="u1")
    anonymize_contact(gone)
    Contact.objects.filter(pk=gone.pk).update(external_id="u1")

    identified = _login(api_client, secret_org, session)

    assert identified.contact is None
    ticket.refresh_from_db()
    assert ticket.contact == contact


def test_login_keeps_the_contact_the_identified_session_attached_to(
    api_client, secret_org
):
    contact, session = _anonymous_session(secret_org)
    res = api_client.post(
        SESSION_URL,
        {
            "session_id": str(session.id),
            "external_user_id": "u1",
            "user_hash": _sign("u1"),
            "email": "alice@x.io",
            "email_hash": _sign("email:alice@x.io"),
        },
        format="json",
        HTTP_X_WIDGET_TOKEN=str(secret_org.api_token),
    )
    identified = WidgetSession.objects.get(id=res.data["session_id"])
    assert identified.contact == contact
    contact.refresh_from_db()
    assert contact.external_id == "u1"


def test_login_survives_a_contact_it_cant_delete(api_client, secret_org, caplog):
    contact, session = _anonymous_session(secret_org)
    with mock.patch(
        "apps.tickets.views.delete_contact_if_left_empty",
        side_effect=DatabaseError("deadlock"),
    ):
        identified = _login(api_client, secret_org, session)
    assert identified.external_user_id == "u1"
    assert Contact.objects.filter(pk=contact.pk).exists()
    assert "alice@x.io" not in caplog.text


# Anonymization: tickets that no longer point at the contact


def test_anonymize_scrubs_tickets_an_agent_unlinked_from_the_contact(
    organization, media, django_capture_on_commit_callbacks
):
    contact = ContactFactory(organization=organization, email="alice@x.io")
    session = WidgetSession.objects.create(organization=organization, contact=contact)
    cleared = TicketFactory(
        organization=organization,
        contact=None,
        requester=None,
        widget_session=session,
        title="Alice's invoice",
        description="My card is 4242",
        requester_email="alice@x.io",
        requester_name="Alice",
        context_url="https://app/x",
    )
    message = TicketMessageFactory(
        ticket=cleared,
        author=None,
        widget_session=session,
        sender_type=TicketMessage.SenderType.USER,
        body="secret",
    )
    upload = TicketAttachmentFactory(ticket=cleared, uploaded_by=None, file=_file())
    path = media / upload.file.name

    with django_capture_on_commit_callbacks(execute=True):
        anonymize_contact(contact)

    contact.refresh_from_db()
    cleared.refresh_from_db()
    message.refresh_from_db()
    assert cleared.widget_session is None
    assert cleared.contact is None
    assert (cleared.title, cleared.description) == (REMOVED_TITLE, REMOVED_BODY)
    assert cleared.requester_email == contact.email
    assert cleared.context_url == ""
    assert message.body == REMOVED_BODY
    assert message.widget_session is None
    assert not TicketAttachment.objects.filter(pk=upload.pk).exists()
    assert not path.exists()


def test_anonymize_leaves_another_contacts_ticket_on_the_same_session(organization):
    contact = ContactFactory(organization=organization)
    other = ContactFactory(organization=organization)
    session = WidgetSession.objects.create(organization=organization, contact=contact)
    ticket = TicketFactory(
        organization=organization,
        contact=other,
        requester=None,
        widget_session=session,
        title="Kept",
    )
    anonymize_contact(contact)
    ticket.refresh_from_db()
    assert ticket.title == "Kept"


def test_anonymize_scrubs_unlinked_tickets_naming_its_external_id(organization):
    """``widget_submit`` takes any external id, unsigned, and links nothing."""
    contact = ContactFactory(organization=organization, external_id="u1")
    named = TicketFactory(
        organization=organization,
        contact=None,
        requester=None,
        external_user_id="u1",
        title="Alice's invoice",
    )
    linked_elsewhere = TicketFactory(
        organization=organization,
        contact=ContactFactory(organization=organization),
        requester=None,
        external_user_id="u1",
        title="Kept",
    )
    other_org = TicketFactory(
        organization=OrganizationFactory(),
        contact=None,
        requester=None,
        external_user_id="u1",
        title="Kept",
    )

    anonymize_contact(contact)

    for ticket in (named, linked_elsewhere, other_org):
        ticket.refresh_from_db()
    assert named.title == REMOVED_TITLE
    assert named.external_user_id == ""
    assert linked_elsewhere.title == "Kept"
    assert linked_elsewhere.external_user_id == "u1"
    assert other_org.title == "Kept"


def test_anonymizing_a_contact_without_external_id_spares_tickets_without_one(
    organization,
):
    contact = ContactFactory(organization=organization, external_id="")
    ticket = TicketFactory(
        organization=organization,
        contact=None,
        requester=None,
        external_user_id="",
        title="Kept",
    )
    anonymize_contact(contact)
    ticket.refresh_from_db()
    assert ticket.title == "Kept"


# Anonymization: details


def test_anonymize_clears_the_last_contact_date(organization):
    contact = ContactFactory(
        organization=organization, last_contacted_at=timezone.now()
    )
    anonymize_contact(contact)
    contact.refresh_from_db()
    assert contact.last_contacted_at is None


def test_anonymize_keeps_whitelisted_metadata_only_if_harmless(organization):
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization,
        contact=contact,
        requester=None,
        context_metadata={
            "language": "fr",
            "timezone": "alice@x.io",
            "browser": {"name": "Chrome"},
            "os": "x" * 101,
            "screen_resolution": "1920x1080",
            "custom": "secret",
        },
    )
    anonymize_contact(contact)
    ticket.refresh_from_db()
    assert ticket.context_metadata == {
        "language": "fr",
        "screen_resolution": "1920x1080",
    }


def test_anonymize_scrubs_messages_by_the_requester_whatever_their_sender_type(
    organization, agent
):
    requester = EndUserFactory(organization=organization)
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=requester
    )
    by_requester = TicketMessageFactory(
        ticket=ticket,
        author=requester,
        sender_type=TicketMessage.SenderType.AGENT,
        body="secret",
    )
    by_agent = TicketMessageFactory(
        ticket=ticket,
        author=agent,
        sender_type=TicketMessage.SenderType.AGENT,
        body="reply",
    )
    system = TicketMessageFactory(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.SYSTEM,
        body="Reopened",
    )
    anonymize_contact(contact)
    for message in (by_requester, by_agent, system):
        message.refresh_from_db()
    assert by_requester.body == REMOVED_BODY
    assert by_agent.body == "reply"
    assert system.body == "Reopened"


@pytest.mark.parametrize("role", ["agent", "admin"])
def test_anonymize_keeps_what_a_requester_who_is_staff_uploaded_and_wrote(
    organization, media, role
):
    """An agent filed the ticket for the contact: their work isn't the contact's."""
    requester = UserFactory(organization=organization, role=role)
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=requester
    )
    upload = TicketAttachmentFactory(ticket=ticket, uploaded_by=requester, file=_file())
    video = VideoRecordingFactory(
        ticket=ticket, recorded_by=requester, original_file=_file("a.webm")
    )
    reply = TicketMessageFactory(
        ticket=ticket,
        author=requester,
        sender_type=TicketMessage.SenderType.AGENT,
        body="reply",
    )
    anonymize_contact(contact)
    reply.refresh_from_db()
    assert reply.body == "reply"
    assert TicketAttachment.objects.filter(pk=upload.pk).exists()
    assert VideoRecording.objects.filter(pk=video.pk).exists()


def test_anonymize_deletes_what_a_requester_who_is_staff_elsewhere_uploaded(
    organization, media
):
    requester = UserFactory(organization=OrganizationFactory(), role="agent")
    orphan = UserFactory(organization=None, role="end_user")
    contact = ContactFactory(organization=organization)
    uploads = [
        TicketAttachmentFactory(
            ticket=TicketFactory(
                organization=organization, contact=contact, requester=user
            ),
            uploaded_by=user,
            file=_file(),
        )
        for user in (requester, orphan)
    ]
    anonymize_contact(contact)
    assert not TicketAttachment.objects.filter(
        pk__in=[upload.pk for upload in uploads]
    ).exists()


def test_a_row_added_while_collecting_uploads_keeps_its_file(organization, media):
    """Only what got collected goes: its row can't go without its file."""
    contact = ContactFactory(organization=organization)
    ticket = TicketFactory(organization=organization, contact=contact, requester=None)
    late = []

    def add_rows(files):
        late.append(TicketAttachmentFactory(ticket=ticket, uploaded_by=None))
        late.append(VideoRecordingFactory(ticket=ticket))

    with mock.patch("apps.contacts.gdpr._delete_files_after_commit", add_rows):
        anonymize_contact(contact)

    attachment, video = late
    assert TicketAttachment.objects.filter(pk=attachment.pk).exists()
    assert VideoRecording.objects.filter(pk=video.pk).exists()
