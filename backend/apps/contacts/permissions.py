"""Permissions of the contacts API."""

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.permissions import get_active_org, impersonates_no_organization
from apps.organizations.models import User


class IsNotEndUser(BasePermission):
    """Refuse end users. A superuser's role means nothing: it defaults to end user."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return user.role != User.Role.END_USER or user.is_superuser


class IsOrganizationStaff(IsNotEndUser):
    """Allow an organization's agents and admins, not its end users.

    The API needs an active organization: a superuser without one has to
    impersonate one first. An impersonation that doesn't resolve is refused rather
    than falling back on the superuser's own organization, which would answer or
    write for an organization other than the one asked for.
    """

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if impersonates_no_organization(request):
            raise ValidationError({"detail": "Unknown organization."})
        return get_active_org(request) is not None


def is_org_admin(user) -> bool:
    return user.role == User.Role.ADMIN or user.is_superuser


class IsOrganizationAdminOrReadOnly(BasePermission):
    """Let admins write. Checked before validation, so that an agent's answer doesn't
    depend on the body sent, and doesn't tell what the validation would have refused.
    """

    def has_permission(self, request, view) -> bool:
        return request.method in SAFE_METHODS or is_org_admin(request.user)


def require_org_admin(user) -> None:
    if not is_org_admin(user):
        raise PermissionDenied("Only admins can perform this action.")
