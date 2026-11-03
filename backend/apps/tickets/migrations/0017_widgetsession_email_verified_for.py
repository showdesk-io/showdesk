from django.db import migrations, models
from django.db.models.functions import Lower, Trim


def record_proven_addresses(apps, schema_editor) -> None:
    """A session proven so far was proven for the email it has: no write changed one
    without clearing its proof."""
    WidgetSession = apps.get_model("tickets", "WidgetSession")
    WidgetSession.objects.filter(email_verified_at__isnull=False).update(
        email_verified_for=Lower(Trim("email"))
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
