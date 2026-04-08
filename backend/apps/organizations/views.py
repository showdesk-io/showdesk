"""Views for organization-related models."""

import uuid

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsPlatformAdmin, get_active_org

from .models import Organization, Team, User
from .serializers import (
    InviteAgentSerializer,
    OrganizationSerializer,
    PlatformOrganizationCreateSerializer,
    PlatformOrganizationDetailSerializer,
    PlatformOrganizationListSerializer,
    TeamSerializer,
    UserSerializer,
)


class OrganizationViewSet(viewsets.ModelViewSet):
    """ViewSet for managing organizations (tenant-scoped)."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter organizations by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Organization.objects.filter(id=org.id)
        return Organization.objects.none()

    @action(detail=True, methods=["post"])
    def regenerate_token(self, request, pk=None):  # noqa: ANN001, ANN201
        """Regenerate the organization's widget API token."""
        org = self.get_object()
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can regenerate the API token."},
                status=status.HTTP_403_FORBIDDEN,
            )
        org.api_token = uuid.uuid4()
        org.save(update_fields=["api_token"])
        return Response(OrganizationSerializer(org).data)


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for managing users."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter users by the current user's organization.

        Superusers with an org see their org's users.
        Superusers without an org see no users (use platform admin endpoints).
        Supports ?role=agent|admin|end_user filtering.
        """
        org = get_active_org(self.request)
        if org:
            qs = User.objects.filter(organization=org)
        else:
            qs = User.objects.none()

        role = self.request.query_params.get("role")
        if role:
            if role == "agent":
                qs = qs.filter(role__in=[User.Role.AGENT, User.Role.ADMIN])
            else:
                qs = qs.filter(role=role)
        return qs

    @action(detail=False, methods=["get"])
    def me(self, request):  # noqa: ANN001, ANN201
        """Return the currently authenticated user."""
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"])
    def invite(self, request):  # noqa: ANN001, ANN201
        """Invite a new agent to the current organization.

        Creates the user with an unusable password. They log in via OTP.
        Sends an invitation email.
        """
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can invite agents."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InviteAgentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org = get_active_org(request)
        if not org:
            return Response(
                {"error": "No active organization."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.create(
            email=serializer.validated_data["email"],
            first_name=serializer.validated_data.get("first_name", ""),
            last_name=serializer.validated_data.get("last_name", ""),
            role=serializer.validated_data.get("role", User.Role.AGENT),
            organization=org,
        )
        user.set_unusable_password()
        user.save()

        # Send invitation email
        try:
            send_mail(
                subject=f"You've been invited to {org.name} on Showdesk",
                message=(
                    f"Hi {user.first_name or user.email},\n\n"
                    f"You've been invited to join {org.name} on Showdesk.\n\n"
                    f"Log in with your email ({user.email}) "
                    f"-- you'll receive an OTP code.\n\n"
                    f"-- The Showdesk team"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:  # noqa: BLE001
            pass

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def toggle_active(self, request, pk=None):  # noqa: ANN001, ANN201
        """Activate or deactivate a user."""
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can change user status."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = self.get_object()
        if user.id == request.user.id:
            return Response(
                {"error": "You cannot deactivate yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        return Response(UserSerializer(user).data)


class TeamViewSet(viewsets.ModelViewSet):
    """ViewSet for managing teams."""

    serializer_class = TeamSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter teams by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Team.objects.filter(organization=org)
        return Team.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization on creation."""
        serializer.save(organization=get_active_org(self.request))


class PlatformOrganizationViewSet(viewsets.ModelViewSet):
    """ViewSet for platform admins to manage all organizations."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    queryset = Organization.objects.all()

    def get_serializer_class(self):  # noqa: ANN201
        if self.action == "list":
            return PlatformOrganizationListSerializer
        if self.action == "create":
            return PlatformOrganizationCreateSerializer
        return PlatformOrganizationDetailSerializer

    def get_queryset(self):  # noqa: ANN201
        qs = Organization.objects.annotate(
            _agent_count=Count(
                "users",
                filter=Q(users__role__in=["admin", "agent"], users__is_active=True),
            ),
            _ticket_count=Count("tickets"),
        )
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(slug__icontains=search)
                | Q(domain__icontains=search)
            )
        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):  # noqa: ANN001, ANN201
        """Toggle the active status of an organization."""
        org = self.get_object()
        org.is_active = not org.is_active
        org.save(update_fields=["is_active"])
        return Response(PlatformOrganizationDetailSerializer(org).data)

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):  # noqa: ANN001, ANN201
        """Return usage statistics for an organization."""
        org = self.get_object()
        tickets = org.tickets.all()
        agents = org.users.filter(role__in=["admin", "agent"])

        ticket_stats = {
            "total": tickets.count(),
            "open": tickets.filter(status="open").count(),
            "in_progress": tickets.filter(status="in_progress").count(),
            "waiting": tickets.filter(status="waiting").count(),
            "resolved": tickets.filter(status="resolved").count(),
            "closed": tickets.filter(status="closed").count(),
        }

        agent_stats = {
            "total": agents.count(),
            "active": agents.filter(is_active=True).count(),
            "inactive": agents.filter(is_active=False).count(),
        }

        video_count = 0
        try:
            from apps.videos.models import VideoRecording

            video_count = VideoRecording.objects.filter(
                ticket__organization=org
            ).count()
        except ImportError:
            pass

        return Response(
            {
                "tickets": ticket_stats,
                "agents": agent_stats,
                "videos": {"total": video_count},
                "teams": org.teams.count(),
                "tags": org.tags.count(),
            }
        )
