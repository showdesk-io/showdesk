"""Core views."""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Health check endpoint for load balancers and monitoring."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request) -> Response:  # noqa: ANN001
        """Return health status."""
        return Response({"status": "healthy"}, status=status.HTTP_200_OK)
