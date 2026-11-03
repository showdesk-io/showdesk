"""What agents and admins manage of the email channel: mailboxes, their log, mails."""

from unittest import mock

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from apps.email_channel.models import InboundEmail, Mailbox
from apps.tickets.models import TicketMessage
from tests.email_channel.mails import INBOUND_DOMAIN
from tests.factories import (
    AdminFactory,
    InboundEmailFactory,
    MailboxFactory,
    OrganizationFactory,
    TeamFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]

RAW = b"From: ann@example.org\r\nSubject: Printer on fire\r\n\r\nIt burns."


def client_for(user, org=None) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    if org is not None:
        client.credentials(HTTP_X_SHOWDESK_ORG=str(org.id))
    return client


@pytest.fixture
def delay():
    with mock.patch("apps.email_channel.tasks.process_inbound_email.delay") as delay:
        yield delay


@pytest.fixture
def mailbox(organization):
    return MailboxFactory(organization=organization, name="Support")


@pytest.fixture
def stranger():
    """An admin of another organization."""
    return client_for(AdminFactory(organization=OrganizationFactory()))


def _emailed_message(organization, raw=RAW) -> TicketMessage:
    ticket = TicketFactory(organization=organization, requester=None)
    message = TicketMessageFactory(
        ticket=ticket,
        author=None,
        sender_type=TicketMessage.SenderType.USER,
        channel=TicketMessage.Channel.EMAIL,
        external_sender='"Ann" <ann@example.org>',
    )
    inbound = InboundEmailFactory(
        mailbox=MailboxFactory(organization=organization),
        ticket=ticket,
        ticket_message=message,
        status=InboundEmail.Status.PROCESSED,
    )
    if raw:
        inbound.raw.save("raw.eml", ContentFile(raw))
    return message


def _original_url(message: TicketMessage) -> str:
    return f"/api/v1/tickets/{message.ticket_id}/messages/{message.id}/original/"


class TestMailboxes:
    def test_agents_read_and_admins_write(
        self, authenticated_client, admin_client, organization
    ):
        team = TeamFactory(organization=organization)

        refused = authenticated_client.post(
            "/api/v1/mailboxes/", {"name": "Support"}, format="json"
        )
        created = admin_client.post(
            "/api/v1/mailboxes/",
            {
                "name": "Support",
                "public_address": "Support@Acme.example.com",
                "default_team": str(team.id),
                "local_part": "chosen",
            },
            format="json",
        )

        assert refused.status_code == 403
        assert created.status_code == 201, created.data
        mailbox = Mailbox.objects.get(organization=organization)
        assert mailbox.local_part != "chosen"
        assert created.data["public_address"] == "support@acme.example.com"
        assert (
            created.data["inbound_address"] == f"{mailbox.local_part}@{INBOUND_DOMAIN}"
        )
        listed = authenticated_client.get("/api/v1/mailboxes/")
        assert [row["id"] for row in listed.data] == [str(mailbox.id)]

    def test_what_the_model_refuses_is_a_clear_400(
        self, admin_client, mailbox, organization
    ):
        MailboxFactory(public_address="billing@acme.example.com")
        url = f"/api/v1/mailboxes/{mailbox.id}/"

        taken = admin_client.patch(
            url, {"public_address": "BILLING@acme.example.com"}, format="json"
        )
        inbound = admin_client.patch(
            url, {"public_address": f"x@{INBOUND_DOMAIN}"}, format="json"
        )
        foreign_team = admin_client.patch(
            url, {"default_team": str(TeamFactory().id)}, format="json"
        )

        assert taken.status_code == 400
        assert "public_address" in taken.data
        assert inbound.status_code == 400
        assert "public_address" in inbound.data
        assert foreign_team.status_code == 400
        assert "default_team" in foreign_team.data
        mailbox.refresh_from_db()
        assert mailbox.public_address == ""

    def test_regenerating_the_address_is_for_admins(
        self, authenticated_client, admin_client, mailbox
    ):
        url = f"/api/v1/mailboxes/{mailbox.id}/regenerate-address/"
        before = mailbox.local_part

        assert authenticated_client.post(url).status_code == 403
        response = admin_client.post(url)

        assert response.status_code == 200
        mailbox.refresh_from_db()
        assert mailbox.local_part != before
        assert response.data["local_part"] == mailbox.local_part

    def test_the_forwarding_confirmation_is_shown_to_admins_only(
        self, authenticated_client, admin_client, mailbox
    ):
        mailbox.forwarding_confirmation = {
            "url": "https://mail.google.com/x",
            "code": "123456789",
            "detected_at": "2026-11-03T10:00:00+00:00",
        }
        mailbox.save()
        url = f"/api/v1/mailboxes/{mailbox.id}/"

        assert admin_client.get(url).data["forwarding_confirmation"]["code"]
        assert "forwarding_confirmation" not in authenticated_client.get(url).data

    def test_another_organization_sees_and_touches_nothing(self, stranger, mailbox):
        url = f"/api/v1/mailboxes/{mailbox.id}/"

        assert stranger.get("/api/v1/mailboxes/").data == []
        assert stranger.get(url).status_code == 404
        assert stranger.patch(url, {"name": "Mine"}, format="json").status_code == 404
        assert stranger.post(f"{url}regenerate-address/").status_code == 404
        assert stranger.get(f"{url}inbound/").status_code == 404

    def test_a_superuser_works_in_the_organization_impersonated(
        self, organization, mailbox
    ):
        superuser = UserFactory(organization=None, is_superuser=True, is_staff=True)

        inside = client_for(superuser, organization).get("/api/v1/mailboxes/")
        unknown = client_for(superuser).get(
            "/api/v1/mailboxes/", HTTP_X_SHOWDESK_ORG="nope"
        )

        assert [row["id"] for row in inside.data] == [str(mailbox.id)]
        assert unknown.status_code == 400

    def test_mailboxes_are_not_deleted_but_deactivated(self, admin_client, mailbox):
        # Deleting one would delete its log of received mails with it.
        url = f"/api/v1/mailboxes/{mailbox.id}/"

        assert admin_client.delete(url).status_code == 405
        assert (
            admin_client.patch(url, {"is_active": False}, format="json").data[
                "is_active"
            ]
            is False
        )


class TestInboundLog:
    def test_lists_what_did_not_become_a_message_newest_first(
        self, authenticated_client, mailbox
    ):
        InboundEmailFactory(mailbox=mailbox, status=InboundEmail.Status.PROCESSED)
        InboundEmailFactory(mailbox=mailbox, status=InboundEmail.Status.PENDING)
        ignored = InboundEmailFactory(
            mailbox=mailbox, status=InboundEmail.Status.IGNORED, reason="auto_reply"
        )
        failed = InboundEmailFactory(
            mailbox=mailbox, status=InboundEmail.Status.FAILED, reason="exception"
        )
        InboundEmailFactory(status=InboundEmail.Status.IGNORED)  # Another mailbox.

        response = authenticated_client.get(f"/api/v1/mailboxes/{mailbox.id}/inbound/")

        assert response.status_code == 200
        assert [row["id"] for row in response.data["results"]] == [
            str(failed.id),
            str(ignored.id),
        ]
        assert response.data["results"][1]["reason"] == "auto_reply"


class TestReplay:
    @pytest.fixture
    def failed(self, mailbox):
        return InboundEmailFactory(
            mailbox=mailbox, status=InboundEmail.Status.FAILED, reason="exception"
        )

    def url(self, inbound) -> str:
        return f"/api/v1/inbound-emails/{inbound.id}/replay/"

    def test_queues_a_failed_mail_once(
        self, admin_client, failed, delay, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            first = admin_client.post(self.url(failed))
            second = admin_client.post(self.url(failed))

        assert first.status_code == 202
        assert second.status_code == 409
        assert delay.call_args_list == [mock.call(str(failed.id))]
        failed.refresh_from_db()
        assert failed.status == InboundEmail.Status.PENDING

    def test_only_failed_mails_and_only_by_admins(
        self, authenticated_client, admin_client, failed, mailbox, delay
    ):
        ignored = InboundEmailFactory(
            mailbox=mailbox, status=InboundEmail.Status.IGNORED
        )

        assert authenticated_client.post(self.url(failed)).status_code == 403
        assert admin_client.post(self.url(ignored)).status_code == 409
        delay.assert_not_called()

    def test_not_on_another_organizations_mail(self, stranger, failed, delay):
        assert stranger.post(self.url(failed)).status_code == 404
        failed.refresh_from_db()
        assert failed.status == InboundEmail.Status.FAILED
        delay.assert_not_called()


class TestOriginalMail:
    def test_agents_download_it_as_an_attachment(
        self, authenticated_client, organization
    ):
        message = _emailed_message(organization)

        response = authenticated_client.get(_original_url(message))

        assert response.status_code == 200
        assert response["Content-Type"] == "message/rfc822"
        assert response["Content-Disposition"].startswith("attachment;")
        assert response["X-Content-Type-Options"] == "nosniff"
        assert b"".join(response.streaming_content) == RAW

    def test_not_in_another_organization_nor_through_another_ticket(
        self, stranger, authenticated_client, organization
    ):
        message = _emailed_message(organization)
        other_ticket = TicketFactory(organization=organization, requester=None)

        assert stranger.get(_original_url(message)).status_code == 404
        wrong_ticket = (
            f"/api/v1/tickets/{other_ticket.id}/messages/{message.id}/original/"
        )
        assert authenticated_client.get(wrong_ticket).status_code == 404

    def test_a_purged_mail_is_gone(self, authenticated_client, organization):
        message = _emailed_message(organization, raw=None)

        assert authenticated_client.get(_original_url(message)).status_code == 404


def test_no_payload_gives_a_url_to_a_raw_mail(
    authenticated_client, admin_client, organization
):
    message = _emailed_message(organization)
    inbound = message.inbound_emails.get()
    InboundEmail.objects.filter(pk=inbound.pk).update(status=InboundEmail.Status.FAILED)
    payloads = [
        admin_client.get("/api/v1/mailboxes/"),
        admin_client.get(f"/api/v1/mailboxes/{inbound.mailbox_id}/inbound/"),
        authenticated_client.get(f"/api/v1/tickets/{message.ticket_id}/"),
    ]

    for response in payloads:
        assert response.status_code == 200
        assert inbound.raw.name not in response.content.decode()
        assert "inbound-emails/" not in response.content.decode()


def test_messages_tell_their_channel_and_delivery(authenticated_client, organization):
    message = _emailed_message(organization)
    TicketMessage.objects.filter(pk=message.pk).update(
        email_delivery_status=TicketMessage.DeliveryStatus.FAILED
    )

    response = authenticated_client.get(f"/api/v1/tickets/{message.ticket_id}/")

    (shown,) = response.data["messages"]
    assert shown["channel"] == "email"
    assert shown["external_sender"] == '"Ann" <ann@example.org>'
    assert shown["email_delivery_status"] == "failed"
    assert "mailbox" in response.data


def test_the_organization_says_whether_the_channel_is_on(
    authenticated_client, settings
):
    on = authenticated_client.get("/api/v1/organizations/").data["results"][0]
    settings.INBOUND_EMAIL_DOMAIN = ""
    off = authenticated_client.get("/api/v1/organizations/").data["results"][0]

    assert on["inbound_email_enabled"] is True
    assert on["inbound_email_domain"] == INBOUND_DOMAIN
    assert off["inbound_email_enabled"] is False
    assert off["inbound_email_domain"] == ""
