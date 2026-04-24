"""Widget-related views that are authenticated by JWT (not X-Widget-Token).

Used by the Showdesk frontend itself to bootstrap the embedded widget
(dogfooding): authenticated Showdesk users can submit feedback to the
`showdesk-internal` organization via the same widget used by customers.
"""

import hashlib
import hmac

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.models import SHOWDESK_INTERNAL_ORG_SLUG, Organization


class InternalWidgetIdentityView(APIView):
    """Return the token + HMAC user hash to initialize the in-app widget."""

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ANN001, ANN201
        try:
            org = Organization.objects.get(
                slug=SHOWDESK_INTERNAL_ORG_SLUG,
                is_active=True,
            )
        except Organization.DoesNotExist:
            return Response(
                {"error": "Internal organization not provisioned."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        external_user_id = str(request.user.id)
        user_hash = hmac.new(
            org.widget_secret.encode(),
            external_user_id.encode(),
            hashlib.sha256,
        ).hexdigest()

        full_name = (
            f"{request.user.first_name} {request.user.last_name}".strip()
            or request.user.email
        )

        return Response(
            {
                "token": str(org.api_token),
                "user_hash": user_hash,
                "external_user_id": external_user_id,
                "user": {
                    "id": external_user_id,
                    "name": full_name,
                    "email": request.user.email,
                },
            }
        )
