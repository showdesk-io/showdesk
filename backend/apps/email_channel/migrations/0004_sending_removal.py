import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("email_channel", "0003_inbound_rejected_without_mailbox"),
        ("organizations", "0017_organizationdomain_sending"),
    ]

    operations = [
        migrations.CreateModel(
            name="SendingRemoval",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("domain", models.CharField(db_index=True, max_length=255)),
                ("ref", models.CharField(max_length=255, unique=True)),
                (
                    "provider",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "The provider that made the registration: only it "
                            "removes it. Blank if unknown (recorded while the "
                            'provider was "none").'
                        ),
                        max_length=32,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
    ]
