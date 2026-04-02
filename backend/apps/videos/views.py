"""Views for video-related models."""

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from apps.core.throttling import WidgetUploadThrottle
from apps.organizations.models import Organization

from .models import VideoRecording
from .serializers import VideoRecordingSerializer, VideoUploadSerializer
from .tasks import process_video


class VideoRecordingViewSet(viewsets.ModelViewSet):
    """ViewSet for managing video recordings.

    Videos are the heart of Showdesk. This viewset handles both
    authenticated agent access and unauthenticated widget uploads.
    """

    serializer_class = VideoRecordingSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):  # noqa: ANN201
        """Filter videos by user's organization tickets."""
        user = self.request.user
        if user.is_superuser:
            return VideoRecording.objects.all()
        if user.organization:
            return VideoRecording.objects.filter(ticket__organization=user.organization)
        return VideoRecording.objects.none()

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        serializer_class=VideoUploadSerializer,
        throttle_classes=[WidgetUploadThrottle],
    )
    def widget_upload(self, request):  # noqa: ANN001, ANN201
        """Upload a video recording from the widget.

        Authenticates via X-Widget-Token header. Triggers async
        video processing via Celery.
        """
        token = request.headers.get("X-Widget-Token")
        if not token:
            return Response(
                {"error": "Missing X-Widget-Token header."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            organization = Organization.objects.get(api_token=token, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive organization token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = VideoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Compute expiration based on organization settings
        expiration_days = organization.video_expiration_days
        expires_at = timezone.now() + timezone.timedelta(days=expiration_days)

        video = serializer.save(
            status=VideoRecording.Status.UPLOADING,
            expires_at=expires_at,
        )

        # Trigger async processing
        process_video.delay(str(video.id))

        return Response(
            VideoRecordingSerializer(video).data,
            status=status.HTTP_201_CREATED,
        )
