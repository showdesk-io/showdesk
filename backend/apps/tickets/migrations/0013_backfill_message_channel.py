from django.db import migrations


def backfill_channel(apps, schema_editor) -> None:
    """Give existing messages the channel their sender type implies.

    Before the email channel, a user's message could only come from the widget:
    the column's default already says so.
    """
    TicketMessage = apps.get_model("tickets", "TicketMessage")
    for sender_type in ("agent", "system"):
        TicketMessage.objects.filter(sender_type=sender_type).update(
            channel=sender_type
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0012_email_channel_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_channel, migrations.RunPython.noop),
    ]
