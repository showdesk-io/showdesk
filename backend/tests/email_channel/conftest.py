"""Shared fixtures of the email channel tests."""

import pytest

from tests.email_channel.mails import INBOUND_DOMAIN


@pytest.fixture(autouse=True)
def _inbound_domain(settings):
    settings.INBOUND_EMAIL_DOMAIN = INBOUND_DOMAIN
