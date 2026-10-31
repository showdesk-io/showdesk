"""Uploading a video from the widget, authenticated by an organization's token."""

from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests.factories import OrganizationFactory, TicketFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/videos/widget_upload/"
UNKNOWN_TICKET_ID = "00000000-0000-4000-8000-000000000000"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    """Local files, as the default storage needs an S3 server."""
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path)},
        },
    }


@pytest.fixture(autouse=True)
def process_video():
    with mock.patch("apps.videos.views.process_video") as task:
        yield task


def _upload(api_client, organization, ticket_id: str):
    return api_client.post(
        URL,
        {
            "ticket": ticket_id,
            "original_file": SimpleUploadedFile(
                "a.webm", b"x", content_type="video/webm"
            ),
            "mime_type": "video/webm",
        },
        format="multipart",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
    )


def test_uploads_on_a_ticket_of_the_tokens_organization(
    api_client, organization, process_video
):
    ticket = TicketFactory(organization=organization)
    res = _upload(api_client, organization, str(ticket.id))
    assert res.status_code == 201
    video = ticket.videos.get()
    assert video.expires_at is not None
    process_video.delay.assert_called_once_with(str(video.id))


def test_another_organizations_ticket_reads_as_an_unknown_ticket(
    api_client, organization, process_video
):
    ticket = TicketFactory(organization=OrganizationFactory())

    other = _upload(api_client, organization, str(ticket.id))
    unknown = _upload(api_client, organization, UNKNOWN_TICKET_ID)

    assert other.status_code == unknown.status_code == 400
    assert {
        field: [
            str(error).replace(str(ticket.id), UNKNOWN_TICKET_ID) for error in errors
        ]
        for field, errors in other.data.items()
    } == {
        field: [str(error) for error in errors]
        for field, errors in unknown.data.items()
    }
    assert not ticket.videos.exists()
    process_video.delay.assert_not_called()
