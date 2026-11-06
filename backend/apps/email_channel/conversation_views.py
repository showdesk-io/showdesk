"""The conversation page's API: a ticket's public thread, opened by a mailed link (§6.1).

The link's token is the only credential. It names a ticket and its contact, and the
hash of the address it was mailed to. A link opens its ticket only while that ticket
is still its contact's, the contact still holds that address and isn't anonymized,
and no login moved the ticket (its contact isn't necessarily who wrote it): the
conditions a reply mail mints a link under, enforced again here whatever minted it.
Every failure is the same 404. An expired link is a 410 saying only whether a new
one can be asked for.

What the page shows of the requester's side carries no name or address: the
ticket's session or a mail's sender may be someone else's.

These routes take no account's credentials: an agent logged in on the same browser
is no one here.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.contacts.services import mark_email_proven
from apps.core.permissions import LOOKUP_ERRORS
from apps.core.throttling import (
    ConversationReadThrottle,
    ConversationRenewThrottle,
    ConversationWriteThrottle,
)
from apps.email_channel.serializers import (
    ConversationAttachmentSerializer,
    ConversationMessageSerializer,
    ConversationReplySerializer,
)
from apps.email_channel.tasks import send_conversation_link
from apps.email_channel.thread_matching import (
    ReopenOutcome,
    apply_reopen_rule,
    reopen_expired,
)
from apps.email_channel.tokens import ConversationClaim, read_conversation_token
from apps.notifications.signals import notify_new_message, notify_ticket_update
from apps.tickets.messages import (
    MessageRefused,
    create_user_message,
    lock_ticket_with_contact,
)
from apps.tickets.models import PRE_LOGIN_ANONYMOUS_KEY, Ticket, TicketMessage
from apps.tickets.serializers import TicketAttachmentSerializer

logger = logging.getLogger(__name__)

# One new link per ticket per hour, and per contact a few a day, whoever asks.
RENEWAL_INTERVAL_SECONDS = 3600
RENEWALS_PER_CONTACT_PER_DAY = 3

_NOT_FOUND = {"error": "Conversation not found."}


def _opens(ticket: Ticket | None, claim: ConversationClaim) -> bool:
    """Tell if ``ticket``, loaded with its contact, is one ``claim`` still opens.

    The contact must still hold the address the link was mailed to: once an agent
    corrects it, the previous address's holder has no access anymore.
    """
    if ticket is None or str(ticket.contact_id) != claim.contact_id:
        return False
    contact = ticket.contact
    if contact.is_anonymized or not claim.holds(contact.email):
        return False
    metadata = ticket.context_metadata
    return not (isinstance(metadata, dict) and PRE_LOGIN_ANONYMOUS_KEY in metadata)


def _resolve(claim: ConversationClaim) -> Ticket | None:
    """The ticket ``claim`` opens, or None."""
    try:
        ticket = (
            Ticket.objects.select_related("organization", "contact")
            .filter(pk=claim.ticket_id)
            .first()
        )
    except LOOKUP_ERRORS:
        return None
    return ticket if _opens(ticket, claim) else None


def _open(
    token: str,
) -> tuple[Ticket | None, ConversationClaim | None, Response | None]:
    """The ticket and claim of a link, or the response refusing it.

    Any expired link of ours is a 410, whatever its ticket became: it says no more
    than the link itself does.
    """
    claim = read_conversation_token(token)
    if claim is None:
        if read_conversation_token(token, allow_expired=True) is None:
            return None, None, Response(_NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        renewable = read_conversation_token(token, renewable=True) is not None
        return (
            None,
            None,
            Response({"renewable": renewable}, status=status.HTTP_410_GONE),
        )
    ticket = _resolve(claim)
    if ticket is None:
        return None, None, Response(_NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    return ticket, claim, None


def _logo_url(organization) -> str:
    if not organization.logo:
        return ""
    try:
        return organization.logo.url
    except Exception:
        logger.exception("Organization logo URL unavailable")
        return ""


class _ConversationView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]


class ConversationView(_ConversationView):
    """``GET``: the ticket's public thread, branded.

    Proves the contact's address, and that the requester saw the replies: a reply
    mail waiting for them to stay unread stands down.
    """

    throttle_classes = [ConversationReadThrottle]

    def get(self, request, token: str) -> Response:
        ticket, claim, refused = _open(token)
        if refused:
            return refused
        # Opening proves who holds the mailbox, not who wrote the ticket. A poll
        # finding the contact verified on this address has nothing to write.
        if ticket.contact.email_verified_at is None:
            mark_email_proven(ticket.contact_id, claim.holds)
        # Not an edit of the ticket: ``updated_at`` stays.
        Ticket.objects.filter(pk=ticket.pk).update(widget_last_read_at=timezone.now())
        messages = (
            ticket.messages.filter(message_type=TicketMessage.MessageType.REPLY)
            .select_related("author")
            .prefetch_related("attachments")
            .order_by("created_at")
        )
        organization = ticket.organization
        return Response(
            {
                "organization": {
                    "name": organization.name,
                    "logo": _logo_url(organization),
                    "color": organization.primary_color or settings.BRAND_PRIMARY_COLOR,
                },
                "reference": ticket.reference,
                "title": ticket.title,
                "status": ticket.status,
                "can_reply": not reopen_expired(ticket),
                "messages": ConversationMessageSerializer(messages, many=True).data,
            }
        )


def _post(token: str, attachment=None, **fields) -> Response:
    """Write the requester's message, with ``attachment`` if any, as the widget does.

    A resolved or closed ticket reopens as for a mail (§4.3); one closed for too long
    takes nothing more, since this page can only show its own ticket. The message
    proves nothing about who wrote the ticket.
    """
    ticket, claim, refused = _open(token)
    if refused:
        return refused
    try:
        with transaction.atomic():
            # Contact, then ticket, as an anonymization locks them: under these
            # locks the ticket's contact, its address and session are current.
            ticket, contact = lock_ticket_with_contact(ticket.pk)
            if contact is not None:
                ticket.contact = contact
            if not _opens(ticket, claim):
                raise MessageRefused
            outcome = apply_reopen_rule(ticket)
            if outcome == ReopenOutcome.EXPIRED:
                return Response(
                    {"error": "This conversation is closed."},
                    status=status.HTTP_409_CONFLICT,
                )
            message = create_user_message(
                ticket,
                only_contacts_session=True,
                channel=TicketMessage.Channel.WIDGET,
                **fields,
            )
            if attachment is not None:
                attachment.save(uploaded_by=None, message=message)
            reopened = outcome == ReopenOutcome.REOPENED
            transaction.on_commit(lambda: _announce(ticket, message, reopened=reopened))
    except MessageRefused:
        return Response(_NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    return Response(
        ConversationMessageSerializer(message).data, status=status.HTTP_201_CREATED
    )


def _announce(ticket, message, *, reopened: bool) -> None:
    """Tell agents, and the widget, as for a widget message."""
    try:
        if reopened:
            notify_ticket_update(ticket)
        notify_new_message(message)
    except Exception:
        logger.exception("WebSocket notification failed for message %s", message.id)


class ConversationMessageView(_ConversationView):
    """``POST``: a message from the requester."""

    throttle_classes = [ConversationWriteThrottle]

    def post(self, request, token: str) -> Response:
        serializer = ConversationReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _post(token, body=serializer.validated_data["body"])


class ConversationAttachmentView(_ConversationView):
    """``POST``: a file from the requester, as a message, within the widget's limits."""

    throttle_classes = [ConversationWriteThrottle]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, token: str) -> Response:
        ticket, _, refused = _open(token)
        if refused:
            return refused
        serializer = ConversationAttachmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        attachment = TicketAttachmentSerializer(
            data={
                "ticket": str(ticket.id),
                "file": uploaded,
                "filename": uploaded.name,
                "content_type": uploaded.content_type or "application/octet-stream",
                "file_size": uploaded.size,
            },
            context={"organization": ticket.organization},
        )
        attachment.is_valid(raise_exception=True)
        is_image = attachment.validated_data["content_type"].startswith("image/")
        return _post(
            token,
            attachment,
            body=serializer.validated_data["body"],
            body_type=(
                TicketMessage.BodyType.IMAGE
                if is_image
                else TicketMessage.BodyType.TEXT
            ),
        )


class ConversationRenewView(_ConversationView):
    """``POST {token}``: mail the contact a fresh link. Always a 202.

    The link goes to the address the ticket's contact holds and nowhere else,
    whatever the body says, for a link at most ``RENEWABLE_FOR`` old, at most once
    per ticket per hour and ``RENEWALS_PER_CONTACT_PER_DAY`` times per contact. The
    answer is the same whether anything was sent, so it tells nothing about the
    token or the ticket.
    """

    throttle_classes = [ConversationRenewThrottle]
    parser_classes = [JSONParser]

    def post(self, request) -> Response:
        try:
            data = request.data
        except (ParseError, UnsupportedMediaType):
            data = None
        token = data.get("token") if isinstance(data, dict) else None
        claim = (
            read_conversation_token(token, renewable=True)
            if isinstance(token, str)
            else None
        )
        ticket = _resolve(claim) if claim is not None else None
        if ticket is not None and ticket.contact.email and _renewal_allowed(ticket):
            try:
                send_conversation_link.delay(str(ticket.id))
            except Exception:
                logger.exception("Couldn't queue a conversation link")
        return Response(status=status.HTTP_202_ACCEPTED)


def _renewal_allowed(ticket) -> bool:
    """Count a renewal of ``ticket``'s link, and tell if it's within the limits."""
    try:
        if not cache.add(
            f"email_channel:conversation_renewal:{ticket.pk}",
            1,
            RENEWAL_INTERVAL_SECONDS,
        ):
            return False
        key = f"email_channel:conversation_renewals:{ticket.contact_id}"
        cache.add(key, 0, 24 * 3600)
        return cache.incr(key) <= RENEWALS_PER_CONTACT_PER_DAY
    except (RedisError, ValueError):  # ValueError: the counter expired meanwhile.
        logger.exception("Couldn't count a conversation link renewal")
        return False
