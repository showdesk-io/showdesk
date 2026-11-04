"""The sending domain provider interface, and the configured provider (§7.2).

A provider registers a customer domain for sending, tells which DNS records
the customer must publish, checks them, and removes the registration. It is
chosen by `SENDING_DOMAIN_PROVIDER`:

- `none` (default): the feature is off, mail always goes out from the
  mailbox's inbound address;
- `manual`: the operator's own sending service signs every customer domain
  with one DKIM key; Showdesk checks the records itself (see `manual`);
- `scaleway_tem`: Scaleway Transactional Email (see `scaleway_tem`).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class CheckStatus(enum.StrEnum):
    """What a check says about a registered domain."""

    VERIFIED = "verified"
    PENDING = "pending"  # Not there yet, or no longer.
    FAILED = "failed"  # The provider gave up on it.
    UNKNOWN = "unknown"  # Couldn't tell: change nothing.


@dataclass(frozen=True)
class RegisteredDomain:
    """A domain the provider now knows, and the records to publish for it."""

    ref: str
    records: list[dict[str, str]]


@dataclass(frozen=True)
class DomainCheck:
    """The outcome of one check, with newer records when the provider gives some."""

    status: CheckStatus
    error: str = ""
    records: list[dict[str, str]] | None = None


class SendingProviderError(Exception):
    """The provider refused or could not be reached. The message is shown to admins."""


class SendingDomainProvider(Protocol):
    """What every sending domain provider does."""

    def register(self, domain: str) -> RegisteredDomain: ...

    def check(self, ref: str) -> DomainCheck: ...

    def remove(self, ref: str) -> None: ...


class NoProvider:
    """`none`: nothing can be registered, so nothing is ever sendable."""

    def register(self, domain: str) -> RegisteredDomain:
        raise SendingProviderError(
            "Sending from your own domain is not available on this server."
        )

    def check(self, ref: str) -> DomainCheck:
        return DomainCheck(CheckStatus.UNKNOWN)

    def remove(self, ref: str) -> None:
        return None


def sending_enabled() -> bool:
    """Whether organizations may send from their own domains at all."""
    return settings.SENDING_DOMAIN_PROVIDER != "none"


def get_provider() -> SendingDomainProvider:
    """The configured provider. ImproperlyConfigured if its settings are missing."""
    name = settings.SENDING_DOMAIN_PROVIDER
    if name == "none":
        return NoProvider()
    if name == "manual":
        from .manual import ManualProvider

        return ManualProvider()
    raise ImproperlyConfigured(
        f"Unknown SENDING_DOMAIN_PROVIDER {name!r}: use none, manual or scaleway_tem."
    )
