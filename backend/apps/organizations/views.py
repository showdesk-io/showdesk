"""Views for organization-related models."""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Organization, Team, User
from .serializers import (
    OrganizationSerializer,
    TeamSerializer,
    UserCreateSerializer,
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


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for managing users."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):  # noqa: ANN201
        """Use different serializer for creation."""
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):  # noqa: ANN201
        """Filter users by the current user's organization."""
        user = self.request.user
        if user.is_superuser:
            return User.objects.all()
        if user.organization:
            return User.objects.filter(organization=user.organization)
        return User.objects.none()


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
