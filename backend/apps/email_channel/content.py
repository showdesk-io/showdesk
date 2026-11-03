"""What of an inbound mail becomes a message: its text and its files (design §4.4).

A message body is plain text, and is shown as text: HTML is reduced to its text,
and no markup of a mail reaches a message.
"""

import mimetypes
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PureWindowsPath
from urllib.parse import urlsplit

from email_reply_parser import EmailReplyParser

from apps.email_channel.recipients import one_line
from apps.tickets.models import BLOCKED_EXTENSIONS, TicketAttachment

# Above the quoted history of the mails we send: what a reply writes is above it.
REPLY_MARKER = "-- Reply above this line --"

_FILENAME_MAX_LENGTH = TicketAttachment._meta.get_field("filename").max_length
_CONTENT_TYPE_MAX_LENGTH = TicketAttachment._meta.get_field("content_type").max_length

# Postgres refuses NUL in text; the other control characters are noise.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in _CONTROL_CHARACTERS.sub("", text).split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# Body


def extract_body(message) -> str:
    """The mail's text: its text part, or else the text of its HTML part."""
    text = message.text or ""
    if not text.strip() and message.html:
        text = html_to_text(message.html)
    return _clean_text(text)


class _TextExtractor(HTMLParser):
    """Collects the text of an HTML document, and nothing of its markup."""

    _SKIPPED = frozenset({"head", "script", "style", "template", "noscript", "title"})
    _BLOCKS = frozenset(
        {
            "address", "article", "blockquote", "div", "dl", "dt", "dd", "footer",
            "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "ol",
            "p", "pre", "section", "table", "tr", "ul",
        }
    )  # fmt: skip
    _PARAGRAPHS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._line: list[str] = []
        self._quote_depth = 0
        self._line_depth = 0
        self._skipping = 0
        self._links: list[tuple[str, int]] = []

    def _break(self, *, blank: bool = False) -> None:
        text = " ".join("".join(self._line).split())
        if text:
            self.lines.append("> " * self._line_depth + text)
        if blank and self.lines and self.lines[-1] != "":
            self.lines.append("")
        self._line = []
        self._line_depth = self._quote_depth

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIPPED:
            self._skipping += 1
        elif tag == "br":
            self._break()
        elif tag in self._BLOCKS:
            self._break(blank=tag in self._PARAGRAPHS)
            if tag == "blockquote":
                self._quote_depth += 1
                self._line_depth = self._quote_depth
            elif tag == "li":
                self._line.append("- ")
        elif tag == "a":
            self._links.append((dict(attrs).get("href") or "", len(self._line)))

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self._BLOCKS:
            self._break(blank=tag in self._PARAGRAPHS)
            if tag == "blockquote":
                self._quote_depth = max(0, self._quote_depth - 1)
                self._line_depth = self._quote_depth
        elif tag == "a" and self._links:
            href, start = self._links.pop()
            label = "".join(self._line[start:]).strip()
            if _is_shown_link(href) and href != label:
                self._line.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self._line.append(data)

    def close(self) -> None:
        super().close()
        self._break()


def _is_shown_link(href: str) -> bool:
    return urlsplit(href.strip()).scheme.lower() in ("http", "https", "mailto")


def html_to_text(html: str) -> str:
    """The text of an HTML document: its words, links' addresses, and no markup.

    Quoted blocks come out as ``>`` lines, as in a text mail.
    """
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return _clean_text("\n".join(extractor.lines))


# Quoted history

# "On Mon, 2 Nov 2026, Ann <ann@example.org> wrote:", "Le 2 nov. 2026, Ann a écrit :",
# possibly quoted (Apple Mail on iOS).
_QUOTE_HEADER = re.compile(r"^(?:>\s*)?(?:On\s.*\swrote|Le\s.*\sa\s+écrit)\s*:$")
_ORIGINAL_MESSAGE = re.compile(
    r"^-{2,}\s*(?:original message|message d'origine)\s*-{2,}$", re.IGNORECASE
)
# Outlook's header block: "From: …" then "Sent: …", in English or French.
_OUTLOOK_FROM = re.compile(r"^\*?(?:From|De)\s?:", re.IGNORECASE)
_OUTLOOK_SENT = re.compile(r"^\*?(?:Sent|Envoyé|Date)\s?:", re.IGNORECASE)
_SEPARATOR = re.compile(r"^_{10,}$")
# Gmail, Thunderbird and Apple Mail mark a forward. Outlook writes a forward as it
# writes a reply: only the subject tells them apart.
_FORWARDED = re.compile(
    r"^(?:-{2,}\s*(?:forwarded message|message transféré)\s*-{2,}"
    r"|begin forwarded message:|début du message réexpédié\s*:)$",
    re.IGNORECASE,
)


def _history_start(lines: list[str]) -> int | None:
    """The index of the line where the quoted history starts, if any."""
    for index, line in enumerate(lines):
        line = line.strip().replace("\xa0", " ")
        if REPLY_MARKER in line or _ORIGINAL_MESSAGE.match(line):
            return index
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        # Gmail wraps a long header over two lines.
        if _QUOTE_HEADER.match(line) or _QUOTE_HEADER.match(f"{line} {following}"):
            return index
        if _OUTLOOK_FROM.match(line) and any(
            _OUTLOOK_SENT.match(next_line.strip().replace("\xa0", " "))
            for next_line in lines[index + 1 : index + 4]
        ):
            while index > 0 and (
                not lines[index - 1].strip() or _SEPARATOR.match(lines[index - 1])
            ):
                index -= 1
            return index
    return None


def strip_history(text: str) -> str:
    """What a reply wrote, without the history it quotes.

    Cut at our own marker, at a client's quote header or Outlook's header block,
    then what ``email-reply-parser`` takes for quotes or a signature. Agents can
    always open the original mail. A mail that is all history keeps its text.

    A forward is not history: what it forwards is the request.
    """
    text = _clean_text(text)
    lines = text.split("\n")
    forwarded = next(
        (index for index, line in enumerate(lines) if _FORWARDED.match(line.strip())),
        len(lines),
    )
    start = _history_start(lines[:forwarded])
    written = "\n".join(lines[: forwarded if start is None else start])
    written = _clean_text(EmailReplyParser.parse_reply(written))
    if start is None and forwarded < len(lines):
        written = "\n\n".join(
            part for part in (written, "\n".join(lines[forwarded:])) if part
        )
    return written or text


# Attachments


# Files kept from one mail: each one is a row and a stored file.
MAX_ATTACHMENTS = 50
# Dropped files named in the note: the rest are counted.
_MAX_NAMED_DROPPED = 20


@dataclass(frozen=True)
class Attachment:
    """A file of an inbound mail, to keep as a ``TicketAttachment``."""

    filename: str
    content_type: str
    content: bytes


def _leaf_parts(part):
    """The parts of a mail that aren't containers, without entering attached mails."""
    if part.get_content_maintype() == "multipart":
        for child in part.get_payload():
            yield from _leaf_parts(child)
    else:
        yield part


def _is_file(part) -> bool:
    # Body text is no file; anything else is, with or without a disposition
    # (images of multipart/related, for instance).
    return (
        part.is_attachment()
        or part.get_content_maintype() != "text"
        or bool(part.get_filename())
    )


def safe_filename(name: str | None, content_type: str) -> str:
    """A file name without any path, nor what Windows would drop at its end."""
    name = PureWindowsPath(one_line(name)).name.strip(" .")
    if not name:
        extension = mimetypes.guess_extension(content_type) or ".bin"
        name = f"attachment{extension}"
    if len(name) > _FILENAME_MAX_LENGTH:
        stem, extension = os.path.splitext(name)
        name = stem[: _FILENAME_MAX_LENGTH - len(extension)] + extension
    return name


def _content(part) -> bytes:
    try:
        return part.get_content_bytes() or b""
    except (AssertionError, ValueError):
        return b""


def extract_attachments(message, max_bytes: int) -> tuple[list[Attachment], list[str]]:
    """The mail's files, and a description of each one dropped.

    A file whose extension is blocked for uploads is dropped, and so is any file
    that would take the total over ``max_bytes`` or the count over
    ``MAX_ATTACHMENTS``.
    """
    attachments: list[Attachment] = []
    dropped: list[str] = []
    total = 0
    for part in _leaf_parts(message):
        if not _is_file(part):
            continue
        content_type = part.get_content_type()[:_CONTENT_TYPE_MAX_LENGTH]
        filename = safe_filename(part.get_filename(), content_type)
        if os.path.splitext(filename)[1].lower() in BLOCKED_EXTENSIONS:
            dropped.append(f"{filename} (file type not allowed)")
            continue
        if len(attachments) >= MAX_ATTACHMENTS:
            dropped.append(f"{filename} (over the limit of {MAX_ATTACHMENTS} files)")
            continue
        content = _content(part)
        if total + len(content) > max_bytes:
            dropped.append(f"{filename} (over the size limit)")
            continue
        total += len(content)
        attachments.append(Attachment(filename, content_type, content))
    return attachments, dropped


def dropped_note(dropped: list[str]) -> str:
    """The line telling agents which files of the mail weren't kept, or ""."""
    if not dropped:
        return ""
    named = ", ".join(dropped[:_MAX_NAMED_DROPPED])
    rest = len(dropped) - _MAX_NAMED_DROPPED
    if rest > 0:
        named += f" and {rest} more"
    return f"Attachments not kept: {named}."
