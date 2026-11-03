"""Expired one-time codes are deleted every day: nothing reads them any more."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.organizations.models import OTPCode
from apps.organizations.tasks import purge_expired_otp_codes
from apps.tickets.models import WidgetSession
from tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_expired_codes_of_every_purpose_are_purged_daily(settings):
    settings.OTP_EXPIRY_SECONDS = 600
    org = OrganizationFactory()
    session = WidgetSession.objects.create(organization=org, email="a@x.io")
    expired_login = OTPCode.generate("a@x.io")
    expired_widget = OTPCode.generate(
        "a@x.io",
        purpose=OTPCode.Purpose.WIDGET_EMAIL,
        organization=org,
        widget_session=session,
    )
    used = OTPCode.generate("b@x.io")
    OTPCode.objects.filter(pk=used.pk).update(used_at=timezone.now())
    long_ago = timezone.now() - timedelta(seconds=601)
    OTPCode.objects.filter(pk__in=[expired_login.pk, expired_widget.pk]).update(
        created_at=long_ago
    )
    fresh = OTPCode.generate("c@x.io")

    assert purge_expired_otp_codes() == 2

    assert set(OTPCode.objects.values_list("pk", flat=True)) == {used.pk, fresh.pk}
    assert settings.CELERY_BEAT_SCHEDULE["purge-expired-otp-codes"] == {
        "task": "apps.organizations.tasks.purge_expired_otp_codes",
        "schedule": 60 * 60 * 24,
    }
