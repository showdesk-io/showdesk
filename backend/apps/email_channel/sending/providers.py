"""The sending domain provider interface, and the configured provider (§7.2).

A provider registers a customer domain for sending, tells which DNS records
the customer must publish, checks them, and removes the registration. It is
chosen by `SENDING_DOMAIN_PROVIDER`:

- `none` (default): the feature is off, mail always goes out from the
  mailbox's inbound address;
- `manual`: the operator's own sending service signs every customer domain
  with one DKIM key; Showdesk checks the records itself (see `manual`);
- `scaleway_tem`: Scaleway Transactional Email (see `scaleway_tem`);
- `mailjet`: Mailjet, the account Anymail sends with (see `mailjet`);
- `postal`: one server of a self-hosted Postal, through the Postal domains
  service run next to it (see `postal`).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Protocol

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
    # [{type, name, value}], plus `merge: True` on a record a domain has at
    # most one of (SPF, DMARC): merge into an existing one, don't add another.
    records: list[dict[str, Any]]


@dataclass(frozen=True)
class DomainCheck:
    """The outcome of one check, with newer records when the provider gives some."""

    status: CheckStatus
    error: str = ""
    records: list[dict[str, Any]] | None = None


class SendingProviderError(Exception):
    """The provider refused or could not be reached. The message is shown to admins."""


class AlreadyRegisteredError(SendingProviderError):
    """The provider already holds a registration of this domain name."""


class ProviderUnavailableError(SendingProviderError):
    """No provider is configured: nothing can be done at one, removals wait."""


class SendingDomainProvider(Protocol):
    """What every sending domain provider does.

    `removal_needed`: whether a registration it made exists anywhere but on
    our row, so that letting go of one must be recorded and removed there.
    """

    removal_needed: bool

    def register(self, domain: str) -> RegisteredDomain: ...

    def check(self, ref: str) -> DomainCheck: ...

    def remove(self, ref: str) -> None: ...


class NoProvider:
    """`none`: nothing can be registered, so nothing is ever sendable."""

    # It makes no registration. One let go of while it is configured was made
    # by another provider: see `services.record_removal`.
    removal_needed = False

    def register(self, domain: str) -> RegisteredDomain:
        raise SendingProviderError(
            "Sending from your own domain is not available on this server."
        )

    def check(self, ref: str) -> DomainCheck:
        return DomainCheck(CheckStatus.UNKNOWN)

    def remove(self, ref: str) -> None:
        # A registration made under another provider is still there: the
        # removal must wait for one, not be taken as done.
        raise ProviderUnavailableError(
            "No sending domain provider is configured to remove this registration."
        )


def sending_enabled() -> bool:
    """Whether organizations may send from their own domains at all."""
    return settings.SENDING_DOMAIN_PROVIDER != "none"


def provider_class(name: str) -> type[SendingDomainProvider]:
    """The class of the provider called `name`. ImproperlyConfigured if unknown."""
    if name == "none":
        return NoProvider
    if name == "manual":
        from .manual import ManualProvider

        return ManualProvider
    if name == "scaleway_tem":
        from .scaleway_tem import ScalewayTEMProvider

        return ScalewayTEMProvider
    if name == "mailjet":
        from .mailjet import MailjetProvider

        return MailjetProvider
    if name == "postal":
        from .postal import PostalProvider

        return PostalProvider
    raise ImproperlyConfigured(
        f"Unknown SENDING_DOMAIN_PROVIDER {name!r}: "
        "use none, manual, scaleway_tem, mailjet or postal."
    )


def get_provider() -> SendingDomainProvider:
    """The configured provider. ImproperlyConfigured if its settings are missing."""
    return provider_class(settings.SENDING_DOMAIN_PROVIDER)()
