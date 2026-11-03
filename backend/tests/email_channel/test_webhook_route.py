"""Only signed provider webhooks reach the inbound pipeline."""

import base64
import io
from email.message import EmailMessage
from unittest import mock

import pytest
from django.conf import settings as django_settings
from django.core.handlers.asgi import ASGIRequest
from django.test import Client

from apps.email_channel.models import InboundEmail
from apps.email_channel.webhooks import PostalInboundView
from tests.email_channel.postal import (
    POSTAL_URL,
    new_postal_key,
    post_to_postal,
    postal_payload,
)

# The inbound signal stores what it receives.
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]


def _mail(body: str = "Hello", **headers: str) -> bytes:
    message = EmailMessage()
    message["From"] = "customer@example.org"
    message["To"] = "support@example.com"
    message["Subject"] = "Help"
    message["Message-ID"] = "<1@example.org>"
    for name, value in headers.items():
        del message[name]
        message[name] = value
    message.set_content(body)
    return message.as_bytes()


def test_a_signed_mail_is_accepted(postal_key, received):
    response = post_to_postal(
        postal_payload(_mail(Subject="Printer on fire")), postal_key
    )
    assert response.status_code == 200
    [event] = received
    assert event.message["Subject"] == "Printer on fire"
    assert event.message.envelope_recipient == "acme-abc@in.example.com"
    assert InboundEmail.objects.get().subject == "Printer on fire"


def test_postal_s_spam_header_is_its_verdict(postal_key, received):
    post_to_postal(postal_payload(_mail(**{"X-Postal-Spam": "yes"})), postal_key)
    post_to_postal(
        postal_payload(_mail(**{"Message-ID": "<2@example.org>"})), postal_key
    )

    assert [event.message.spam_detected for event in received] == [True, None]


def test_a_forged_signature_is_refused(postal_key, received):
    response = post_to_postal(postal_payload(_mail()), new_postal_key())
    assert response.status_code == 400
    assert received == []


def test_other_providers_are_only_mounted_with_a_secret(postal_key, mount, settings):
    # Without a shared secret, Anymail's views for basic-auth providers accept anyone.
    assert Client().post("/anymail/mailjet/inbound/").status_code == 404

    mount(ANYMAIL={**settings.ANYMAIL, "WEBHOOK_SECRET": [" ", "", "no-colon", ":"]})
    assert Client().post("/anymail/mailjet/inbound/").status_code == 404

    mount(ANYMAIL={**settings.ANYMAIL, "WEBHOOK_SECRET": ["user:password"]})
    assert Client().post("/anymail/mailjet/inbound/").status_code == 400


def test_basic_auth_does_not_replace_postal_s_signature(postal_key, mount, received):
    secret = "user:password"
    mount(ANYMAIL={**django_settings.ANYMAIL, "WEBHOOK_SECRET": [secret]})
    credentials = base64.b64encode(secret.encode()).decode()

    response = Client().post(
        POSTAL_URL,
        data=postal_payload(_mail()),
        content_type="application/json",
        headers={"Authorization": f"Basic {credentials}"},
    )

    assert response.status_code == 400
    assert received == []


def test_a_latin1_mail_is_accepted(postal_key, received):
    raw = (
        b"From: customer@example.org\r\n"
        b"To: support@example.com\r\n"
        b"Subject: =?iso-8859-1?q?Caf=E9?=\r\n"
        b"Message-ID: <2@example.org>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=iso-8859-1\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n"
        b"\r\n"
        b"Un caf\xe9, s'il vous pla\xeet.\r\n"
    )
    response = post_to_postal(postal_payload(raw), postal_key)
    assert response.status_code == 200
    [event] = received
    assert event.message["Subject"] == "Café"
    assert "Un café, s'il vous plaît." in event.message.text


def test_a_mail_over_the_default_upload_limit_is_accepted(postal_key, received):
    body = "x" * 76 + "\n"
    response = post_to_postal(
        postal_payload(_mail(body * (5 * 1024 * 1024 // 77))), postal_key
    )
    assert response.status_code == 200
    assert len(received) == 1


def test_a_mail_over_the_cap_is_refused_before_reading(postal_key, received, settings):
    settings.INBOUND_EMAIL_MAX_SIZE_MB = 1
    body = "x" * 76 + "\n"
    response = post_to_postal(
        postal_payload(_mail(body * (3 * 1024 * 1024 // 77))), postal_key
    )
    assert response.status_code == 413
    assert received == []


def test_a_body_over_the_cap_without_content_length_is_refused(
    postal_key, received, settings
):
    # Over ASGI, a chunked request has no Content-Length: only reading tells.
    settings.INBOUND_EMAIL_MAX_SIZE_MB = 1
    body = postal_payload(_mail(("x" * 76 + "\n") * 40_000))
    scope = {
        "type": "http",
        "method": "POST",
        "path": POSTAL_URL,
        "headers": [(b"content-type", b"application/json")],
    }
    request = ASGIRequest(scope, io.BytesIO(body))
    assert "CONTENT_LENGTH" not in request.META

    with mock.patch("apps.email_channel.webhooks.logger") as logger:
        response = PostalInboundView.as_view()(request)

    assert response.status_code == 413
    logger.warning.assert_called_once()
    assert received == []


def test_the_route_is_absent_when_the_channel_is_off(postal_key, mount, received):
    mount(INBOUND_EMAIL_DOMAIN="")
    assert post_to_postal(postal_payload(_mail()), postal_key).status_code == 404
    assert received == []
