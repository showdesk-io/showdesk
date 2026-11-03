"""Celery tasks of the email channel."""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Pending for longer than this, a mail's queuing is taken as lost.
STALE_PENDING_AFTER = timedelta(minutes=10)


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    # Under a row lock: a mail that takes longer is a mail to look at by hand.
    soft_time_limit=120,
    time_limit=150,
)
def process_inbound_email(self, inbound_id: str) -> None:
    """Run one stored mail through the pipeline. Safe to run again.

    A failure marks the mail failed, in its own transaction, then retries with a
    growing delay. An admin can replay it past the last retry.
    """
    from apps.email_channel.pipeline import process

    try:
        process(inbound_id)
    except Exception as exc:
        logger.exception("Inbound mail %s failed", inbound_id)
        _mark_failed(inbound_id)
        raise self.retry(exc=exc, countdown=60 * 2**self.request.retries)


def _mark_failed(inbound_id: str) -> None:
    from apps.email_channel.models import InboundEmail
    from apps.email_channel.pipeline import PROCESSABLE

    with transaction.atomic():
        InboundEmail.objects.filter(pk=inbound_id, status__in=PROCESSABLE).update(
            status=InboundEmail.Status.FAILED,
            reason="exception",
            updated_at=timezone.now(),
        )


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


@shared_task
def purge_inbound_raw() -> int:
    """Delete the raw mails older than ``INBOUND_EMAIL_RAW_RETENTION_DAYS``.

    The rows stay, as a log, until ``INBOUND_EMAIL_LOG_RETENTION_DAYS``. Pending
    and failed mails keep both: it's all a replay has. Returns how many raw mails
    were emptied.
    """
    from django.conf import settings

    from apps.email_channel.models import InboundEmail
    from apps.email_channel.pipeline import PROCESSABLE

    cutoff = timezone.now() - timedelta(days=settings.INBOUND_EMAIL_RAW_RETENTION_DAYS)
    expired = (
        InboundEmail.objects.filter(received_at__lt=cutoff)
        .exclude(raw="")
        .exclude(status__in=PROCESSABLE)
    )
    count = 0
    for inbound in expired.only("id", "raw").iterator():
        storage, name = inbound.raw.storage, inbound.raw.name
        with transaction.atomic():
            # Unless it was replayed in the meantime.
            emptied = (
                InboundEmail.objects.filter(pk=inbound.pk, raw=name)
                .exclude(status__in=PROCESSABLE)
                .update(raw="", updated_at=timezone.now())
            )
            if emptied:
                transaction.on_commit(lambda s=storage, n=name: _delete_file(s, n))
        count += emptied
    # The log itself, past its own retention. Their files go with the rows, once
    # committed, by the post_delete receiver.
    InboundEmail.objects.filter(
        received_at__lt=timezone.now()
        - timedelta(days=settings.INBOUND_EMAIL_LOG_RETENTION_DAYS)
    ).exclude(status__in=PROCESSABLE).delete()
    return count


def _delete_file(storage, name: str) -> None:
    try:
        storage.delete(name)
    except Exception:
        logger.exception("Couldn't delete the raw mail %s", name)
