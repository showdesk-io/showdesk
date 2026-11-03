"""Shared fixtures of the email channel tests."""

import importlib

import pytest
from anymail.signals import inbound
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings
from django.urls import clear_url_caches

from tests.email_channel.mails import INBOUND_DOMAIN
from tests.email_channel.postal import new_postal_key, public_key_setting


@pytest.fixture(autouse=True)
def _inbound_domain(settings):
    settings.INBOUND_EMAIL_DOMAIN = INBOUND_DOMAIN


def _reload_urls() -> None:
    importlib.reload(importlib.import_module("config.urls"))
    clear_url_caches()


@pytest.fixture
def mount():
    """Rebuild the URLs under settings: which webhooks exist is decided at import."""
    overrides = []

    def _mount(**settings) -> None:
        override = override_settings(**settings)
        override.enable()
        overrides.append(override)
        _reload_urls()

    yield _mount
    for override in reversed(overrides):
        override.disable()
    _reload_urls()


@pytest.fixture
def received():
    """The events of the ``inbound`` signal."""
    events = []

    def receiver(sender, event, esp_name, **kwargs) -> None:
        events.append(event)

    inbound.connect(receiver)
    yield events
    inbound.disconnect(receiver)


@pytest.fixture
def postal_key(mount, settings) -> rsa.RSAPrivateKey:
    """Postal's webhook mounted, with the key a test signs with."""
    key = new_postal_key()
    mount(
        INBOUND_EMAIL_DOMAIN=INBOUND_DOMAIN,
        ANYMAIL={**settings.ANYMAIL, "POSTAL_WEBHOOK_KEY": public_key_setting(key)},
    )
    return key
