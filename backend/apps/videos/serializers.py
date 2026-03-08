"""Serializers for video-related models."""

from rest_framework import serializers

from .models import VideoRecording


class VideoRecordingSerializer(serializers.ModelSerializer):
    """Serializer for the VideoRecording model."""

    is_playable = serializers.BooleanField(read_only=True)

    class Meta:
        model = VideoRecording
        fields = [
            "id",
            "ticket",
            "recorded_by",
            "original_file",
            "processed_file",
            "thumbnail",
            "status",
            "recording_type",
            "duration_seconds",
            "file_size",
            "width",
            "height",
            "mime_type",
            "has_audio",
            "has_camera",
            "transcription",
            "transcription_status",
            "transcription_language",
            "expires_at",
            "is_redacted",
            "is_playable",
            "processing_started_at",
            "processing_completed_at",
            "processing_error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "duration_seconds",
            "file_size",
            "width",
            "height",
            "processed_file",
            "thumbnail",
            "transcription",
            "transcription_status",
            "processing_started_at",
            "processing_completed_at",
            "processing_error",
            "created_at",
            "updated_at",
        ]


class VideoUploadSerializer(serializers.ModelSerializer):
    """Serializer for uploading a video from the widget."""

    # Max 500 MB per video (configurable via settings)
    MAX_FILE_SIZE = 500 * 1024 * 1024

    ALLOWED_MIME_TYPES = {
        "video/webm",
        "video/mp4",
        "video/ogg",
        "video/quicktime",
    }

    class Meta:
        model = VideoRecording
        fields = [
            "ticket",
            "original_file",
            "recording_type",
            "has_audio",
            "has_camera",
            "mime_type",
        ]

    def validate_original_file(self, value):  # noqa: ANN001, ANN201
        """Validate video file size and type."""
        from django.conf import settings as django_settings

        max_size = getattr(django_settings, "VIDEO_MAX_FILE_SIZE_MB", 500) * 1024 * 1024
        if value.size > max_size:
            max_mb = max_size // (1024 * 1024)
            raise serializers.ValidationError(
                f"Video file exceeds the {max_mb} MB limit."
            )

        # Check content type from the request
        content_type = getattr(value, "content_type", "")
        if content_type and content_type not in self.ALLOWED_MIME_TYPES:
            raise serializers.ValidationError(
                f"Video type '{content_type}' is not supported. "
                f"Allowed: {', '.join(sorted(self.ALLOWED_MIME_TYPES))}"
            )

        return value
