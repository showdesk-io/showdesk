"""Add widget_secret field to Organization for HMAC identity verification."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_user_is_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="widget_secret",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Secret key for HMAC identity verification. Never expose client-side.",
                max_length=64,
            ),
        ),
    ]
