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
