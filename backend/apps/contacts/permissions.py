"""Permissions of the contacts API."""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.permissions import get_active_org
from apps.organizations.models import User


class IsOrganizationStaff(BasePermission):
    """Allow an organization's agents and admins, not its end users.

    The API needs an active organization: a superuser without one has to
    impersonate one first.
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        if user.role == User.Role.END_USER and not user.is_superuser:
            return False
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
