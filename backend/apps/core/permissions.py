"""Reusable permission classes and helpers for the Showdesk platform."""

from rest_framework.permissions import BasePermission


class IsPlatformAdmin(BasePermission):
    """Allow access only to platform administrators (superusers)."""

    def has_permission(self, request, view):  # noqa: ANN001, ANN201
        return request.user and request.user.is_authenticated and request.user.is_superuser


def get_active_org(request):  # noqa: ANN001, ANN201
    """Return the effective organization for the current request.

    For superusers with an impersonated org (via X-Showdesk-Org header),
    returns the impersonated org. Otherwise returns the user's own org.
    """
    impersonated = getattr(request, "impersonated_org", None)
    if impersonated and request.user.is_superuser:
        return impersonated
    return request.user.organization
