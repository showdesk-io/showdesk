"""Which inbound mails open no ticket, and why (design §4.2).

What a mail says of itself is a claim: a filter can only drop a mail, or show its
organization's admins what it says. Nothing here grants access.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from email.parser import HeaderParser
from email.utils import parseaddr
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.core.email import send_branded_email
from apps.email_channel.content import decoded_text, extract_body
from apps.email_channel.models import InboundEmail, Mailbox
from apps.email_channel.recipients import Recipient, one_line
from apps.organizations.models import User
from apps.tickets.models import TicketMessage

GMAIL_FORWARDING_SENDER = "forwarding-noreply@google.com"
# The only hosts a Gmail confirmation link is kept, and shown, for.
GMAIL_CONFIRMATION_HOSTS = frozenset({"mail.google.com", "mail-settings.google.com"})

_CODE_IN_SUBJECT = re.compile(r"\(#(\d{4,20})\)")
_CODE_IN_BODY = re.compile(
    r"(?:confirmation code|code de confirmation)\s*:\s*(\d{4,20})", re.IGNORECASE
)
_URL = re.compile(r"https://[^\s<>\"']+")
_URL_MAX_LENGTH = 2048
# Seconds between two mails to admins about a mailbox's confirmations.
CONFIRMATION_NOTICE_EVERY = 10 * 60
# Enough for any real bounce, and a bound on what one mail makes us look up.
_MAX_BOUNCED_IDS = 20


@dataclass(frozen=True)
class Verdict:
    """What becomes of a mail that opens no ticket: its row's status and reason."""

    status: str
    reason: str


def _ignored(reason: str) -> Verdict:
    return Verdict(InboundEmail.Status.IGNORED, reason)


def classify(message, inbound: InboundEmail, recipient: Recipient) -> Verdict | None:
    """Tell why ``message`` opens no ticket, or None when it goes on to one.

    ``inbound`` is its stored row and ``recipient`` what it was delivered to. Some
    verdicts act before returning: a Gmail forwarding confirmation is kept on the
    mailbox and mailed to the organization's admins once committed, and a bounce
    marks the message it reports as not delivered.
    """
    organization = recipient.organization
    if _is_duplicate(inbound, organization):
        return _ignored("duplicate")
    # Before anything a mail can make us do, such as mailing admins.
    if _is_mailbox_rate_limited(inbound):
        return _ignored("mailbox_rate_limited")
    if _is_rate_limited(inbound):
        return _ignored("rate_limited")
    if _is_forwarding_confirmation(message, recipient):
        _record_forwarding_confirmation(message, recipient.mailbox)
        return _ignored("forwarding_confirmation")
    if _is_bounce(message, inbound):
        _mark_bounced_messages(message, organization)
        return _ignored("bounce")
    if _is_loop(inbound, organization):
        return _ignored("loop")
    if reason := _automatic_reason(message):
        return _ignored(reason)
    if getattr(message, "spam_detected", None) is True:
        return _ignored("spam")
    return None


def _header(message, name: str) -> str:
    return one_line(message.get(name))


def _from_address(message) -> str:
    return parseaddr(_header(message, "From"))[1].strip().lower()


# Gmail forwarding confirmation


def _is_forwarding_confirmation(message, recipient: Recipient) -> bool:
    # Gmail writes to the forwarding address itself, which nobody else knows. On
    # the public address, a forged From would be enough.
    mailbox = recipient.mailbox
    return (
        _from_address(message) == GMAIL_FORWARDING_SENDER
        and recipient.ticket is None
        and mailbox is not None
        and recipient.address == mailbox.inbound_address.lower()
    )


def _confirmation_url(text: str) -> str:
    """The first Google link of ``text``, rebuilt from parts checked one by one."""
    for match in _URL.finditer(text):
        url = match.group().rstrip(".,;:)]")
        if len(url) > _URL_MAX_LENGTH:
            continue
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        # A user, a port or a backslash can make a browser go somewhere else
        # than the host a parser reads.
        if parts.scheme != "https" or parts.netloc not in GMAIL_CONFIRMATION_HOSTS:
            continue
        if "\\" in url:
            continue
        return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))
    return ""


def _record_forwarding_confirmation(message, mailbox: Mailbox) -> None:
    text = extract_body(message)
    match = _CODE_IN_SUBJECT.search(_header(message, "Subject")) or (
        _CODE_IN_BODY.search(text)
    )
    mailbox.forwarding_confirmation = {
        "url": _confirmation_url(text),
        "code": match.group(1) if match else "",
        "detected_at": timezone.now().isoformat(),
    }
    mailbox.save(update_fields=["forwarding_confirmation", "updated_at"])
    confirmation = dict(mailbox.forwarding_confirmation)
    transaction.on_commit(lambda: _notify_admins_of_confirmation(mailbox, confirmation))


def _notify_admins_of_confirmation(mailbox: Mailbox, confirmation: dict) -> None:
    # Once in a while at most: the mailbox keeps the latest one anyway.
    if not cache.add(
        f"email_channel:confirmation_notice:{mailbox.pk}", 1, CONFIRMATION_NOTICE_EVERY
    ):
        return
    organization = mailbox.organization
    admins = list(
        organization.users.filter(role=User.Role.ADMIN, is_active=True).values_list(
            "email", flat=True
        )
    )
    if not admins:
        return
    send_branded_email(
        template="forwarding_confirmation",
        subject=f"Gmail forwarding confirmation for {mailbox.name}",
        to=admins,
        organization=organization,
        context={
            "org_name": organization.name,
            "mailbox_name": mailbox.name,
            "inbound_address": mailbox.inbound_address,
            "code": confirmation["code"],
            "url": confirmation["url"],
            "settings_url": f"{settings.SITE_URL.rstrip('/')}/settings",
        },
        fail_silently=True,
    )


# Bounces


def _is_bounce(message, inbound: InboundEmail) -> bool:
    if message.get_content_type() == "multipart/report":
        report_type = message.get_param("report-type", "") or ""
        # A read receipt is a report too, but not a failure.
        return str(report_type).lower() == "delivery-status"
    local_part = inbound.sender.partition("@")[0]
    return local_part in ("mailer-daemon", "postmaster")


def _delivery_failed(message) -> bool:
    """False for a report that only says delivery is delayed."""
    actions = []
    for part in message.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        for block in part.get_payload():
            if hasattr(block, "get"):
                actions.append(one_line(block.get("Action")).lower())
    actions = [action for action in actions if action]
    return not actions or "failed" in actions


def _bounced_message_ids(message) -> list[str]:
    """The Message-IDs of the returned mail, as the report quotes it."""
    ids = []
    for part in message.walk():
        content_type = part.get_content_type()
        if content_type == "message/rfc822":
            payload = part.get_payload()
            headers = payload[0] if payload else None
        elif content_type == "text/rfc822-headers":
            headers = HeaderParser().parsestr(decoded_text(part))
        else:
            continue
        message_id = one_line(headers.get("Message-ID")) if headers else ""
        if message_id and message_id not in ids:
            ids.append(message_id)
    return ids[:_MAX_BOUNCED_IDS]


def _mark_bounced_messages(message, organization) -> None:
    if not _delivery_failed(message):
        return
    ids = _bounced_message_ids(message)
    if not ids:
        return
    # Only mail we sent: a customer's own Message-ID can be quoted by anyone.
    TicketMessage.objects.filter(
        ticket__organization=organization, external_id__in=ids
    ).exclude(sender_type=TicketMessage.SenderType.USER).update(
        email_delivery_status=TicketMessage.DeliveryStatus.FAILED
    )


# Loops, automatic and bulk mail


def _is_loop(inbound: InboundEmail, organization) -> bool:
    """From our own domain, or from one of the organization's own addresses."""
    domain = settings.INBOUND_EMAIL_DOMAIN.lower()
    if domain and inbound.sender.rpartition("@")[2] == domain:
        return True
    return (
        bool(inbound.sender)
        and Mailbox.objects.filter(
            organization=organization, public_address=inbound.sender
        ).exists()
    )


def _automatic_reason(message) -> str | None:
    auto_submitted = _header(message, "Auto-Submitted").split(";")[0].strip().lower()
    if auto_submitted and auto_submitted != "no":
        return "auto_reply"
    if any(message.get(name) is not None for name in ("X-Autoreply", "X-Autorespond")):
        return "auto_reply"
    precedence = _header(message, "Precedence").lower()
    if precedence == "auto_reply":
        return "auto_reply"
    if precedence in ("bulk", "junk", "list") or message.get("List-Id") is not None:
        return "bulk"
    return None


# Rate limit


def _is_duplicate(inbound: InboundEmail, organization) -> bool:
    """Tell if the mail is already a message of the organization.

    One mail sent to a ticket's reply address and to the inbound address arrives
    twice, as two rows: it must land once.
    """
    return TicketMessage.objects.filter(
        ticket__organization=organization, external_id=inbound.message_id
    ).exists()


def _last_hour(inbound: InboundEmail):
    # The hour before the mail arrived, so that a replay gives the same answer.
    return InboundEmail.objects.filter(
        received_at__gt=inbound.received_at - timedelta(hours=1),
        received_at__lte=inbound.received_at,
    )


def _is_rate_limited(inbound: InboundEmail) -> bool:
    """More mail from this sender to this mailbox than allowed in an hour.

    Without a mailbox (a reply address of a ticket that has none), counted over
    every such mail of the sender.
    """
    rows = _last_hour(inbound).filter(sender=inbound.sender)
    if inbound.mailbox_id:
        rows = rows.filter(mailbox_id=inbound.mailbox_id)
    else:
        rows = rows.filter(mailbox__isnull=True).exclude(
            status=InboundEmail.Status.REJECTED
        )
    return rows.count() > settings.INBOUND_EMAIL_RATE_LIMIT_PER_HOUR


def _is_mailbox_rate_limited(inbound: InboundEmail) -> bool:
    """More mail to this mailbox, from anyone, than allowed in an hour."""
    if not inbound.mailbox_id:
        return False
    rows = _last_hour(inbound).filter(mailbox_id=inbound.mailbox_id)
    return rows.count() > settings.INBOUND_EMAIL_MAILBOX_RATE_LIMIT_PER_HOUR
