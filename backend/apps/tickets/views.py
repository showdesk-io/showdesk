"""Views for ticket-related models."""

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.organizations.models import Organization

from .models import Tag, Ticket, TicketAttachment, TicketMessage
from .serializers import (
    TagSerializer,
    TicketAttachmentSerializer,
    TicketCreateFromWidgetSerializer,
    TicketListSerializer,
    TicketMessageSerializer,
    TicketSerializer,
)


class TicketViewSet(viewsets.ModelViewSet):
    """ViewSet for managing tickets.

    Supports full CRUD operations, filtering by status/priority/assignee,
    and a special widget submission endpoint.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "priority", "assigned_agent", "assigned_team", "source"]
    search_fields = ["title", "description", "reference", "requester_email"]
    ordering_fields = ["created_at", "updated_at", "priority", "status"]

    def get_serializer_class(self):  # noqa: ANN201
        """Use list serializer for list action."""
        if self.action == "list":
            return TicketListSerializer
        return TicketSerializer

    def get_queryset(self):  # noqa: ANN201
        """Filter tickets by the current user's organization."""
        user = self.request.user
        if user.is_superuser:
            return Ticket.objects.all()
        if user.organization:
            return Ticket.objects.filter(organization=user.organization)
        return Ticket.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization and reference on creation."""
        org = self.request.user.organization
        serializer.save(
            organization=org,
            reference=org.next_ticket_reference(),
        )

    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
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
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):  # noqa: ANN001, ANN201
        """Mark a ticket as resolved."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.save()
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):  # noqa: ANN001, ANN201
        """Close a ticket."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.CLOSED
        ticket.closed_at = timezone.now()
        ticket.save()
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):  # noqa: ANN001, ANN201
        """Reopen a resolved or closed ticket."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.OPEN
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.save()
        return Response(TicketSerializer(ticket).data)


class TicketMessageViewSet(viewsets.ModelViewSet):
    """ViewSet for managing ticket messages."""

    serializer_class = TicketMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter messages by user's organization tickets."""
        user = self.request.user
        if user.is_superuser:
            return TicketMessage.objects.all()
        if user.organization:
            return TicketMessage.objects.filter(
                ticket__organization=user.organization
            )
        return TicketMessage.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set author on creation."""
        serializer.save(author=self.request.user)


class TicketAttachmentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing ticket attachments."""

    serializer_class = TicketAttachmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter attachments by user's organization tickets."""
        user = self.request.user
        if user.is_superuser:
            return TicketAttachment.objects.all()
        if user.organization:
            return TicketAttachment.objects.filter(
                ticket__organization=user.organization
            )
        return TicketAttachment.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set uploaded_by on creation."""
        serializer.save(uploaded_by=self.request.user)


class TagViewSet(viewsets.ModelViewSet):
    """ViewSet for managing tags."""

    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter tags by user's organization."""
        user = self.request.user
        if user.is_superuser:
            return Tag.objects.all()
        if user.organization:
            return Tag.objects.filter(organization=user.organization)
        return Tag.objects.none()
