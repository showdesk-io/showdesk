"""The conversation page's API: a ticket's public thread, opened by a mailed link (§6.1).

The link's token is the only credential. It names a ticket and its contact, and the
hash of the address it was mailed to. A link opens its ticket only while that ticket
is still its contact's, the contact isn't anonymized, and no login moved the ticket
(its contact isn't necessarily who wrote it): the conditions a reply mail mints a
link under, enforced again here whatever minted it. Every failure is the same 404; an
expired link is a 410 saying only that a new one can be asked for.

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
)
from apps.email_channel.tasks import send_conversation_link
from apps.email_channel.thread_matching import (
    ReopenOutcome,
    apply_reopen_rule,
    reopen_expired,
)
from apps.email_channel.tokens import ConversationClaim, read_conversation_token
from apps.notifications.signals import notify_new_message, notify_ticket_update
from apps.tickets.messages import create_user_message
from apps.tickets.models import PRE_LOGIN_ANONYMOUS_KEY, Ticket, TicketMessage
from apps.tickets.serializers import TicketAttachmentSerializer, WidgetMessageSerializer

logger = logging.getLogger(__name__)

# One new link per ticket per hour, whoever asks for it.
RENEWAL_INTERVAL_SECONDS = 3600

_NOT_FOUND = {"error": "Conversation not found."}


def _opens(ticket: Ticket | None, claim: ConversationClaim) -> bool:
    """Tell if ``ticket``, loaded with its contact, is one ``claim`` still opens."""
    if ticket is None or str(ticket.contact_id) != claim.contact_id:
        return False
    if ticket.contact.is_anonymized:
        return False
    metadata = ticket.context_metadata
    return not (isinstance(metadata, dict) and PRE_LOGIN_ANONYMOUS_KEY in metadata)


def _resolve(claim: ConversationClaim, *, lock: bool = False) -> Ticket | None:
    """The ticket ``claim`` opens, or None. ``lock`` locks its row, in a transaction."""
    tickets = Ticket.objects.select_related("organization", "contact")
    if lock:
        tickets = tickets.select_for_update(of=("self",))
    try:
        ticket = tickets.filter(pk=claim.ticket_id).first()
    except LOOKUP_ERRORS:
        return None
    return ticket if _opens(ticket, claim) else None


def _open(
    token: str,
) -> tuple[Ticket | None, ConversationClaim | None, Response | None]:
    """The ticket and claim of a link, or the response refusing it."""
    claim = read_conversation_token(token)
    if claim is None:
        expired = read_conversation_token(token, allow_expired=True)
        if expired is not None and _resolve(expired) is not None:
            return (
                None,
                None,
                Response({"renewable": True}, status=status.HTTP_410_GONE),
            )
        return None, None, Response(_NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
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
    """``GET``: the ticket's public thread, branded. Proves the contact's address."""

    throttle_classes = [ConversationReadThrottle]

    def get(self, request, token: str) -> Response:
        ticket, claim, refused = _open(token)
        if refused:
            return refused
        # Opening proves who holds the mailbox, not who wrote the ticket: the
        # ticket's sender is only verified by a message posted here.
        mark_email_proven(ticket.contact_id, claim.holds)
        messages = (
            ticket.messages.filter(message_type=TicketMessage.MessageType.REPLY)
            .select_related("author", "widget_session")
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
                "messages": WidgetMessageSerializer(messages, many=True).data,
            }
        )


def _post(token: str, attachment=None, **fields) -> Response:
    """Write the requester's message, with ``attachment`` if any, as the widget does.

    A resolved or closed ticket reopens as for a mail (§4.3); one closed for too long
    takes nothing more, since this page can only show its own ticket. The message
    verifies the ticket's sender if the link went to the address the contact holds.
    """
    ticket, claim, refused = _open(token)
    if refused:
        return refused
    with transaction.atomic():
        # Under the lock, the ticket's contact and session are current.
        ticket = _resolve(claim, lock=True)
        if ticket is None:
            return Response(_NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        outcome = apply_reopen_rule(ticket)
        if outcome == ReopenOutcome.EXPIRED:
            return Response(
                {"error": "This conversation is closed."},
                status=status.HTTP_409_CONFLICT,
            )
        message = create_user_message(
            ticket, channel=TicketMessage.Channel.WIDGET, **fields
        )
        if attachment is not None:
            attachment.save(uploaded_by=None, message=message)
        if not ticket.sender_verified_at and claim.holds(ticket.contact.email):
            ticket.sender_verified_at = timezone.now()
            ticket.save(update_fields=["sender_verified_at", "updated_at"])
        reopened = outcome == ReopenOutcome.REOPENED
        transaction.on_commit(lambda: _announce(ticket, message, reopened=reopened))
    return Response(
        WidgetMessageSerializer(message).data, status=status.HTTP_201_CREATED
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
        serializer = ConversationMessageSerializer(data=request.data)
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
    whatever the body says, at most once per ticket per hour. The answer is the same
    whether anything was sent, so it tells nothing about the token or the ticket.
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
            read_conversation_token(token, allow_expired=True)
            if isinstance(token, str)
            else None
        )
        ticket = _resolve(claim) if claim is not None else None
        if (
            ticket is not None
            and ticket.contact.email
            and self._first_this_hour(ticket)
        ):
            try:
                send_conversation_link.delay(str(ticket.id))
            except Exception:
                logger.exception("Couldn't queue a conversation link")
        return Response(status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _first_this_hour(ticket) -> bool:
        try:
            return cache.add(
                f"email_channel:conversation_renewal:{ticket.pk}",
                1,
                RENEWAL_INTERVAL_SECONDS,
            )
        except RedisError:
            logger.exception("Couldn't count a conversation link renewal")
            return False
