"""Videos admin configuration."""

from django.contrib import admin

from .models import VideoRecording


@admin.register(VideoRecording)
class VideoRecordingAdmin(admin.ModelAdmin):
    """Admin for video recordings."""

    list_display = [
        "ticket",
        "status",
        "recording_type",
        "duration_seconds",
        "has_audio",
        "has_camera",
        "expires_at",
        "created_at",
    ]
    list_filter = ["status", "recording_type", "has_audio", "has_camera"]
    search_fields = ["ticket__reference"]
    readonly_fields = [
        "id",
        "processing_started_at",
        "processing_completed_at",
        "created_at",
        "updated_at",
    ]
