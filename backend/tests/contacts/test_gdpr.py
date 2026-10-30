"""Anonymization and export of a contact."""

import hashlib
import hmac
from unittest import mock

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from apps.contacts.gdpr import REMOVED_BODY, REMOVED_TITLE, anonymize_contact
from apps.contacts.models import Contact
from apps.contacts.services import resolve_contact_for_widget_session
from apps.tickets.models import TicketAttachment, TicketMessage, WidgetSession
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


def test_anonymize_is_idempotent(organization):
    contact = ContactFactory(organization=organization, email="a@x.io")
    anonymize_contact(contact)
    contact.refresh_from_db()
    first = (contact.email, contact.updated_at)
    # Written after the anonymization: a second one has no business touching it.
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=None, title="Kept"
    )

    anonymize_contact(contact)

    contact.refresh_from_db()
    ticket.refresh_from_db()
    assert (contact.email, contact.updated_at) == first
    assert ticket.title == "Kept"


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
