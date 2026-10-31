"""Merge the widget sessions sharing an external user, before they can't anymore.

``widget_conversation`` looks tickets up by session while ``widget_history`` lists
them by external user, so a user with two sessions sees conversations they can't
open. Plain function called from a migration, so it takes the app registry.
"""

from django.db.models import Count


def merge_duplicate_sessions(apps, schema_editor) -> None:
    """Keep each user's oldest session, moving the others' tickets and messages.

    The kept session's id stays valid, but it takes the name, the email with its proof,
    the contact and the date of the most recently seen session having them: an older
    value is the one the user has since replaced. It's idempotent: there's nothing to
    do on a second run.
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
        sessions = list(
            WidgetSession.objects.filter(
                organization_id=group["organization_id"],
                external_user_id=group["external_user_id"],
            ).order_by("created_at", "id")
        )
        kept, *others = sessions
        latest_first = sorted(
            sessions, key=lambda s: (s.last_seen_at, s.created_at), reverse=True
        )
        kept.name = next((s.name for s in latest_first if s.name.strip()), "")
        with_email = next((s for s in latest_first if s.email.strip()), kept)
        kept.email = with_email.email
        kept.email_verified_at = with_email.email_verified_at
        kept.contact_id = next(
            (s.contact_id for s in latest_first if s.contact_id), None
        )
        kept.last_seen_at = latest_first[0].last_seen_at
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
            last_seen_at=kept.last_seen_at,
        )
