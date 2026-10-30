"""Permissions of the contacts API."""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

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


def require_org_admin(user) -> None:
    if user.role != User.Role.ADMIN and not user.is_superuser:
        raise PermissionDenied("Only admins can perform this action.")
