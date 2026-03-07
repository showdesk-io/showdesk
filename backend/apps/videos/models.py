"""Video recording model and related functionality.

Video is the core differentiator of Showdesk. This model tracks
the full lifecycle of a video recording: upload, processing,
transcription, and eventual expiration.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class VideoRecording(TimestampedModel):
    """A screen recording submitted with a ticket.

    Videos are first-class citizens in Showdesk. They go through a
    processing pipeline: upload -> processing (FFmpeg) -> ready.
    Transcription is optional and gated behind the AI_ENABLED flag.

    Privacy: videos have an explicit expiration date, after which they
    are automatically deleted. This is a feature, not a constraint.
    """

    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    class RecordingType(models.TextChoices):
        SCREEN = "screen", "Screen Only"
        SCREEN_CAMERA = "screen_camera", "Screen + Camera"
        CAMERA = "camera", "Camera Only"

    # Relationships
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.CASCADE,
        related_name="videos",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recordings",
    )

    # Video files
    original_file = models.FileField(
        upload_to="videos/originals/%Y/%m/%d/",
        help_text="Original uploaded video file.",
    )
    processed_file = models.FileField(
        upload_to="videos/processed/%Y/%m/%d/",
        blank=True,
        help_text="Processed/compressed video file.",
    )
    thumbnail = models.ImageField(
        upload_to="videos/thumbnails/%Y/%m/%d/",
        blank=True,
        help_text="Auto-generated video thumbnail.",
    )

    # Metadata
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADING,
        db_index=True,
    )
    recording_type = models.CharField(
        max_length=20,
        choices=RecordingType.choices,
        default=RecordingType.SCREEN,
    )
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Duration of the video in seconds.",
    )
    file_size = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes.",
    )
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=50, default="video/webm")

    # Audio
    has_audio = models.BooleanField(default=False)
    has_camera = models.BooleanField(default=False)

    # Transcription (AI feature, gated)
    transcription = models.TextField(
        blank=True,
        help_text="Auto-generated transcription of the audio track.",
    )
    transcription_status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("disabled", "Disabled"),
        ],
        default="disabled",
    )
    transcription_language = models.CharField(max_length=10, blank=True)

    # Privacy & expiration
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When this video will be automatically deleted.",
    )
    is_redacted = models.BooleanField(
        default=False,
        help_text="Whether sensitive content has been redacted.",
    )

    # Processing metadata
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_completed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ticket", "status"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Video for {self.ticket.reference} ({self.status})"

    @property
    def is_playable(self) -> bool:
        """Check if the video is ready for playback."""
        return self.status == self.Status.READY
