import django.utils.timezone
from django.db import migrations, models


def record_dangling_refs(apps, schema_editor):
    """Rows not set up for sending but still holding a ref: record its removal.

    The hourly sweep queues them.
    """
    OrganizationDomain = apps.get_model("organizations", "OrganizationDomain")
    SendingRemoval = apps.get_model("email_channel", "SendingRemoval")
    dangling = OrganizationDomain.objects.filter(sending_status="").exclude(
        sending_provider_ref=""
    )
    for row in dangling:
        SendingRemoval.objects.get_or_create(
            ref=row.sending_provider_ref, defaults={"domain": row.domain}
        )
    dangling.update(sending_provider_ref="")


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
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_error", models.CharField(blank=True, max_length=500)),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.RunPython(record_dangling_refs, migrations.RunPython.noop),
    ]
