"""Reusable permission classes and helpers for the Showdesk platform."""

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission

# What ``Model.objects.get(id=<client value>)`` raises when no row matches: a
# malformed UUID doesn't raise DoesNotExist but Django's ValidationError.
LOOKUP_ERRORS = (ObjectDoesNotExist, DjangoValidationError, ValueError, TypeError)


class IsPlatformAdmin(BasePermission):
    """Allow access only to platform administrators (superusers)."""

    def has_permission(self, request, view):
        return (
            request.user and request.user.is_authenticated and request.user.is_superuser
        )


class IsOrgStaff(BasePermission):
    """Refuse end users: they only talk to the widget routes, which set their own."""

    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and (
            user.is_agent or user.is_staff or user.is_superuser
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


def get_active_org(request):
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
            except LOOKUP_ERRORS:
                pass
    # Anonymous users reach this through AllowAny routes on scoped viewsets.
    return getattr(request.user, "organization", None)


def require_active_org(request):
    """Return the active organization, or refuse the request with a 400."""
    org = get_active_org(request)
    if org is None:
        raise ValidationError({"error": "No active organization."})
    return org
