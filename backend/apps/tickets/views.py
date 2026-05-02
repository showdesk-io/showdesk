"""Views for ticket-related models."""

import logging

from django.db import models
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from apps.core.permissions import get_active_org
from rest_framework.parsers import FormParser, MultiPartParser
from apps.core.throttling import (
    WidgetMessageThrottle,
    WidgetSessionThrottle,
    WidgetSubmitThrottle,
    WidgetUploadThrottle,
)
from apps.notifications.signals import (
    notify_message_deleted,
    notify_new_message,
    notify_new_ticket,
    notify_ticket_update,
)
from apps.organizations.models import Organization

from .models import (
    CannedResponse,
    PriorityLevel,
    SavedView,
    Tag,
    Ticket,
    TicketAttachment,
    TicketMessage,
    WidgetSession,
)
from .serializers import (
    CannedResponseSerializer,
    PriorityLevelSerializer,
    SavedViewSerializer,
    TagSerializer,
    TicketAttachmentSerializer,
    TicketCreateFromWidgetSerializer,
    TicketListSerializer,
    TicketMessageSerializer,
    TicketSerializer,
    WidgetConversationListSerializer,
    WidgetMessageCreateSerializer,
    WidgetMessageSerializer,
    WidgetSessionSerializer,
)
from .tasks import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_reply_email,
    send_ticket_resolved_email,
)

logger = logging.getLogger(__name__)


def _get_widget_org(request):
    """Validate X-Widget-Token header and return the Organization.

    Returns (organization, None) on success, or (None, Response) on failure.
    """
    token = request.headers.get("X-Widget-Token")
    if not token:
        return None, Response(
            {"error": "Missing X-Widget-Token header."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        org = Organization.objects.get(api_token=token, is_active=True)
    except Organization.DoesNotExist:
        return None, Response(
            {"error": "Invalid or inactive organization token."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    # Stamp the first widget call so the onboarding wizard can flip from
    # "Waiting for first ping" to "Widget detected". Single UPDATE keyed on
    # the still-null state to avoid a race with concurrent first calls.
    if org.widget_first_seen_at is None:
        now = timezone.now()
        updated = Organization.objects.filter(
            pk=org.pk, widget_first_seen_at__isnull=True
        ).update(widget_first_seen_at=now)
        if updated:
            org.widget_first_seen_at = now
    return org, None


def _get_widget_session(request, organization):
    """Validate X-Widget-Session header and return the WidgetSession.

    Returns (session, None) on success, or (None, Response) on failure.
    """
    session_id = request.headers.get("X-Widget-Session")
    if not session_id:
        return None, Response(
            {"error": "Missing X-Widget-Session header."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        session = WidgetSession.objects.get(id=session_id, organization=organization)
    except (WidgetSession.DoesNotExist, ValueError):
        return None, Response(
            {"error": "Invalid session."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    return session, None


class TicketViewSet(viewsets.ModelViewSet):
    """ViewSet for managing tickets.

    Supports full CRUD operations, filtering by status/priority/assignee,
    and a special widget submission endpoint.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "status",
        "priority",
        "assigned_agent",
        "assigned_team",
        "source",
        "tags",
        "external_user_id",
    ]
    search_fields = ["title", "description", "reference", "requester_email"]
    ordering_fields = ["created_at", "updated_at", "priority", "status"]

    def get_serializer_class(self):  # noqa: ANN201
        """Use list serializer for list action."""
        if self.action == "list":
            return TicketListSerializer
        return TicketSerializer

    def get_queryset(self):  # noqa: ANN201
        """Filter tickets by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Ticket.objects.filter(organization=org)
        return Ticket.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization and reference on creation."""
        org = get_active_org(self.request)
        ticket = serializer.save(
            organization=org,
            reference=org.next_ticket_reference(),
        )
        # Notify via WebSocket + email
        try:
            notify_new_ticket(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        send_ticket_created_email.delay(str(ticket.id))

    @action(detail=False, methods=["get"])
    def stats(self, request):  # noqa: ANN001, ANN201
        """Return aggregated statistics for the current filtered queryset.

        Accepts the same filter params as the list endpoint (status, priority,
        assigned_agent, assigned_team, tags, search). Returns breakdowns by
        status, priority, and agent workload.
        """
        qs = self.filter_queryset(self.get_queryset())
        total = qs.count()

        # Status breakdown
        status_counts = dict(
            qs.values_list("status")
            .annotate(count=models.Count("id"))
            .values_list("status", "count")
        )

        # Priority breakdown
        priority_counts = dict(
            qs.values_list("priority")
            .annotate(count=models.Count("id"))
            .values_list("priority", "count")
        )

        # Agent workload (top agents by ticket count)
        agent_rows = (
            qs.filter(assigned_agent__isnull=False)
            .values(
                "assigned_agent",
                "assigned_agent__first_name",
                "assigned_agent__last_name",
                "assigned_agent__email",
            )
            .annotate(count=models.Count("id"))
            .order_by("-count")[:10]
        )
        agent_workload = [
            {
                "agent_id": str(row["assigned_agent"]),
                "name": f"{row['assigned_agent__first_name']} {row['assigned_agent__last_name']}".strip()
                or row["assigned_agent__email"],
                "count": row["count"],
            }
            for row in agent_rows
        ]
        unassigned = qs.filter(assigned_agent__isnull=True).count()

        # Average age in hours
        from django.db.models import Avg
        from django.db.models.functions import Now

        avg_age = qs.aggregate(avg_age=Avg(Now() - models.F("created_at")))["avg_age"]
        avg_age_hours = round(avg_age.total_seconds() / 3600, 1) if avg_age else 0

        return Response(
            {
                "total": total,
                "by_status": status_counts,
                "by_priority": priority_counts,
                "agent_workload": agent_workload,
                "unassigned": unassigned,
                "avg_age_hours": avg_age_hours,
            }
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetSubmitThrottle],
    )
    def widget_submit(self, request):  # noqa: ANN001, ANN201
        """Submit a ticket from the embeddable widget.

        Authenticates via organization API token passed in the
        X-Widget-Token header.
        """
        token = request.headers.get("X-Widget-Token")
        if not token:
            return Response(
                {"error": "Missing X-Widget-Token header."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            organization = Organization.objects.get(api_token=token, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive organization token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = TicketCreateFromWidgetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.save(
            organization=organization,
            reference=organization.next_ticket_reference(),
            source=Ticket.Source.WIDGET,
        )

        # Notify via WebSocket + email
        try:
            notify_new_ticket(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        send_ticket_created_email.delay(str(ticket.id))

        return Response(
            TicketSerializer(ticket).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetUploadThrottle],
        parser_classes=[MultiPartParser, FormParser],
    )
    def widget_upload_attachment(self, request):  # noqa: ANN001, ANN201
        """Upload a file attachment from the widget.

        Authenticates via X-Widget-Token header.
        Expects multipart form data with `ticket` (UUID) and `file`.
        """
        token = request.headers.get("X-Widget-Token")
        if not token:
            return Response(
                {"error": "Missing X-Widget-Token header."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            organization = Organization.objects.get(api_token=token, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive organization token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        ticket_id = request.data.get("ticket")
        uploaded_file = request.FILES.get("file")

        if not ticket_id or not uploaded_file:
            return Response(
                {"error": "Both 'ticket' and 'file' fields are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ticket = Ticket.objects.get(id=ticket_id, organization=organization)
        except Ticket.DoesNotExist:
            return Response(
                {"error": "Ticket not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TicketAttachmentSerializer(
            data={
                "ticket": str(ticket.id),
                "file": uploaded_file,
                "filename": uploaded_file.name,
                "content_type": uploaded_file.content_type
                or "application/octet-stream",
                "file_size": uploaded_file.size,
            }
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(uploaded_by=None)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
    )
    def widget_tickets(self, request):  # noqa: ANN001, ANN201
        """Fetch tickets for a user from the widget.

        Authenticates via X-Widget-Token header.
        Requires ?external_user_id=xxx and ?user_hash=xxx query parameters.
        The user_hash is verified via HMAC-SHA256(widget_secret, external_user_id)
        to prevent enumeration of other users' tickets.
        """
        token = request.headers.get("X-Widget-Token")
        if not token:
            return Response(
                {"error": "Missing X-Widget-Token header."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            organization = Organization.objects.get(api_token=token, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive organization token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        external_user_id = request.query_params.get("external_user_id")
        if not external_user_id:
            return Response(
                {"error": "external_user_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # HMAC identity verification: require user_hash when widget_secret is set
        user_hash = request.query_params.get("user_hash")
        if not organization.widget_secret:
            return Response(
                {
                    "error": "Identity verification not configured. Generate a widget secret in Settings."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user_hash:
            return Response(
                {"error": "user_hash query parameter is required for ticket history."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not organization.verify_user_hash(external_user_id, user_hash):
            return Response(
                {"error": "Invalid user_hash."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tickets = Ticket.objects.filter(
            organization=organization,
            external_user_id=external_user_id,
        ).order_by("-created_at")[:20]

        from .serializers import WidgetTicketListSerializer

        serializer = WidgetTicketListSerializer(tickets, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):  # noqa: ANN001, ANN201
        """Assign a ticket to an agent or team."""
        ticket = self.get_object()
        agent_id = request.data.get("agent_id")
        team_id = request.data.get("team_id")

        if agent_id:
            ticket.assigned_agent_id = agent_id
        if team_id:
            ticket.assigned_team_id = team_id
        if not ticket.first_response_at and agent_id:
            ticket.first_response_at = timezone.now()

        ticket.status = Ticket.Status.IN_PROGRESS
        ticket.save()

        # Notify
        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        if agent_id:
            send_ticket_assigned_email.delay(str(ticket.id))

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):  # noqa: ANN001, ANN201
        """Mark a ticket as resolved."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.save()

        # Notify
        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        send_ticket_resolved_email.delay(str(ticket.id))

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):  # noqa: ANN001, ANN201
        """Close a ticket."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.CLOSED
        ticket.closed_at = timezone.now()
        ticket.save()

        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):  # noqa: ANN001, ANN201
        """Reopen a resolved or closed ticket."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.OPEN
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.save()

        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def set_tags(self, request, pk=None):  # noqa: ANN001, ANN201
        """Set tags on a ticket (replaces existing tags)."""
        ticket = self.get_object()
        tag_ids = request.data.get("tag_ids", [])

        # Validate that tags belong to the same org
        tags = Tag.objects.filter(
            id__in=tag_ids,
            organization=ticket.organization,
        )
        ticket.tags.set(tags)

        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)

        return Response(TicketSerializer(ticket).data)

    # ------------------------------------------------------------------
    # Widget messaging endpoints (chat-style)
    # ------------------------------------------------------------------

    @action(
        detail=False,
        methods=["post", "patch"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetSessionThrottle],
        url_path="widget_session",
    )
    def widget_session(self, request):  # noqa: ANN001, ANN201
        """Create, resume, or update a widget session.

        POST: Create a new session or resume an existing one.
        PATCH: Update contact info (name/email) on an existing session.
        """
        org, err = _get_widget_org(request)
        if err:
            return err

        if request.method == "PATCH":
            session, err = _get_widget_session(request, org)
            if err:
                return err
            name = request.data.get("name")
            email = request.data.get("email")
            if name is not None:
                session.name = name
            if email is not None:
                session.email = email
            session.save(update_fields=["name", "email", "last_seen_at"])
            # Backfill on linked tickets with blank requester info
            if session.name or session.email:
                update_fields = {}
                if session.name:
                    update_fields["requester_name"] = session.name
                if session.email:
                    update_fields["requester_email"] = session.email
                Ticket.objects.filter(
                    widget_session=session,
                    requester_name="",
                ).update(**update_fields)
            return Response(WidgetSessionSerializer(session).data)

        # POST — create or resume
        session_id = request.data.get("session_id")
        external_user_id = request.data.get("external_user_id", "")
        user_hash = request.data.get("user_hash", "")
        name = request.data.get("name", "")
        email = request.data.get("email", "")

        # Try to resume existing session
        if session_id:
            try:
                session = WidgetSession.objects.get(id=session_id, organization=org)
            except (WidgetSession.DoesNotExist, ValueError):
                session = None

            # Identity mismatch (e.g. a different user logged into the same
            # browser): drop the stored session_id and fall through so the
            # HMAC branch finds-or-creates the legitimate session for this
            # user. Anonymous sessions (no external_user_id) can still be
            # claimed by an identified user on the next branch.
            if (
                session is not None
                and session.external_user_id
                and external_user_id
                and session.external_user_id != external_user_id
            ):
                session = None

            if session is not None:
                session.last_seen_at = timezone.now()
                if name and not session.name:
                    session.name = name
                if email and not session.email:
                    session.email = email
                session.save()
                return Response(WidgetSessionSerializer(session).data)

        # HMAC-identified user: find-or-create by external_user_id
        if external_user_id and user_hash:
            if not org.widget_secret:
                return Response(
                    {"error": "Identity verification not configured."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not org.verify_user_hash(external_user_id, user_hash):
                return Response(
                    {"error": "Invalid user_hash."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            session, created = WidgetSession.objects.get_or_create(
                organization=org,
                external_user_id=external_user_id,
                defaults={
                    "name": name,
                    "email": email,
                    "user_agent": request.META.get("HTTP_USER_AGENT", ""),
                },
            )
            if not created:
                session.last_seen_at = timezone.now()
                if name and not session.name:
                    session.name = name
                if email and not session.email:
                    session.email = email
                session.save()
            resp_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return Response(WidgetSessionSerializer(session).data, status=resp_status)

        # Anonymous session
        session = WidgetSession.objects.create(
            organization=org,
            name=name,
            email=email,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(
            WidgetSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetMessageThrottle],
        url_path="widget_message",
    )
    def widget_message(self, request):  # noqa: ANN001, ANN201
        """Send a chat message from the widget.

        Creates a ticket on the first message (when ticket_id is null).
        Subsequent messages are appended to the existing ticket.
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        serializer = WidgetMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ticket_id = data.get("ticket_id")
        body = data.get("body", "")
        body_type = data.get("body_type", "text")
        context_data = data.get("context", {})

        # Create or retrieve ticket
        if ticket_id:
            try:
                ticket = Ticket.objects.get(
                    id=ticket_id,
                    organization=org,
                    widget_session=session,
                )
            except Ticket.DoesNotExist:
                return Response(
                    {"error": "Ticket not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            # First message — create ticket
            title = body[:100] if body else f"[{body_type.capitalize()}]"
            ticket = Ticket.objects.create(
                organization=org,
                reference=org.next_ticket_reference(),
                title=title,
                description=body,
                source=Ticket.Source.WIDGET,
                widget_session=session,
                requester_name=session.name,
                requester_email=session.email,
                external_user_id=session.external_user_id,
                context_url=context_data.get("url", ""),
                context_user_agent=context_data.get("user_agent", ""),
                context_os=context_data.get("os", ""),
                context_browser=context_data.get("browser", ""),
                context_screen_resolution=context_data.get("screen_resolution", ""),
                context_metadata={
                    k: v
                    for k, v in context_data.items()
                    if k
                    not in (
                        "url",
                        "user_agent",
                        "os",
                        "browser",
                        "screen_resolution",
                    )
                },
            )
            try:
                notify_new_ticket(ticket)
            except Exception:
                logger.exception(
                    "WebSocket notification failed for %s", ticket.reference
                )
            send_ticket_created_email.delay(str(ticket.id))

        # Create message
        message = TicketMessage.objects.create(
            ticket=ticket,
            widget_session=session,
            sender_type=TicketMessage.SenderType.USER,
            body=body,
            body_type=body_type,
        )

        try:
            notify_new_message(message)
        except Exception:
            logger.exception("WebSocket notification failed for message %s", message.id)

        return Response(
            {
                "ticket_id": str(ticket.id),
                "message_id": str(message.id),
                "reference": ticket.reference,
                "created_at": message.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetUploadThrottle],
        parser_classes=[MultiPartParser, FormParser],
        url_path="widget_message_attachment",
    )
    def widget_message_attachment(self, request):  # noqa: ANN001, ANN201
        """Upload a media attachment as a chat message from the widget.

        Supports screenshots, audio messages, images, and video recordings.
        Creates a ticket on the first message if ticket_id is not provided.
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"error": "'file' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ticket_id = request.data.get("ticket_id")
        body_type = request.data.get("body_type", "image")
        body = request.data.get("body", "")

        # Create or retrieve ticket
        if ticket_id:
            try:
                ticket = Ticket.objects.get(
                    id=ticket_id,
                    organization=org,
                    widget_session=session,
                )
            except Ticket.DoesNotExist:
                return Response(
                    {"error": "Ticket not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            title = body[:100] if body else f"[{body_type.capitalize()}]"
            ticket = Ticket.objects.create(
                organization=org,
                reference=org.next_ticket_reference(),
                title=title,
                description=body,
                source=Ticket.Source.WIDGET,
                widget_session=session,
                requester_name=session.name,
                requester_email=session.email,
                external_user_id=session.external_user_id,
            )
            try:
                notify_new_ticket(ticket)
            except Exception:
                logger.exception(
                    "WebSocket notification failed for %s", ticket.reference
                )
            send_ticket_created_email.delay(str(ticket.id))

        # Create message
        message = TicketMessage.objects.create(
            ticket=ticket,
            widget_session=session,
            sender_type=TicketMessage.SenderType.USER,
            body=body,
            body_type=body_type,
        )

        # Validate and save attachment
        att_serializer = TicketAttachmentSerializer(
            data={
                "ticket": str(ticket.id),
                "message": str(message.id),
                "file": uploaded_file,
                "filename": uploaded_file.name,
                "content_type": uploaded_file.content_type
                or "application/octet-stream",
                "file_size": uploaded_file.size,
            }
        )
        att_serializer.is_valid(raise_exception=True)
        att_serializer.save(uploaded_by=None)

        # For video uploads, also create VideoRecording
        if body_type == "video":
            from apps.videos.models import VideoRecording

            video = VideoRecording.objects.create(
                ticket=ticket,
                original_file=uploaded_file,
                status=VideoRecording.Status.UPLOADING,
                recording_type=request.data.get("recording_type", "screen"),
                has_audio=request.data.get("has_audio", "false").lower() == "true",
                has_camera=request.data.get("has_camera", "false").lower() == "true",
                mime_type=uploaded_file.content_type or "video/webm",
                file_size=uploaded_file.size,
            )
            from apps.videos.tasks import process_video

            process_video.delay(str(video.id))

        try:
            notify_new_message(message)
        except Exception:
            logger.exception("WebSocket notification failed for message %s", message.id)

        return Response(
            {
                "ticket_id": str(ticket.id),
                "message_id": str(message.id),
                "reference": ticket.reference,
                "attachment": att_serializer.data,
                "created_at": message.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
        url_path="widget_conversation",
    )
    def widget_conversation(self, request):  # noqa: ANN001, ANN201
        """Fetch messages for a specific conversation from the widget."""
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        ticket_id = request.query_params.get("ticket_id")
        if not ticket_id:
            return Response(
                {"error": "ticket_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ticket = Ticket.objects.get(
                id=ticket_id,
                organization=org,
                widget_session=session,
            )
        except (Ticket.DoesNotExist, ValueError):
            return Response(
                {"error": "Ticket not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        messages = (
            ticket.messages.filter(message_type=TicketMessage.MessageType.REPLY)
            .select_related("author", "widget_session")
            .prefetch_related("attachments")
            .order_by("created_at")
        )

        serializer = WidgetMessageSerializer(messages, many=True)
        return Response(
            {
                "ticket_id": str(ticket.id),
                "reference": ticket.reference,
                "status": ticket.status,
                "messages": serializer.data,
            }
        )

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
        url_path="widget_history",
    )
    def widget_history(self, request):  # noqa: ANN001, ANN201
        """Fetch conversation history for the current widget session."""
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        # Find tickets by session, or by external_user_id for cross-session history
        q = models.Q(widget_session=session)
        if session.external_user_id:
            q |= models.Q(
                external_user_id=session.external_user_id,
                organization=org,
            )

        tickets = Ticket.objects.filter(q).order_by("-updated_at")[:30]
        serializer = WidgetConversationListSerializer(tickets, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        url_path="widget_mark_read",
    )
    def widget_mark_read(self, request):  # noqa: ANN001, ANN201
        """Mark a widget conversation as read up to `now`.

        The end-user has just opened this ticket in the widget, so agent
        replies up to this moment are no longer unread.
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        ticket_id = request.data.get("ticket_id")
        if not ticket_id:
            return Response(
                {"error": "ticket_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ticket = Ticket.objects.get(
                id=ticket_id,
                organization=org,
                widget_session=session,
            )
        except (Ticket.DoesNotExist, ValueError):
            return Response(
                {"error": "Ticket not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        ticket.widget_last_read_at = timezone.now()
        ticket.save(update_fields=["widget_last_read_at"])
        return Response({"ticket_id": str(ticket.id), "status": "ok"})

    @action(
        detail=False,
        methods=["delete"],
        permission_classes=[AllowAny],
        url_path="widget_message_delete",
    )
    def widget_message_delete(self, request):  # noqa: ANN001, ANN201
        """Delete a user message from the widget.

        Only the session that created the message can delete it.
        Only user-sent messages can be deleted (not agent replies).
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        message_id = request.query_params.get("message_id")
        if not message_id:
            return Response(
                {"error": "message_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            message = TicketMessage.objects.get(
                id=message_id,
                widget_session=session,
                ticket__organization=org,
            )
        except (TicketMessage.DoesNotExist, ValueError):
            return Response(
                {"error": "Message not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if message.sender_type != TicketMessage.SenderType.USER:
            return Response(
                {"error": "Only user messages can be deleted."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Keep references before deleting
        ticket = message.ticket
        deleted_message_id = str(message.id)

        # Delete associated attachments (files on storage) and the message
        message.attachments.all().delete()
        message.delete()

        try:
            notify_message_deleted(ticket, deleted_message_id)
        except Exception:
            logger.exception(
                "WebSocket notification failed for deleted message %s",
                deleted_message_id,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class TicketMessageViewSet(viewsets.ModelViewSet):
    """ViewSet for managing ticket messages."""

    serializer_class = TicketMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter messages by the active organization's tickets."""
        org = get_active_org(self.request)
        if org:
            return TicketMessage.objects.filter(ticket__organization=org)
        return TicketMessage.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set author on creation and send notifications."""
        message = serializer.save(author=self.request.user)

        # WebSocket notification
        try:
            notify_new_message(message)
        except Exception:
            logger.exception("WebSocket notification failed for message %s", message.id)

        # Email notification (async via Celery)
        send_ticket_reply_email.delay(str(message.id))

    def perform_destroy(self, instance) -> None:  # noqa: ANN001
        """Delete message and send WebSocket notification."""
        ticket = instance.ticket
        message_id = str(instance.id)
        instance.delete()
        try:
            notify_message_deleted(ticket, message_id)
        except Exception:
            logger.exception(
                "WebSocket notification failed for deleted message %s", message_id
            )


class TicketAttachmentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing ticket attachments."""

    serializer_class = TicketAttachmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter attachments by the active organization's tickets."""
        org = get_active_org(self.request)
        if org:
            return TicketAttachment.objects.filter(ticket__organization=org)
        return TicketAttachment.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set uploaded_by on creation."""
        serializer.save(uploaded_by=self.request.user)


class TagViewSet(viewsets.ModelViewSet):
    """ViewSet for managing tags."""

    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter tags by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Tag.objects.filter(organization=org)
        return Tag.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization from the active org."""
        serializer.save(organization=get_active_org(self.request))


class PriorityLevelViewSet(viewsets.ModelViewSet):
    """ViewSet for managing custom priority levels."""

    serializer_class = PriorityLevelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter priority levels by the active organization."""
        org = get_active_org(self.request)
        if org:
            return PriorityLevel.objects.filter(organization=org)
        return PriorityLevel.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization from the active org."""
        serializer.save(organization=get_active_org(self.request))


class SavedViewViewSet(viewsets.ModelViewSet):
    """ViewSet for managing saved ticket filter views.

    Returns views owned by the current user plus shared views from the
    same organization. Only the creator can update or delete a view.
    """

    serializer_class = SavedViewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Return personal views + shared views from the active org."""
        user = self.request.user
        org = get_active_org(self.request)
        if org:
            return SavedView.objects.filter(
                organization=org,
            ).filter(
                models.Q(created_by=user) | models.Q(is_shared=True),
            )
        return SavedView.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization and creator."""
        serializer.save(
            organization=get_active_org(self.request),
            created_by=self.request.user,
        )

    def perform_update(self, serializer) -> None:  # noqa: ANN001
        """Only the creator can update a saved view."""
        if serializer.instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You can only edit your own saved views.")
        serializer.save()

    def perform_destroy(self, instance) -> None:  # noqa: ANN001
        """Only the creator can delete a saved view."""
        if instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You can only delete your own saved views.")
        instance.delete()


class CannedResponseViewSet(viewsets.ModelViewSet):
    """ViewSet for managing reusable reply templates.

    Returns templates owned by the current user plus shared templates from
    the same organization. Only the creator can update or delete a template.
    """

    serializer_class = CannedResponseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "shortcut", "body"]

    def get_queryset(self):  # noqa: ANN201
        """Return personal templates + shared templates from the active org."""
        user = self.request.user
        org = get_active_org(self.request)
        if org:
            return CannedResponse.objects.filter(
                organization=org,
            ).filter(
                models.Q(created_by=user) | models.Q(is_shared=True),
            )
        return CannedResponse.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization and creator."""
        serializer.save(
            organization=get_active_org(self.request),
            created_by=self.request.user,
        )

    def perform_update(self, serializer) -> None:  # noqa: ANN001
        """Only the creator can update a canned response."""
        if serializer.instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "You can only edit your own canned responses.",
            )
        serializer.save()

    def perform_destroy(self, instance) -> None:  # noqa: ANN001
        """Only the creator can delete a canned response."""
        if instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "You can only delete your own canned responses.",
            )
        instance.delete()

    @action(detail=True, methods=["post"], url_path="record-use")
    def record_use(self, request, pk=None):  # noqa: ANN001, ANN201, ARG002
        """Increment usage_count when a template is inserted."""
        instance = self.get_object()
        CannedResponse.objects.filter(pk=instance.pk).update(
            usage_count=models.F("usage_count") + 1,
        )
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
