"""Custom middleware for the Showdesk platform."""

import logging

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class OrgImpersonationMiddleware(MiddlewareMixin):
    """Allow superusers to impersonate an organization.

    When a superuser sends the X-Showdesk-Org header with an org ID,
    this middleware attaches the corresponding Organization instance
    to request.impersonated_org. Tenant-scoped views use get_active_org()
    to pick up this override.
    """

    def process_request(self, request):  # noqa: ANN001, ANN201
        request.impersonated_org = None

        org_id = request.META.get("HTTP_X_SHOWDESK_ORG")
        if not org_id:
            return

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_superuser:
            return

        from apps.organizations.models import Organization

        try:
            request.impersonated_org = Organization.objects.get(id=org_id)
        except (Organization.DoesNotExist, ValueError):
            logger.warning("Invalid impersonation org ID: %s", org_id)
