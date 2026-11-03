"""Raw mails are kept for a while, then only their row stays."""

from datetime import timedelta

import pytest
from django.conf import settings as django_settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.email_channel.models import InboundEmail
from apps.email_channel.tasks import purge_inbound_raw
from tests.factories import InboundEmailFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_media")]


def _received(days_ago: int, status=InboundEmail.Status.PROCESSED) -> InboundEmail:
    inbound = InboundEmailFactory(
        status=status, received_at=timezone.now() - timedelta(days=days_ago)
    )
    inbound.raw.save("raw.eml", ContentFile(b"Subject: Hi\r\n\r\nHi"))
    return inbound


def test_raw_mails_past_the_retention_are_emptied_but_rows_stay(
    settings, django_capture_on_commit_callbacks
):
    settings.INBOUND_EMAIL_RAW_RETENTION_DAYS = 30
    recent = _received(29)
    old = _received(31, status=InboundEmail.Status.IGNORED)
    # Still to be processed, or replayed: their mail is all there is.
    pending = _received(31, status=InboundEmail.Status.PENDING)
    failed = _received(31, status=InboundEmail.Status.FAILED)
    storage, old_name = old.raw.storage, old.raw.name

    with django_capture_on_commit_callbacks(execute=True):
        assert purge_inbound_raw() == 1

    old.refresh_from_db()
    assert old.raw.name == ""
    assert not storage.exists(old_name)
    for kept in (recent, pending, failed):
        kept.refresh_from_db()
        assert kept.raw and storage.exists(kept.raw.name)
    assert InboundEmail.objects.count() == 4


def test_the_purge_runs_daily():
    schedule = django_settings.CELERY_BEAT_SCHEDULE["purge-inbound-raw-emails"]

    assert schedule["task"] == "apps.email_channel.tasks.purge_inbound_raw"
    assert schedule["schedule"] == 60 * 60 * 24
