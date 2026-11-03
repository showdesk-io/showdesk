from django.db import migrations

BATCH_SIZE = 5000


def backfill_delivery(apps, schema_editor, batch_size: int = BATCH_SIZE) -> None:
    """Count the agents' replies written before the email channel as emailed.

    A reply mail carries the replies not emailed yet: without this, the first one
    after the upgrade would send a ticket's whole history again. Run outside a
    transaction, by ranges of primary keys, so that each batch commits and holds
    its row locks briefly.
    """
    TicketMessage = apps.get_model("tickets", "TicketMessage")
    to_fill = TicketMessage.objects.filter(
        sender_type="agent", message_type="reply", email_delivery_status=""
    )
    last = None
    while True:
        batch = to_fill.order_by("pk")
        if last is not None:
            batch = batch.filter(pk__gt=last)
        pks = list(batch.values_list("pk", flat=True)[:batch_size])
        if not pks:
            return
        to_fill.filter(pk__gte=pks[0], pk__lte=pks[-1]).update(
            email_delivery_status="sent"
        )
        last = pks[-1]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tickets", "0014_ticketmessage_external_id_index"),
    ]

    operations = [
        migrations.RunPython(backfill_delivery, migrations.RunPython.noop),
    ]
