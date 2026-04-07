"""Add is_verified field to User model."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_otpcode"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_verified",
            field=models.BooleanField(
                default=False,
                help_text="Whether this user has verified their email via OTP at least once.",
            ),
        ),
    ]
