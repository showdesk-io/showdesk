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
from apps.core.throttling import WidgetSubmitThrottle
from apps.notifications.signals import (
    notify_new_message,
    notify_new_ticket,
    notify_ticket_update,
)
from apps.organizations.models import Organization

from .models import (
    PriorityLevel,
    SavedView,
    Tag,
    Ticket,
    TicketAttachment,
    TicketMessage,
)
from .serializers import (
    PriorityLevelSerializer,
    SavedViewSerializer,
    TagSerializer,
    TicketAttachmentSerializer,
    TicketCreateFromWidgetSerializer,
    TicketListSerializer,
    TicketMessageSerializer,
    TicketSerializer,
)
from .tasks import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_reply_email,
    send_ticket_resolved_email,
)

logger = logging.getLogger(__name__)


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
