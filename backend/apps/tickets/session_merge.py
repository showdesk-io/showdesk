"""Merge the widget sessions sharing an external user, before they can't anymore.

``widget_conversation`` looks tickets up by session while ``widget_history`` lists
them by external user, so a user with two sessions sees conversations they can't
open. Plain function called from a migration, so it takes the app registry.
"""

from django.db.models import Count


def merge_duplicate_sessions(apps, schema_editor) -> None:
    """Keep each user's oldest session, moving the others' tickets and messages.

    The kept session takes what it lacks from the most recent others, an email
    with its proof. It's idempotent: there's nothing to do on a second run.
    """
    WidgetSession = apps.get_model("tickets", "WidgetSession")
    Ticket = apps.get_model("tickets", "Ticket")
    TicketMessage = apps.get_model("tickets", "TicketMessage")

    groups = (
        WidgetSession.objects.exclude(external_user_id="")
        .order_by()
        .values("organization_id", "external_user_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    for group in groups:
        kept, *others = WidgetSession.objects.filter(
            organization_id=group["organization_id"],
            external_user_id=group["external_user_id"],
        ).order_by("created_at", "id")
        for other in reversed(others):
            kept.name = kept.name or other.name
            if not kept.email and other.email:
                kept.email = other.email
                kept.email_verified_at = other.email_verified_at
            kept.contact_id = kept.contact_id or other.contact_id
        other_ids = [other.pk for other in others]
        Ticket.objects.filter(widget_session_id__in=other_ids).update(
            widget_session_id=kept.pk
        )
        TicketMessage.objects.filter(widget_session_id__in=other_ids).update(
            widget_session_id=kept.pk
        )
        WidgetSession.objects.filter(pk__in=other_ids).delete()
        WidgetSession.objects.filter(pk=kept.pk).update(
            name=kept.name,
            email=kept.email,
            email_verified_at=kept.email_verified_at,
            contact_id=kept.contact_id,
        )
