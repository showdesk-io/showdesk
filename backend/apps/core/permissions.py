"""Reusable permission classes and helpers for the Showdesk platform."""

from django.core.exceptions import ValidationError
from rest_framework.permissions import BasePermission


class IsPlatformAdmin(BasePermission):
    """Allow access only to platform administrators (superusers)."""

    def has_permission(self, request, view):
        return (
            request.user and request.user.is_authenticated and request.user.is_superuser
        )


def has_feature(feature: str) -> type[BasePermission]:
    """Build a DRF permission class that gates on a per-org feature flag.

    Usage:
        permission_classes = [IsAuthenticated, has_feature("sla_policies")]

    Resolves the active org via ``get_active_org`` so that platform
    admin impersonation (X-Showdesk-Org header) sees the impersonated
    org's flags, not the superuser's own. Returns 403 if the flag is
    not enabled for the org.
    """

    class _HasFeature(BasePermission):
        message = f"Your plan does not include the '{feature}' feature."

        def has_permission(self, request, view):
            org = get_active_org(request)
            return org is not None and org.has_feature(feature)

    _HasFeature.__name__ = f"HasFeature_{feature}"
    return _HasFeature


def _impersonated_org(request):
    """Return the organization a superuser's header names, None if it names none."""
    org_id = request.META.get("HTTP_X_SHOWDESK_ORG")
    if not org_id or not request.user.is_superuser:
        return None
    from apps.organizations.models import Organization

    try:
        return Organization.objects.get(id=org_id)
    except (Organization.DoesNotExist, ValueError, ValidationError):
        return None


def impersonates_no_organization(request) -> bool:
    """Tell whether a superuser's header names an organization that doesn't resolve."""
    return (
        request.user.is_superuser
        and bool(request.META.get("HTTP_X_SHOWDESK_ORG"))
        and _impersonated_org(request) is None
    )


def get_active_org(request):
    """Return the effective organization for the current request.

    For superusers with an impersonated org (via X-Showdesk-Org header),
    returns the impersonated org. Otherwise returns the user's own org,
    including when the header names an org that doesn't resolve: the frontend
    persists the org it sends, and a stale one mustn't lock its user out.

    Note: This resolves the header lazily at call time (in the ViewSet),
    because DRF JWT authentication runs after Django middleware.
    """
    return _impersonated_org(request) or request.user.organization
