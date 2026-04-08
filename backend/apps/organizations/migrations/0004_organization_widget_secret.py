"""Add widget_secret field to Organization for HMAC identity verification."""

import secrets

from django.db import migrations, models


def backfill_widget_secrets(apps, schema_editor):
    """Generate a widget_secret for all existing organizations."""
    Organization = apps.get_model("organizations", "Organization")
    for org in Organization.objects.filter(widget_secret=""):
        org.widget_secret = secrets.token_hex(32)
        org.save(update_fields=["widget_secret"])


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_user_is_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="widget_secret",
            field=models.CharField(
                default=secrets.token_hex,
                help_text="Secret key for HMAC identity verification. Never expose client-side.",
                max_length=64,
            ),
        ),
        migrations.RunPython(backfill_widget_secrets, migrations.RunPython.noop),
    ]
