"""Mails for the email channel tests."""

from email.message import EmailMessage
from pathlib import Path

from anymail.inbound import AnymailInboundMessage

FIXTURES = Path(__file__).parent / "fixtures"
INBOUND_DOMAIN = "in.example.com"


def fixture_bytes(name: str) -> bytes:
    """The raw bytes of a mail of ``fixtures/``."""
    return (FIXTURES / name).read_bytes()


def build(body: str = "Hello", **headers: str) -> bytes:
    """A plain text mail, with default headers that ``headers`` replace.

    Header names take ``_`` for ``-``, and an empty value removes the header.
    """
    defaults = {
        "From": "Ann Customer <ann@example.org>",
        "To": "support@acme.example.com",
        "Subject": "Help",
        "Message-ID": "<1@mail.example.org>",
    }
    defaults.update({name.replace("_", "-"): value for name, value in headers.items()})
    message = EmailMessage()
    for name, value in defaults.items():
        if value:
            message[name] = value
    message.set_content(body)
    return message.as_bytes()


def parse(raw: bytes, *, envelope_recipient: str | None = None):
    """Parse a raw mail as a provider's webhook hands it over."""
    message = AnymailInboundMessage.parse_raw_mime_bytes(raw)
    message.envelope_recipient = envelope_recipient
    return message
