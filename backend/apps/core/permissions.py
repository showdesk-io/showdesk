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

    Note: This resolves the header lazily at call time (in the ViewSet),
    because DRF JWT authentication runs after Django middleware.
    """
    if request.user.is_superuser:
        org_id = request.META.get("HTTP_X_SHOWDESK_ORG")
        if org_id:
            from apps.organizations.models import Organization

            try:
                return Organization.objects.get(id=org_id)
            except (Organization.DoesNotExist, ValueError):
                pass
    return request.user.organization
