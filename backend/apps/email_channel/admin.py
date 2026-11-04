"""Email channel admin configuration."""

from django.contrib import admin, messages

from .models import InboundEmail, Mailbox, SendingRemoval
from .tasks import replay


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
    personal data. Agents download it from its message, in the app.
    """

    list_display = ["received_at", "sender", "subject", "mailbox", "status", "reason"]
    list_filter = ["status", "reason"]
    search_fields = ["message_id", "sender", "subject"]
    exclude = ["raw"]
    actions = ["replay_failed"]
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

    @admin.action(description="Replay the selected failed mails")
    def replay_failed(self, request, queryset) -> None:
        """Queue the failed ones again, each once however often asked. Others stay."""
        failed = queryset.filter(status=InboundEmail.Status.FAILED)
        count = sum(replay(pk) for pk in failed.values_list("pk", flat=True))
        skipped = queryset.count() - count
        mails = "mail" if count == 1 else "mails"
        self.message_user(
            request, f"{count} failed {mails} queued again.", messages.SUCCESS
        )
        if skipped:
            self.message_user(
                request,
                f"{skipped} left as they were: only failed mails are replayed.",
                messages.WARNING,
            )


@admin.register(SendingRemoval)
class SendingRemovalAdmin(admin.ModelAdmin):
    """Sending registrations still to remove at the provider: to watch, not edit.

    Removed by their task and the sweep. A record may be deleted by
    hand once the registration was removed at the provider some other way.
    """

    list_display = [
        "domain",
        "ref",
        "provider",
        "attempts",
        "last_attempt_at",
        "last_error",
        "created_at",
    ]
    search_fields = ["domain", "ref"]
    readonly_fields = [
        "domain",
        "ref",
        "provider",
        "attempts",
        "last_attempt_at",
        "last_error",
        "created_at",
    ]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
