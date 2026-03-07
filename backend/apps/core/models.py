"""Base models and mixins used across all Showdesk apps."""

import uuid

from django.db import models


class TimestampedModel(models.Model):
    """Abstract base model with created/updated timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class UsageRecord(TimestampedModel):
    """Tracks resource usage for billing purposes.

    This model is isolated from the core functionality and only serves
    usage tracking for the cloud offering. It has no impact on core
    features when absent or disabled.
    """

    class UsageType(models.TextChoices):
        ACTIVE_AGENTS = "active_agents", "Active Agents"
        VIDEO_STORAGE_MB = "video_storage_mb", "Video Storage (MB)"
        RECORDING_MINUTES = "recording_minutes", "Recording Minutes"
        TRANSCRIPTION_MINUTES = "transcription_minutes", "Transcription Minutes"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="usage_records",
    )
    usage_type = models.CharField(max_length=30, choices=UsageType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    recorded_at = models.DateTimeField(auto_now_add=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(fields=["organization", "usage_type", "recorded_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.organization} - {self.usage_type}: {self.quantity}"
