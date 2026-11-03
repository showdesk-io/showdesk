from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # Built without locking the table against writes.
    atomic = False

    dependencies = [
        ("tickets", "0017_widgetsession_email_verified_for"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(fields=["mailbox"], name="ticket_mailbox"),
        ),
    ]
