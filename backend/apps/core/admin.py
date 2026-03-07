"""Core admin configuration."""

from django.contrib import admin

from .models import UsageRecord


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    """Admin for usage records."""

    list_display = ["organization", "usage_type", "quantity", "recorded_at"]
    list_filter = ["usage_type", "recorded_at"]
    readonly_fields = ["id", "created_at", "updated_at"]
