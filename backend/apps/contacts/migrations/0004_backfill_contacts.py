from django.db import migrations

from apps.contacts.backfill import backfill


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0003_contact_declared_email"),
        ("tickets", "0011_one_widget_session_per_external_user"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
