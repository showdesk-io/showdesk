"""Signed reply addresses, conversation links and outbound Message-IDs."""

import hashlib
import time
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.core import signing
from django.test import override_settings

from apps.email_channel.tokens import (
    conversation_link_message_id,
    conversation_token,
    email_hash,
    outbound_message_id,
    read_conversation_token,
    reply_address,
    ticket_id_from_message_id,
    ticket_id_from_reply_address,
)
from tests.email_channel.mails import INBOUND_DOMAIN


def _ticket():
    return SimpleNamespace(id=uuid.uuid4())


def test_a_reply_address_names_its_ticket_whatever_the_case():
    ticket = _ticket()
    address = reply_address(ticket)

    assert address.endswith(f"@{INBOUND_DOMAIN}")
    assert ticket_id_from_reply_address(address) == ticket.id
    # Mail servers may change the case of an address.
    assert ticket_id_from_reply_address(address.upper()) == ticket.id


def test_a_reply_address_cannot_be_forged_or_moved():
    ticket, other = _ticket(), _ticket()
    address = reply_address(ticket)
    signature = address.partition(".")[2].partition("@")[0]

    tampered = address.replace(signature, "0" * len(signature))
    moved = address.replace(ticket.id.hex, other.id.hex)
    elsewhere = address.replace(INBOUND_DOMAIN, "example.net")

    for address in (tampered, moved, elsewhere, "reply+@" + INBOUND_DOMAIN):
        assert ticket_id_from_reply_address(address) is None


def test_a_conversation_token_carries_ticket_contact_and_a_hash_of_the_address():
    ticket, contact = _ticket(), SimpleNamespace(id=uuid.uuid4())

    token = conversation_token(ticket, contact, "Ann@Example.org ")

    claim = read_conversation_token(token)
    assert (claim.ticket_id, claim.contact_id) == (str(ticket.id), str(contact.id))
    assert claim.holds("ann@example.org")
    assert claim.holds(" ANN@example.org")
    assert not claim.holds("bob@example.org")
    assert not claim.holds("")
    # A link is forwarded, pasted, logged: it doesn't spell the address out.
    payload = signing.loads(token, salt="showdesk.email_channel.conversation")
    assert "ann" not in str(payload).lower()
    # Nor can a list of addresses be hashed to find it, without the secret key.
    assert payload["h"] != hashlib.sha256(b"ann@example.org").hexdigest()[:16]
    assert len(payload["h"]) == 16
    with override_settings(SECRET_KEY="another-secret-key-" * 3):
        assert payload["h"] != email_hash("ann@example.org")
    assert read_conversation_token(token[:-2] + "xx") is None


def test_an_expired_conversation_token_is_only_read_to_renew(settings):
    settings.CONVERSATION_LINK_MAX_AGE_DAYS = 30
    ticket, contact = _ticket(), SimpleNamespace(id=uuid.uuid4())
    token = conversation_token(ticket, contact, "ann@example.org")

    later = time.time() + timedelta(days=31).total_seconds()
    with mock.patch("django.core.signing.time") as clock:
        clock.time.return_value = later
        assert read_conversation_token(token) is None
        claim = read_conversation_token(token, allow_expired=True)

    assert claim.ticket_id == str(ticket.id)


def test_other_signed_values_are_no_conversation_tokens():
    ticket = _ticket()
    payload = {"t": str(ticket.id), "c": str(uuid.uuid4()), "h": "0" * 16}
    reply_token = reply_address(ticket).partition("+")[2].partition("@")[0]

    assert read_conversation_token(reply_token) is None
    assert read_conversation_token(signing.dumps(payload)) is None
    assert read_conversation_token("") is None


def test_an_outbound_message_id_is_stable_and_on_our_domain(settings):
    message = SimpleNamespace(id=uuid.uuid4())

    assert outbound_message_id(message) == f"<{message.id}@{INBOUND_DOMAIN}>"
    assert outbound_message_id(message) == outbound_message_id(message)

    # Without an inbound domain, the domain mail goes out from.
    settings.INBOUND_EMAIL_DOMAIN = ""
    settings.DEFAULT_FROM_EMAIL = "Showdesk <noreply@mail.example.com>"
    assert outbound_message_id(message) == f"<{message.id}@mail.example.com>"

    # Without a domain there either, the site's host, else localhost.
    settings.DEFAULT_FROM_EMAIL = "noreply"
    settings.SITE_URL = "https://help.example.net:8443/app"
    assert outbound_message_id(message) == f"<{message.id}@help.example.net>"
    settings.SITE_URL = ""
    assert outbound_message_id(message) == f"<{message.id}@localhost>"


def test_addresses_and_links_survive_a_secret_key_rotation(settings):
    ticket, contact = _ticket(), SimpleNamespace(id=uuid.uuid4())
    old_key = settings.SECRET_KEY
    address = reply_address(ticket)
    token = conversation_token(ticket, contact, "ann@example.org")
    message_id = conversation_link_message_id(ticket, "task-1")

    settings.SECRET_KEY = "a-new-secret-key-" * 3
    settings.SECRET_KEY_FALLBACKS = [old_key]

    # Mail already sent, and links already mailed, keep working...
    assert ticket_id_from_reply_address(address) == ticket.id
    assert ticket_id_from_message_id(message_id) == ticket.id
    claim = read_conversation_token(token)
    assert claim.holds("ann@example.org")
    # ...while new ones are signed with the new key.
    assert reply_address(ticket) != address
    assert ticket_id_from_reply_address(reply_address(ticket)) == ticket.id

    settings.SECRET_KEY_FALLBACKS = []
    assert ticket_id_from_reply_address(address) is None
    assert ticket_id_from_message_id(message_id) is None
    assert not claim.holds("ann@example.org")
