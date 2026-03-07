"""Views for organization-related models."""

import uuid

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Organization, Team, User
from .serializers import (
    InviteAgentSerializer,
    OrganizationSerializer,
    TeamSerializer,
    UserSerializer,
)


class OrganizationViewSet(viewsets.ModelViewSet):
    """ViewSet for managing organizations."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter organizations by the current user's organization."""
        user = self.request.user
        if user.is_superuser:
            return Organization.objects.all()
        if user.organization:
            return Organization.objects.filter(id=user.organization_id)
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

        Supports ?role=agent|admin|end_user filtering.
        """
        user = self.request.user
        if user.is_superuser:
            qs = User.objects.all()
        elif user.organization:
            qs = User.objects.filter(organization=user.organization)
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

        org = request.user.organization
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
        """Filter teams by the current user's organization."""
        user = self.request.user
        if user.is_superuser:
            return Team.objects.all()
        if user.organization:
            return Team.objects.filter(organization=user.organization)
        return Team.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization on creation."""
        serializer.save(organization=self.request.user.organization)
