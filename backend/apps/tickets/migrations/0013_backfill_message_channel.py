from django.db import migrations

BATCH_SIZE = 5000


def backfill_channel(apps, schema_editor, batch_size: int = BATCH_SIZE) -> None:
    """Give existing messages the channel their sender type implies.

    Before the email channel, a user's message could only come from the widget:
    the column's default already says so. Run outside a transaction, by ranges of
    primary keys, so that each batch commits and holds its row locks briefly.
    """
    TicketMessage = apps.get_model("tickets", "TicketMessage")
    to_fill = TicketMessage.objects.filter(sender_type__in=("agent", "system"))
    last = None
    while True:
        batch = to_fill.order_by("pk")
        if last is not None:
            batch = batch.filter(pk__gt=last)
        pks = list(batch.values_list("pk", flat=True)[:batch_size])
        if not pks:
            return
        in_range = TicketMessage.objects.filter(pk__gte=pks[0], pk__lte=pks[-1])
        for sender_type in ("agent", "system"):
            in_range.filter(sender_type=sender_type).update(channel=sender_type)
        last = pks[-1]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tickets", "0012_email_channel_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_channel, migrations.RunPython.noop),
    ]
