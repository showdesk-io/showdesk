"""Reusable permission classes and helpers for the Showdesk platform."""

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

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
        return user.is_authenticated and (user.is_agent or user.is_superuser)


def is_org_admin(user) -> bool:
    """Return whether ``user`` administers their active organization.

    ``get_active_org`` ties a non-superuser to their own organization, so the
    role is enough. Superusers administer whichever one they impersonate.
    """
    return user.is_authenticated and (user.role == "admin" or user.is_superuser)


class IsOrgAdmin(BasePermission):
    """Allow organization admins and superusers."""

    message = "Only admins can do this."

    def has_permission(self, request, view):
        return is_org_admin(request.user)


class IsOrgAdminOrReadOnly(BasePermission):
    """Let staff read, and admins write.

    Checked before validation, so that an agent's answer doesn't depend on the body
    sent, and doesn't tell what the validation would have refused.
    """

    message = "Only admins can do this."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return IsOrgStaff().has_permission(request, view)
        return is_org_admin(request.user)


def require_org_admin(user) -> None:
    """Refuse the request unless ``user`` is an admin, for checks inside an action."""
    if not is_org_admin(user):
        raise PermissionDenied(IsOrgAdmin.message)


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
    except LOOKUP_ERRORS:
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
    # Anonymous users reach this through AllowAny routes on scoped viewsets.
    return _impersonated_org(request) or getattr(request.user, "organization", None)


class HasStrictActiveOrg(BasePermission):
    """Need an active organization, without ``get_active_org``'s fallback.

    A superuser without one has to impersonate one first. An impersonation that
    doesn't resolve is refused with a 400 rather than falling back on the
    superuser's own organization: for routes showing personal data, that would
    answer or write for an organization other than the one asked for.
    """

    def has_permission(self, request, view):
        if impersonates_no_organization(request):
            raise ValidationError({"detail": "Unknown organization."})
        return get_active_org(request) is not None


def require_active_org(request):
    """Return the active organization, or refuse the request with a 400."""
    org = get_active_org(request)
    if org is None:
        raise ValidationError({"error": "No active organization."})
    return org
