"""Celery tasks of the email channel."""

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

# Pending for longer than this, a mail's queuing is taken as lost.
STALE_PENDING_AFTER = timedelta(minutes=10)


@shared_task
def process_inbound_email(inbound_id: str) -> None:
    """Run one stored mail through the pipeline. Safe to run again."""


@shared_task
def requeue_stale_inbound() -> int:
    """Queue again the mails still pending long after they arrived.

    Their queuing failed after they were stored (e.g. the broker was down), and
    the provider may never send them again. Returns how many were queued.
    """
    from apps.email_channel.models import InboundEmail

    stale = InboundEmail.objects.filter(
        status=InboundEmail.Status.PENDING,
        received_at__lt=timezone.now() - STALE_PENDING_AFTER,
    ).values_list("id", flat=True)
    count = 0
    for inbound_id in stale.iterator():
        process_inbound_email.delay(str(inbound_id))
        count += 1
    return count
