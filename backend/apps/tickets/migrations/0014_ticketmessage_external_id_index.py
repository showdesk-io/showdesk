from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # Built without locking the table against writes.
    atomic = False

    dependencies = [
        ("tickets", "0013_backfill_message_channel"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticketmessage",
            index=models.Index(
                condition=models.Q(("external_id", ""), _negated=True),
                fields=["external_id"],
                name="ticketmessage_external_id",
            ),
        ),
    ]
