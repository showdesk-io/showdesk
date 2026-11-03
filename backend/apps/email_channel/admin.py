"""Email channel admin configuration."""

from django.contrib import admin

from .models import InboundEmail, Mailbox


@admin.register(Mailbox)
class MailboxAdmin(admin.ModelAdmin):
    """Admin for mailboxes."""

    list_display = ["name", "local_part", "public_address", "organization", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "local_part", "public_address"]
    readonly_fields = ["id", "local_part", "created_at", "updated_at"]


@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    """Admin for received emails.

    The raw mail is left out: its file widget would link to it, and a mail holds
    personal data.
    """

    list_display = ["received_at", "sender", "subject", "mailbox", "status", "reason"]
    list_filter = ["status", "reason"]
    search_fields = ["message_id", "sender", "subject"]
    exclude = ["raw"]
    readonly_fields = [
        "id",
        "mailbox",
        "ticket",
        "ticket_message",
        "message_id",
        "sender",
        "recipients",
        "subject",
        "status",
        "reason",
        "received_at",
        "processed_at",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request) -> bool:
        return False
