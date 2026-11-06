"""What agents and admins manage of the email channel.

Agents read mailboxes and their log, admins change them and replay failed mails.
A raw mail never gets a URL: agents of its ticket's organization download it from
an authenticated route.
"""

from contextlib import contextmanager

from botocore.exceptions import ClientError
from django.db import IntegrityError, transaction
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from apps.core.permissions import (
    LOOKUP_ERRORS,
    HasStrictActiveOrg,
    IsOrgAdmin,
    IsOrgAdminOrReadOnly,
    IsOrgStaff,
    get_active_org,
)
from apps.email_channel.models import InboundEmail, Mailbox
from apps.email_channel.serializers import (
    PUBLIC_ADDRESS_TAKEN,
    InboundLogSerializer,
    MailboxSerializer,
)
from apps.email_channel.tasks import replay

# What didn't become a message. Rejected mails have no mailbox: the admin shows them.
LOGGED_STATUSES = (
    InboundEmail.Status.IGNORED,
    InboundEmail.Status.REJECTED,
    InboundEmail.Status.FAILED,
)


@contextmanager
def _public_address_race():
    """A public address taken since validation is the same 400 as one taken before."""
    try:
        with transaction.atomic():
            yield
    except IntegrityError as exc:
        if "unique_mailbox_public_address" in str(exc):
            raise ValidationError({"public_address": [PUBLIC_ADDRESS_TAKEN]}) from exc
        raise


class MailboxViewSet(viewsets.ModelViewSet):
    """The organization's mailboxes. Deactivated, never deleted: their log goes too."""

    http_method_names = ["get", "post", "patch", "head", "options"]
    serializer_class = MailboxSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrgStaff,
        HasStrictActiveOrg,
        IsOrgAdminOrReadOnly,
    ]
    pagination_class = None

    def get_queryset(self):
        return Mailbox.objects.filter(
            organization=get_active_org(self.request)
        ).select_related("organization")

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "organization": get_active_org(self.request),
        }

    def perform_create(self, serializer) -> None:
        with _public_address_race():
            serializer.save(organization=get_active_org(self.request))

    def perform_update(self, serializer) -> None:
        with _public_address_race():
            serializer.save()

    @action(detail=True, methods=["post"], url_path="regenerate-address")
    def regenerate_address(self, request, pk=None):
        """Give the mailbox a new inbound address. Mail to the previous one bounces."""
        mailbox = self.get_object()
        mailbox.regenerate_address()
        return Response(self.get_serializer(mailbox).data)

    @action(detail=True, methods=["get"])
    def inbound(self, request, pk=None):
        """The mailbox's mails that were ignored or failed, newest first."""
        mailbox = self.get_object()
        rows = mailbox.inbound_emails.filter(status__in=LOGGED_STATUSES).order_by(
            "-received_at"
        )
        # The list of mailboxes isn't paginated, their log is.
        paginator = api_settings.DEFAULT_PAGINATION_CLASS()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(
            InboundLogSerializer(page, many=True).data
        )


class InboundReplayView(APIView):
    """``POST``: run a failed mail of the organization through the pipeline again."""

    permission_classes = [IsAuthenticated, IsOrgStaff, HasStrictActiveOrg, IsOrgAdmin]

    def post(self, request, pk: str) -> Response:
        try:
            inbound = InboundEmail.objects.get(
                pk=pk, mailbox__organization=get_active_org(request)
            )
        except LOOKUP_ERRORS:
            raise NotFound from None
        if not replay(inbound.pk):
            return Response(
                {"error": "Only a failed mail can be replayed."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"status": InboundEmail.Status.PENDING}, status=202)


class OriginalMailView(APIView):
    """``GET``: the raw mail a message came from, as a download.

    For agents of the ticket's organization. 404 once the raw mail is purged.
    """

    permission_classes = [IsAuthenticated, IsOrgStaff, HasStrictActiveOrg]

    def get(self, request, ticket_id: str, message_id: str):
        inbound = (
            InboundEmail.objects.filter(
                ticket_message_id=message_id,
                ticket_message__ticket_id=ticket_id,
                ticket_message__ticket__organization=get_active_org(request),
            )
            .exclude(raw="")
            .select_related("ticket_message__ticket")
            .order_by("-received_at")
            .first()
        )
        if inbound is None or not inbound.raw.storage.exists(inbound.raw.name):
            raise NotFound
        try:
            file = inbound.raw.open("rb")
        except FileNotFoundError:
            # Purged between the check and the opening.
            raise NotFound from None
        except ClientError as exc:
            # The same, on S3. Any other storage error stays a 500.
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey"):
                raise
            raise NotFound from None
        message = inbound.ticket_message
        response = FileResponse(
            file,
            as_attachment=True,
            filename=f"{message.ticket.reference}-{message.id.hex[:8]}.eml",
            content_type="message/rfc822",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response
