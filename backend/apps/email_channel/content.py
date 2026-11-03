"""What of an inbound mail becomes a message: its text and its files (design §4.4).

A message body is plain text, and is shown as text: HTML is reduced to its text,
and no markup of a mail reaches a message.
"""

import codecs
import mimetypes
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PureWindowsPath
from urllib.parse import urlsplit

from apps.core.text import one_line
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


def decoded_text(part) -> str:
    """A text part's content as text, whatever charset it declares.

    An unknown charset, such as ``x-bogus`` or ``unknown-8bit``, is read as UTF-8,
    and what doesn't decode is replaced rather than failing the mail.
    """
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        codecs.lookup(charset)
    except LookupError:
        charset = "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeError):  # A codec that refuses "replace".
        return payload.decode("utf-8", errors="replace")


def _body_parts(message, subtype: str) -> list[str]:
    return [
        decoded_text(part)
        for part in _leaf_parts(message)
        if part.get_content_type() == f"text/{subtype}" and not _is_file(part)
    ]


def extract_body(message) -> str:
    """The mail's text: its inline text parts in order, or else its HTML's text."""
    texts = [_clean_text(text) for text in _body_parts(message, "plain")]
    text = "\n\n".join(text for text in texts if text)
    if not text:
        texts = [html_to_text(html) for html in _body_parts(message, "html")]
        text = "\n\n".join(text for text in texts if text)
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
#
# Line by line, on lines cut to a bounded length, with patterns that can't
# backtrack far: a mail's text is whatever its sender wants, of any size.

_MAX_MATCHED_LINE = 300
# "On Mon, 2 Nov 2026, Ann <ann@example.org> wrote:", "Le 2 nov. 2026, Ann a écrit :",
# possibly quoted (Apple Mail on iOS).
_ATTRIBUTION = re.compile(r"(?:>\s?)?(?:On\s[^\n]*\swrote|Le\s[^\n]*\sa\s+écrit)\s?:")
_ATTRIBUTION_START = re.compile(r"(?:>\s?)?(?:On|Le)\s")
# Outlook's header block, in English or French.
_HEADER_LINE = re.compile(
    r"\*?(from|de|sent|envoyé|date|to|à|cc|subject|objet)\*?\s?:\*?(?:\s|$)",
    re.IGNORECASE,
)
_HEADER_GROUPS = (
    frozenset({"from", "de"}),
    frozenset({"sent", "envoyé", "date"}),
    frozenset({"to", "à", "subject", "objet"}),
)
_ABOVE_HEADERS = re.compile(
    r"_{10,}|-{2,}\s*(?:original message|message d'origine)\s*-{2,}", re.IGNORECASE
)
# Gmail, Thunderbird and Apple Mail mark a forward. Outlook writes a forward as it
# writes a reply: only the subject tells them apart.
_FORWARDED = re.compile(
    r"(?:-{2,}\s*(?:forwarded message|message transféré)\s*-{2,}"
    r"|begin forwarded message:|début du message réexpédié\s*:)",
    re.IGNORECASE,
)


def _matched(line: str) -> str:
    return line.strip().replace("\xa0", " ")[:_MAX_MATCHED_LINE]


def _is_attribution(line: str, following: str) -> bool:
    if not _ATTRIBUTION_START.match(line):
        return False
    # Gmail wraps a long attribution over two lines.
    return bool(
        _ATTRIBUTION.fullmatch(line) or _ATTRIBUTION.fullmatch(f"{line} {following}")
    )


def _header_name(line: str) -> str | None:
    match = _HEADER_LINE.match(line)
    return match.group(1).lower() if match else None


def _is_header_block(lines: list[str], index: int) -> bool:
    """Outlook's block: three header lines or more, From first, then Sent, To."""
    if _header_name(lines[index]) not in _HEADER_GROUPS[0]:
        return False
    names = set()
    for line in lines[index : index + 8]:
        name = _header_name(line)
        if name is None:
            break
        names.add(name)
    return len(names) >= 3 and all(names & group for group in _HEADER_GROUPS)


def _history_start(lines: list[str]) -> int | None:
    """The index of the line where the quoted history starts, if any."""
    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if REPLY_MARKER in line or _is_attribution(line, following):
            return index
        if _is_header_block(lines, index):
            # With the separator or "Original Message" line just above it.
            while index > 0 and (
                not lines[index - 1] or _ABOVE_HEADERS.fullmatch(lines[index - 1])
            ):
                index -= 1
            return index
    return None


def _without_trailing_quote(lines: list[str]) -> list[str]:
    end = len(lines)
    while end and (not lines[end - 1] or lines[end - 1].startswith(">")):
        end -= 1
    return lines[:end]


def strip_history(text: str) -> str:
    """What a reply wrote, without the history it quotes.

    Cut at our own marker, at a client's attribution line ("On … wrote:") or at
    Outlook's header block, then drop a block of ``>`` lines at the end. Nothing
    is taken for a signature. Agents can always open the original mail, and a mail
    that is all history keeps its text.

    A forward is not history: what it forwards is the request.
    """
    text = _clean_text(text)
    lines = text.split("\n")
    matched = [_matched(line) for line in lines]
    forwarded = next(
        (index for index, line in enumerate(matched) if _FORWARDED.fullmatch(line)),
        len(lines),
    )
    start = _history_start(matched[:forwarded])
    end = forwarded if start is None else start
    kept = _without_trailing_quote(lines[:end])
    if start is None and forwarded < len(lines):
        kept += ["", *lines[forwarded:]]
    return _clean_text("\n".join(kept)) or text


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
    # Inline text without a name is body; anything else is a file, with or without
    # a disposition (images of multipart/related, for instance).
    return (
        part.is_attachment()
        or part.get_content_maintype() != "text"
        or bool(part.get_filename())
    )


def _is_body(part) -> bool:
    return not _is_file(part) and part.get_content_subtype() in ("plain", "html")


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
        if _is_body(part):
            continue
        if not _is_file(part):
            # Inline text that is neither text nor HTML, such as an invitation.
            dropped.append(f"an unnamed {part.get_content_type()} part")
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
