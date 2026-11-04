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


def replay(inbound_id) -> bool:
    """Queue a failed mail again. Returns whether it was.

    It goes back to pending first, so that asking twice queues it once: the second
    finds nothing failed to replay.
    """
    from apps.email_channel.models import InboundEmail

    with transaction.atomic():
        replayed = InboundEmail.objects.filter(
            pk=inbound_id, status=InboundEmail.Status.FAILED
        ).update(
            status=InboundEmail.Status.PENDING,
            reason="",
            updated_at=timezone.now(),
        )
        if replayed:
            transaction.on_commit(lambda: process_inbound_email.delay(str(inbound_id)))
    return bool(replayed)


@shared_task
def requeue_stale_inbound() -> int:
    """Queue again the mails still pending long after they arrived.

    Their queuing failed after they were stored (e.g. the broker was down), and
    the provider may never send them again. Each is queued at most once per
    ``STALE_PENDING_AFTER``: queuing it marks it as just updated. Returns how many
    were queued.
    """
    from apps.email_channel.models import InboundEmail

    # Pending since: a replay puts an old mail back to pending, and queues it.
    stale = InboundEmail.objects.filter(
        status=InboundEmail.Status.PENDING,
        updated_at__lt=timezone.now() - STALE_PENDING_AFTER,
    )
    count = 0
    for inbound_id in stale.values_list("id", flat=True).iterator():
        # Unless processed or queued again meanwhile.
        if stale.filter(pk=inbound_id).update(updated_at=timezone.now()):
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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_conversation_link(self, ticket_id: str) -> None:
    """Mail the ticket's contact a fresh link to its conversation, as asked for.

    Only to the address the contact holds, whoever asked, and only where a reply
    mail would carry a link and would go at all.
    """
    from apps.core.email import send_branded_email
    from apps.email_channel import outbound
    from apps.tickets.models import Ticket

    ticket = (
        Ticket.objects.select_related("organization", "contact")
        .filter(pk=ticket_id)
        .first()
    )
    if ticket is None or ticket.contact is None:
        return
    address = ticket.contact.email
    url = outbound.conversation_url(ticket, address) if address else ""
    if not url or outbound.suppressed_by_unsubscribe(ticket):
        return
    try:
        send_branded_email(
            template="conversation_link",
            subject=f"[{ticket.reference}] Your link to the conversation",
            to=[address],
            organization=ticket.organization,
            from_email=outbound.from_address(ticket),
            reply_to=outbound.reply_to(ticket),
            context={"ticket": ticket, "conversation_url": url},
        )
    except Exception as exc:
        logger.exception("Failed to send a conversation link for %s", ticket.reference)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=None)
def remove_sending_registration(self, removal_id: int) -> None:
    """Remove a recorded sending registration at the provider.

    Retried with a growing delay while the provider fails, up to
    MAX_REMOVAL_ATTEMPTS tries of the record; then left to the hourly sweep.
    Without a provider the record waits as it is.
    """
    from apps.email_channel.models import SendingRemoval
    from apps.email_channel.sending.providers import (
        ProviderUnavailableError,
        SendingProviderError,
    )
    from apps.email_channel.sending.services import MAX_REMOVAL_ATTEMPTS, run_removal

    try:
        run_removal(removal_id)
    except ProviderUnavailableError:
        logger.warning(
            "Sending registration removal %s waits: no provider is configured.",
            removal_id,
        )
    except SendingProviderError as exc:
        removal = SendingRemoval.objects.filter(pk=removal_id).first()
        if removal is None:
            return
        if removal.attempts >= MAX_REMOVAL_ATTEMPTS:
            logger.error(
                "Gave up removing sending registration %s of %s after %d tries: %s",
                removal.ref,
                removal.domain,
                removal.attempts,
                exc,
            )
            return
        logger.warning("Removing sending registration %s failed: %s", removal.ref, exc)
        raise self.retry(exc=exc, countdown=60 * 2**self.request.retries) from exc


# A recorded removal older than this whose task isn't retrying anymore (lost
# before it ran, or gave up) is queued again by the hourly sweep.
REMOVAL_SWEEP_AFTER = timedelta(hours=1)


@shared_task
def requeue_sending_removals() -> int:
    """Queue again, once each, the removals no task is working on anymore."""
    from django.db.models import Q

    from apps.email_channel.models import SendingRemoval
    from apps.email_channel.sending.services import MAX_REMOVAL_ATTEMPTS

    stale = SendingRemoval.objects.filter(
        Q(attempts=0) | Q(attempts__gte=MAX_REMOVAL_ATTEMPTS),
        created_at__lt=timezone.now() - REMOVAL_SWEEP_AFTER,
    ).values_list("pk", flat=True)
    count = 0
    for removal_id in stale:
        remove_sending_registration.delay(removal_id)
        count += 1
    return count


@shared_task
def check_sending_domains() -> int:
    """Check the sending domains due for it, each on its own (§7.3).

    Pending ones every run; verified ones once a day, to notice a regression;
    failed ones only when an admin asks. Nothing without a provider. Returns
    how many were checked.
    """
    from django.db.models import Q

    from apps.email_channel.sending.providers import (
        SendingProviderError,
        sending_enabled,
    )
    from apps.email_channel.sending.services import (
        SENDING_RECHECK_HOURS,
        check_sending,
        provider,
    )
    from apps.organizations.models import OrganizationDomain

    if not sending_enabled():
        return 0
    try:
        sender = provider()
    except SendingProviderError:
        return 0  # Logged by `provider()`.
    Sending = OrganizationDomain.SendingStatus
    recheck_before = timezone.now() - timedelta(hours=SENDING_RECHECK_HOURS)
    due = (
        OrganizationDomain.objects.filter(status=OrganizationDomain.Status.VERIFIED)
        .exclude(sending_provider_ref="")
        .filter(
            Q(sending_status=Sending.PENDING)
            | Q(sending_status=Sending.VERIFIED)
            & (
                Q(sending_last_checked_at__isnull=True)
                | Q(sending_last_checked_at__lt=recheck_before)
            )
        )
    )
    count = 0
    for row in list(due):
        try:
            check_sending(row, sender=sender)
        except Exception:
            logger.exception("Sending check of %s failed", row.domain)
            continue
        count += 1
    return count
