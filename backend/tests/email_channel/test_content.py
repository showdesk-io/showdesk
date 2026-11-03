"""What of an inbound mail becomes a message: its text and its files (design §4.4)."""

import pytest

from apps.email_channel.content import (
    dropped_note,
    extract_attachments,
    extract_body,
    strip_history,
)
from tests.email_channel.mails import build, fixture_bytes, parse

REPLIES = {
    "en": "The invoice number is 4521.\n\nAnn",
    "fr": "Le numéro de facture est 4521.\n\nAnn",
}


@pytest.mark.parametrize(
    "client", ["gmail", "outlook", "apple_mail", "thunderbird"], ids=str
)
@pytest.mark.parametrize("language", ["en", "fr"])
def test_a_reply_keeps_only_what_was_written(client, language):
    message = parse(fixture_bytes(f"reply_{client}_{language}.eml"))

    assert strip_history(extract_body(message)) == REPLIES[language]


def test_a_mail_that_is_only_quoted_history_keeps_its_text():
    text = "On Mon, Nov 2, 2026 at 10:00 AM Acme wrote:\n> Could you send it?\n"

    assert strip_history(text) == text.strip()


def test_a_forwarded_mail_keeps_what_it_forwards():
    text = (
        "See below.\n\n"
        "---------- Forwarded message ---------\n"
        "From: Bob <bob@example.net>\n"
        "The printer is on fire."
    )

    assert strip_history(text) == text


def test_html_becomes_text_without_any_markup():
    body = extract_body(parse(fixture_bytes("html_only.eml")))

    assert body == (
        "Hello Acme,\n\n"
        "The printer is on fire & smoking.\n"
        "Steps:\n\n"
        "- Open the tray\n"
        "- Run\n\n"
        "See the status page (https://status.example.net/printer) or this.\n\n"
        "Ann"
    )
    for fragment in ("<", "alert", "javascript", "tracker", "Ignored title"):
        assert fragment not in body


def test_a_text_part_is_preferred_and_cleaned_of_nul():
    body = extract_body(parse(build(body="Hello\x00 there\r\n")))

    assert body == "Hello there"


def test_attachments_are_kept_by_basename_and_dangerous_ones_dropped():
    message = parse(fixture_bytes("attachments.eml"))

    attachments, dropped = extract_attachments(message, max_bytes=1024 * 1024)

    assert [(a.filename, a.content_type) for a in attachments] == [
        ("screen.png", "image/png"),
        ("notes.txt", "text/plain"),
    ]
    assert attachments[0].content.startswith(b"\x89PNG")
    assert dropped == ["setup.exe (file type not allowed)"]


def test_attachments_over_the_cap_are_dropped_and_named():
    message = parse(fixture_bytes("attachments.eml"))
    png_size = 70

    attachments, dropped = extract_attachments(message, max_bytes=png_size)

    assert [a.filename for a in attachments] == ["screen.png"]
    assert dropped == [
        "setup.exe (file type not allowed)",
        "notes.txt (over the size limit)",
    ]
    assert dropped_note(dropped) == (
        "Attachments not kept: setup.exe (file type not allowed), "
        "notes.txt (over the size limit)."
    )
    assert dropped_note([]) == ""
