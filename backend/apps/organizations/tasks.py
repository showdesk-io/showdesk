"""Celery tasks for the organizations app.

There is no periodic re-check of `verified` rows on purpose: per design,
verified-once = verified-forever, with ownership transfers triggered
explicitly by a competing org's DNS challenge. The pending poller below
is the only background DNS work.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import OrganizationDomain
from .services import perform_dns_check

logger = logging.getLogger(__name__)

# How far back to keep polling a pending DNS challenge. After this window
# we stop hammering the resolver — the admin can refresh the token from
# the settings UI to start a new poll cycle.
PENDING_POLL_WINDOW = timedelta(days=7)


@shared_task(name="apps.organizations.tasks.recheck_dns_pending_domains")
def recheck_dns_pending_domains() -> int:
    """Re-poll pending DNS rows so admins don't have to click Verify themselves.

    Runs every 15 minutes (see CELERY_BEAT_SCHEDULE). Skips rows older
    than PENDING_POLL_WINDOW; those need a regenerate-token to resume.
    Returns the number of rows that just transitioned to verified.
    """
    cutoff = timezone.now() - PENDING_POLL_WINDOW
    rows = OrganizationDomain.objects.filter(
        status=OrganizationDomain.Status.PENDING,
        verification_method=OrganizationDomain.VerificationMethod.DNS_TXT,
        created_at__gte=cutoff,
    )

    promoted = 0
    for row in rows:
        try:
            if perform_dns_check(row):
                promoted += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "recheck_dns_pending_domains: failed for %s/%s",
                row.organization_id,
                row.domain,
            )
    return promoted
