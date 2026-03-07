"""Tickets admin configuration."""

from django.contrib import admin

from .models import SLAPolicy, Tag, Ticket, TicketAttachment, TicketMessage


class TicketMessageInline(admin.TabularInline):
    """Inline for ticket messages."""

    model = TicketMessage
    extra = 0
    readonly_fields = ["id", "created_at"]


class TicketAttachmentInline(admin.TabularInline):
    """Inline for ticket attachments."""

    model = TicketAttachment
    extra = 0
    readonly_fields = ["id", "created_at"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    """Admin for tickets."""

    list_display = [
        "reference",
        "title",
        "status",
        "priority",
        "assigned_agent",
        "organization",
        "created_at",
    ]
    list_filter = ["status", "priority", "organization", "source"]
    search_fields = ["reference", "title", "description", "requester_email"]
    readonly_fields = ["id", "reference", "created_at", "updated_at"]
    inlines = [TicketMessageInline, TicketAttachmentInline]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Admin for tags."""

    list_display = ["name", "organization", "color"]
    list_filter = ["organization"]


@admin.register(SLAPolicy)
class SLAPolicyAdmin(admin.ModelAdmin):
    """Admin for SLA policies."""

    list_display = ["name", "priority", "first_response_minutes", "resolution_minutes", "is_active"]
    list_filter = ["priority", "is_active"]
