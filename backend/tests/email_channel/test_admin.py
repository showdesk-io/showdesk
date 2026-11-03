"""The admin of the email channel."""

from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from apps.email_channel.models import InboundEmail
from tests.factories import InboundEmailFactory, UserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]


@pytest.fixture
def superuser_client(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def test_inbound_emails_cannot_be_added_by_hand(superuser_client):
    # They are what a provider delivered: one made up would pass for a real mail.
    response = superuser_client.get(reverse("admin:email_channel_inboundemail_add"))

    assert response.status_code == 403


def test_the_admin_never_links_to_a_raw_mail(superuser_client):
    inbound = InboundEmailFactory()
    inbound.raw.save("raw.eml", ContentFile(b"Subject: Hi\r\n\r\nHi"))

    pages = [
        superuser_client.get(reverse("admin:email_channel_inboundemail_changelist")),
        superuser_client.get(
            reverse("admin:email_channel_inboundemail_change", args=[inbound.pk])
        ),
    ]

    for page in pages:
        assert page.status_code == 200
        assert inbound.raw.name not in page.content.decode()


def test_replays_the_selected_failed_mails_once(
    superuser_client, django_capture_on_commit_callbacks
):
    failed = InboundEmailFactory(mailbox=None, status=InboundEmail.Status.FAILED)
    ignored = InboundEmailFactory(status=InboundEmail.Status.IGNORED)

    with (
        mock.patch("apps.email_channel.tasks.process_inbound_email.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = superuser_client.post(
            reverse("admin:email_channel_inboundemail_changelist"),
            {
                "action": "replay_failed",
                "_selected_action": [str(failed.pk), str(ignored.pk)],
            },
            follow=True,
        )

    assert response.status_code == 200
    assert delay.call_args_list == [mock.call(str(failed.pk))]
    assert "1 failed mail queued again" in response.content.decode()
    ignored.refresh_from_db()
    assert ignored.status == InboundEmail.Status.IGNORED
