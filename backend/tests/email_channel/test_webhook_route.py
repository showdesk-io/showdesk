"""Only signed provider webhooks reach the inbound pipeline."""

import base64
import importlib
import io
import json
from email.message import EmailMessage
from unittest import mock

import pytest
from anymail.signals import inbound
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.core.handlers.asgi import ASGIRequest
from django.test import Client, override_settings
from django.urls import clear_url_caches

from apps.email_channel.models import InboundEmail
from apps.email_channel.webhooks import PostalInboundView

POSTAL_URL = "/anymail/postal/inbound/"
# The inbound signal stores what it receives.
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _public_key_setting(key: rsa.RSAPrivateKey) -> str:
    """The public key as Postal shows it: the PEM body, without its frame."""
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return "".join(pem.decode().strip().splitlines()[1:-1])


def _reload_urls() -> None:
    importlib.reload(importlib.import_module("config.urls"))
    clear_url_caches()


@pytest.fixture
def mount():
    """Rebuild the URLs under settings: which webhooks exist is decided at import."""
    overrides = []

    def _mount(**settings) -> None:
        override = override_settings(**settings)
        override.enable()
        overrides.append(override)
        _reload_urls()

    yield _mount
    for override in reversed(overrides):
        override.disable()
    _reload_urls()


@pytest.fixture
def received():
    """The events of the ``inbound`` signal."""
    events = []

    def receiver(sender, event, esp_name, **kwargs) -> None:
        events.append(event)

    inbound.connect(receiver)
    yield events
    inbound.disconnect(receiver)


@pytest.fixture
def postal_key(mount, settings) -> rsa.RSAPrivateKey:
    key = _new_key()
    mount(
        INBOUND_EMAIL_DOMAIN="in.example.com",
        ANYMAIL={**settings.ANYMAIL, "POSTAL_WEBHOOK_KEY": _public_key_setting(key)},
    )
    return key


def _payload(raw: bytes) -> bytes:
    return json.dumps(
        {
            "id": 1,
            "rcpt_to": "acme-abc@in.example.com",
            "mail_from": "customer@example.org",
            "message": base64.b64encode(raw).decode(),
            "base64": True,
            "size": len(raw),
        }
    ).encode()


def _post(body: bytes, key: rsa.RSAPrivateKey):
    signature = key.sign(body, padding.PKCS1v15(), hashes.SHA1())
    # CSRF checks on, as for a real provider: the view must be exempt.
    return Client(enforce_csrf_checks=True).post(
        POSTAL_URL,
        data=body,
        content_type="application/json",
        headers={"X-Postal-Signature": base64.b64encode(signature).decode()},
    )


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
    response = _post(_payload(_mail(Subject="Printer on fire")), postal_key)
    assert response.status_code == 200
    [event] = received
    assert event.message["Subject"] == "Printer on fire"
    assert event.message.envelope_recipient == "acme-abc@in.example.com"
    assert InboundEmail.objects.get().subject == "Printer on fire"


def test_a_forged_signature_is_refused(postal_key, received):
    response = _post(_payload(_mail()), _new_key())
    assert response.status_code == 400
    assert received == []


def test_other_providers_are_only_mounted_with_a_secret(postal_key, mount, settings):
    # Without a shared secret, Anymail's views for basic-auth providers accept anyone.
    assert Client().post("/anymail/mailjet/inbound/").status_code == 404

    mount(ANYMAIL={**settings.ANYMAIL, "WEBHOOK_SECRET": ["user:password"]})
    assert Client().post("/anymail/mailjet/inbound/").status_code == 400


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
    response = _post(_payload(raw), postal_key)
    assert response.status_code == 200
    [event] = received
    assert event.message["Subject"] == "Café"
    assert "Un café, s'il vous plaît." in event.message.text


def test_a_mail_over_the_default_upload_limit_is_accepted(postal_key, received):
    body = "x" * 76 + "\n"
    response = _post(_payload(_mail(body * (5 * 1024 * 1024 // 77))), postal_key)
    assert response.status_code == 200
    assert len(received) == 1


def test_a_mail_over_the_cap_is_refused_before_reading(postal_key, received, settings):
    settings.INBOUND_EMAIL_MAX_SIZE_MB = 1
    body = "x" * 76 + "\n"
    response = _post(_payload(_mail(body * (3 * 1024 * 1024 // 77))), postal_key)
    assert response.status_code == 413
    assert received == []


def test_a_body_over_the_cap_without_content_length_is_refused(
    postal_key, received, settings
):
    # Over ASGI, a chunked request has no Content-Length: only reading tells.
    settings.INBOUND_EMAIL_MAX_SIZE_MB = 1
    body = _payload(_mail(("x" * 76 + "\n") * 40_000))
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
    assert _post(_payload(_mail()), postal_key).status_code == 404
    assert received == []
