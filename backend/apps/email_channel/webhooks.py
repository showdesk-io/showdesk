"""The webhook receiving Postal's inbound mail."""

import json
import logging
from base64 import b64decode

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent, EventType
from anymail.webhooks.postal import PostalInboundWebhookView
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)


def webhook_secrets(value: str | list[str] | None) -> list[str]:
    """The usable ``user:password`` entries of ``ANYMAIL["WEBHOOK_SECRET"]``.

    A blank entry, or one without both a user and a password, would let Anymail's
    basic-auth views take requests that carry no credentials.
    """
    if isinstance(value, str):
        value = value.split(",")
    secrets = []
    for entry in value or []:
        user, _, password = entry.strip().partition(":")
        if user and password:
            secrets.append(entry.strip())
    return secrets


def max_raw_mail_bytes() -> int:
    """The largest raw mail taken in.

    Attachments up to ``INBOUND_EMAIL_MAX_SIZE_MB`` grow by a third once encoded in
    the mail, which also holds headers and text.
    """
    return int(settings.INBOUND_EMAIL_MAX_SIZE_MB * 1024 * 1024 * 1.4) + 1024 * 1024


def max_webhook_body_bytes() -> int:
    """The largest webhook body: Postal sends the raw mail in base64, inside JSON."""
    return max_raw_mail_bytes() * 4 // 3 + 64 * 1024


class PostalInboundView(PostalInboundWebhookView):
    """Anymail's view, for mail that isn't UTF-8 and is over Django's upload limit.

    Anymail decodes the raw mail as UTF-8, which fails on any 8-bit mail in another
    charset, and reads the body through ``request.body``, which refuses anything over
    ``DATA_UPLOAD_MAX_MEMORY_SIZE``. The signature check is Anymail's.
    """

    # The base class exempts its own dispatch(): Django reads the exemption from the
    # dispatch() of the class the view is built from.
    @method_decorator(csrf_exempt)
    @method_decorator(login_not_required)
    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        limit = max_webhook_body_bytes()
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        if declared > limit:
            return self._too_large(limit)
        # ``request.body`` enforces DATA_UPLOAD_MAX_MEMORY_SIZE, unless already read.
        body = request.read(limit + 1)
        if len(body) > limit:
            return self._too_large(limit)
        request._body = body
        return super().dispatch(request, *args, **kwargs)

    def _too_large(self, limit: int) -> HttpResponse:
        # The mail is lost unless the operator raises the cap: say so.
        logger.warning(
            "Refused an inbound mail webhook over %d bytes; raise "
            "INBOUND_EMAIL_MAX_SIZE_MB to accept larger mail.",
            limit,
        )
        return HttpResponse(status=413)

    def parse_events(self, request: HttpRequest) -> list[AnymailInboundEvent]:
        esp_event = json.loads(request.body)
        if "status" in esp_event:
            raise AnymailConfigurationError(
                "You seem to have set Postal's *tracking* webhook "
                "to Showdesk's Postal *inbound* webhook URL."
            )
        raw = esp_event["message"]
        if esp_event.get("base64") is True:
            raw = b64decode(raw)
        else:
            # JSON can only carry text: 8-bit bytes come back as lone surrogates.
            raw = raw.encode("utf-8", "surrogateescape")
        message = AnymailInboundMessage.parse_raw_mime_bytes(raw)
        # What is stored: serializing the parsed message again could alter it.
        message.raw_bytes = raw
        message.envelope_sender = esp_event.get("mail_from")
        message.envelope_recipient = esp_event.get("rcpt_to")
        # Postal's raw mode sends no verdict but adds its own header. A sender who
        # forges it only gets their own mail ignored.
        if any(
            str(value).strip().lower() == "yes"
            for value in message.get_all("X-Postal-Spam", [])
        ):
            message.spam_detected = True
        return [
            AnymailInboundEvent(
                event_type=EventType.INBOUND,
                timestamp=None,
                event_id=esp_event.get("id"),
                esp_event=esp_event,
                message=message,
            )
        ]
