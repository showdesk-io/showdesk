"""What of an inbound mail becomes a message: its text and its files (design §4.4)."""

import time
from email.message import EmailMessage

import pytest

from apps.email_channel.content import (
    MAX_ATTACHMENTS,
    dropped_note,
    extract_attachments,
    extract_body,
    strip_history,
)
from apps.email_channel.content import (
    _clean_text as _clean,
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


def test_files_past_the_fiftieth_are_dropped_and_named():
    message = EmailMessage()
    message["From"] = "ann@example.org"
    message.set_content("Many files.")
    for index in range(52):
        message.add_attachment(
            b"x", maintype="text", subtype="plain", filename=f"{index}.txt"
        )

    attachments, dropped = extract_attachments(parse(message.as_bytes()), 1024)

    assert len(attachments) == MAX_ATTACHMENTS == 50
    assert dropped == [
        "50.txt (over the limit of 50 files)",
        "51.txt (over the limit of 50 files)",
    ]


def test_stripping_takes_linear_time_on_hostile_text():
    lines = ["On", "Online", "One wrote", "On Monday", "Le", "> On"] * 6000
    text = "Hello\n" + "\n".join(lines)
    assert len(text) > 200_000

    started = time.monotonic()
    strip_history(text)

    assert time.monotonic() - started < 2


def test_dashes_separators_and_lone_header_words_are_no_history():
    text = (
        "Steps:\n\n"
        "-open the app\n"
        "-click Print\n\n"
        "Run it with:\n"
        "--verbose\n\n"
        "------------\n\n"
        "From: Paris\n"
        "Date: 12 Nov\n\n"
        "-- \n"
        "Ann"
    )

    assert strip_history(text) == _clean(text)


def test_a_trailing_quote_block_is_dropped_but_an_inline_one_kept():
    text = "> Which printer?\nThe P-100.\n\n> Since when?\n> And where?"

    assert strip_history(text) == "> Which printer?\nThe P-100."


def test_every_inline_text_part_is_body_and_files_are_not():
    raw = (
        b"From: ann@example.org\r\n"
        b"Subject: Parts\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
        b"--b\r\nContent-Type: text/plain\r\n\r\nFirst part.\r\n"
        b"--b\r\nContent-Type: text/calendar; method=REQUEST\r\n\r\nBEGIN:VCALENDAR\r\n"
        b"--b\r\nContent-Type: text/plain\r\n"
        b'Content-Disposition: attachment; filename="log.txt"\r\n\r\nA log.\r\n'
        b"--b\r\nContent-Type: text/plain\r\n\r\nSecond part.\r\n"
        b"--b--\r\n"
    )
    message = parse(raw)

    assert extract_body(message) == "First part.\n\nSecond part."
    attachments, dropped = extract_attachments(message, 1024)
    assert [a.filename for a in attachments] == ["log.txt"]
    assert dropped == ["an unnamed text/calendar part"]


def test_an_unknown_charset_is_read_as_utf8():
    raw = (
        b"From: ann@example.org\r\n"
        b"Subject: Charset\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=x-bogus\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n"
        b"Caf\xc3\xa9 and \xff.\r\n"
    )

    assert extract_body(parse(raw)) == "Café and �."
