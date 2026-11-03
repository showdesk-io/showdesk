from django.db import migrations, models


def _normalized(value) -> str:
    """As ``apps.tickets.models.normalized_email``, frozen here."""
    return (value or "").strip().lower()


def record_proven_addresses(apps, schema_editor) -> None:
    """Keep a session's proof only where its contact holds the email it has.

    That's what made it a proof when it was written. Anywhere else nothing says which
    address it was about (an email change racing the proof could have left it on an
    unproven one), so it's dropped: the session proves its email again if it can.
    """
    WidgetSession = apps.get_model("tickets", "WidgetSession")
    proven = (
        WidgetSession.objects.filter(email_verified_at__isnull=False)
        .select_related("contact")
        .order_by("pk")
    )
    kept, dropped = [], []
    for session in proven.iterator(chunk_size=500):
        email = _normalized(session.email)
        contact = session.contact
        if email and contact is not None and _normalized(contact.email) == email:
            session.email_verified_for = email
            kept.append(session)
        else:
            session.email_verified_at = None
            session.email_proof_source = ""
            dropped.append(session)
    WidgetSession.objects.bulk_update(kept, ["email_verified_for"], batch_size=500)
    WidgetSession.objects.bulk_update(
        dropped, ["email_verified_at", "email_proof_source"], batch_size=500
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0016_widgetsession_email_proof_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="widgetsession",
            name="email_verified_for",
            field=models.EmailField(
                blank=True,
                default="",
                help_text="The lowercased address the proof is about. It only counts "
                "while it is the session's email and its contact's.",
                max_length=254,
            ),
        ),
        migrations.RunPython(record_proven_addresses, migrations.RunPython.noop),
    ]
