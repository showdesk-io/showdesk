"""Sending from an organization's domain: enable, check, disable (§7).

Every service takes an `OrganizationDomain` row. Provider calls are made
outside any transaction; what they return is written under a row lock, after
re-reading the row, so a transfer or a disable that happened meanwhile wins.

A registration the provider still holds is remembered in the row's
`sending_provider_ref` until the provider confirmed its removal: removals
that fail are retried by `remove_sending_registration`.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from apps.organizations.models import OrganizationDomain

from .providers import (
    CheckStatus,
    DomainCheck,
    SendingDomainProvider,
    SendingProviderError,
    get_provider,
)

logger = logging.getLogger(__name__)

# Long enough for a registration and its first check (two provider calls with
# a 10 s timeout each), and released as soon as they are done.
ENABLE_LOCK_SECONDS = 120
# "Check now" at most this often per domain: each one hits DNS or the provider.
CHECK_NOW_SECONDS = 30
MAX_ERROR_LENGTH = 500

Ownership = OrganizationDomain.Status
Sending = OrganizationDomain.SendingStatus


class SendingError(Exception):
    """A refusal shown to the admin, with the API's `code` and status."""

    code = "sending_error"
    http_status = 400


class NotOwnedError(SendingError):
    code = "not_owned"
    http_status = 400


class NotRegisteredError(SendingError):
    code = "not_registered"
    http_status = 400


class RemovalPendingError(SendingError):
    code = "removal_pending"
    http_status = 409


class InProgressError(SendingError):
    code = "in_progress"
    http_status = 409


class TooSoonError(SendingError):
    code = "too_soon"
    http_status = 429


class ProviderError(SendingError):
    code = "provider_error"
    http_status = 502


def provider() -> SendingDomainProvider:
    """The configured provider; a misconfiguration is a SendingProviderError.

    The settings' names stay in the log: admins only learn that it failed.
    """
    try:
        return get_provider()
    except ImproperlyConfigured:
        logger.exception("The sending domain provider is misconfigured.")
        raise SendingProviderError(
            "Sending from your own domain is unavailable on this server right now."
        ) from None


def enable_lock_key(domain: str) -> str:
    return f"email_channel:sending:enable:{domain}"


def check_lock_key(row: OrganizationDomain) -> str:
    return f"email_channel:sending:check:{row.pk}"


def _lock_domain(domain: str) -> None:
    if not cache.add(enable_lock_key(domain), 1, ENABLE_LOCK_SECONDS):
        raise InProgressError(f"{domain} is being set up already. Try again shortly.")


def _unlock_domain(domain: str) -> None:
    cache.delete(enable_lock_key(domain))


def enable_sending(row: OrganizationDomain) -> OrganizationDomain:
    """Register the row's domain with the provider, then check it once.

    Needs the domain owned, and no other organization's registration of it
    still being removed. Already pending or verified: nothing to do.
    """
    _lock_domain(row.domain)
    try:
        row.refresh_from_db()
        if row.status != Ownership.VERIFIED:
            raise NotOwnedError(f"Verify {row.domain} for your organization first.")
        if row.sending_status in (Sending.PENDING, Sending.VERIFIED):
            return row
        if (
            OrganizationDomain.objects.filter(domain=row.domain)
            .exclude(pk=row.pk)
            .exclude(sending_provider_ref="")
            .exists()
        ):
            raise RemovalPendingError(
                f"{row.domain}'s previous sending setup is still being removed. "
                "Try again in a few minutes."
            )
        try:
            sender = provider()
            old_ref = row.sending_provider_ref
            if old_ref:
                # A failed or turned-off registration: replace it.
                sender.remove(old_ref)
                _forget_ref(old_ref, row.pk)
            registered = sender.register(row.domain)
        except SendingProviderError as exc:
            raise ProviderError(str(exc)) from exc

        with transaction.atomic():
            locked = OrganizationDomain.objects.select_for_update().get(pk=row.pk)
            owned = locked.status == Ownership.VERIFIED
            if owned:
                locked.is_sending = True
                locked.sending_status = Sending.PENDING
                locked.sending_provider_ref = registered.ref
                locked.sending_dns_records = registered.records
                locked.sending_requested_at = timezone.now()
                locked.sending_last_checked_at = None
                locked.sending_last_error = ""
                locked.save()
            else:
                # Transferred while registering: the registration isn't ours.
                queue_removal(registered.ref)
        if not owned:
            raise NotOwnedError(f"Verify {row.domain} for your organization first.")
        check_sending(locked, sender=sender)
        return locked
    finally:
        _unlock_domain(row.domain)


def check_now(row: OrganizationDomain) -> OrganizationDomain:
    """An admin's "Check now": at most once per CHECK_NOW_SECONDS per domain."""
    _require_checkable(row)
    if not cache.add(check_lock_key(row), 1, CHECK_NOW_SECONDS):
        raise TooSoonError(
            "This domain was checked a moment ago. Try again in a few seconds."
        )
    try:
        sender = provider()
    except SendingProviderError as exc:
        raise ProviderError(str(exc)) from exc
    check_sending(row, sender=sender)
    return row


def _require_checkable(row: OrganizationDomain) -> None:
    if row.status != Ownership.VERIFIED:
        raise NotOwnedError(f"Verify {row.domain} for your organization first.")
    if row.sending_status == Sending.NONE or not row.sending_provider_ref:
        raise NotRegisteredError(f"Sending isn't set up for {row.domain}.")


def check_sending(
    row: OrganizationDomain, *, sender: SendingDomainProvider | None = None
) -> CheckStatus:
    """Ask the provider where the row's registration stands, and apply it.

    Only an owned and registered domain is checked. A check that can't
    conclude (UNKNOWN, or a provider error) changes nothing but
    `sending_last_checked_at`.
    """
    _require_checkable(row)
    ref = row.sending_provider_ref
    try:
        result = (sender or provider()).check(ref)
    except SendingProviderError as exc:
        logger.warning("Sending check of %s couldn't conclude: %s", row.domain, exc)
        result = DomainCheck(CheckStatus.UNKNOWN)
    apply_check(row, ref, result)
    return result.status


def next_sending_status(current: str, result: CheckStatus) -> str:
    """The sending status after a check: the one place transitions are decided."""
    if result == CheckStatus.VERIFIED:
        return Sending.VERIFIED
    if result == CheckStatus.FAILED:
        return Sending.FAILED
    if result == CheckStatus.PENDING and current == Sending.VERIFIED:
        return Sending.PENDING  # A regression.
    return current


def apply_check(
    row: OrganizationDomain, ref: str, result: DomainCheck
) -> tuple[str, str] | None:
    """Store a check's outcome on the row, unless the row moved on meanwhile.

    Returns the sending status before and after, None if nothing was stored;
    `row` is updated in place. Transitions go through `next_sending_status`,
    and a regression starts a new pending cycle.
    """
    now = timezone.now()
    with transaction.atomic():
        locked = (
            OrganizationDomain.objects.select_for_update().filter(pk=row.pk).first()
        )
        if (
            locked is None
            or locked.status != Ownership.VERIFIED
            or locked.sending_provider_ref != ref
            or locked.sending_status == Sending.NONE
        ):
            return None
        previous = locked.sending_status
        locked.sending_last_checked_at = now
        fields = ["sending_last_checked_at"]
        if result.status != CheckStatus.UNKNOWN:
            locked.sending_status = next_sending_status(previous, result.status)
            if (
                previous == Sending.VERIFIED
                and locked.sending_status == Sending.PENDING
            ):
                locked.sending_requested_at = now
            locked.sending_last_error = result.error[:MAX_ERROR_LENGTH]
            fields += ["sending_status", "sending_requested_at", "sending_last_error"]
            if result.records:
                locked.sending_dns_records = result.records
                fields.append("sending_dns_records")
        locked.save(update_fields=[*fields, "updated_at"])
        if previous != locked.sending_status:
            logger.info(
                "Sending domain %s: %s -> %s",
                locked.domain,
                previous or "none",
                locked.sending_status,
            )
    for field in fields:
        setattr(row, field, getattr(locked, field))
    return previous, locked.sending_status


def disable_sending(row: OrganizationDomain) -> OrganizationDomain:
    """Stop sending from the domain: remove the registration, reset the state.

    The purpose (`is_sending`) stays. A removal that fails is retried in the
    background, the row keeping the ref meanwhile.
    """
    _lock_domain(row.domain)
    try:
        row.refresh_from_db()
        ref = row.sending_provider_ref
        removed = True
        if ref:
            try:
                provider().remove(ref)
            except SendingProviderError as exc:
                logger.warning(
                    "Removing %s's sending registration failed: %s", row.domain, exc
                )
                removed = False
        with transaction.atomic():
            locked = OrganizationDomain.objects.select_for_update().get(pk=row.pk)
            _reset(locked)
            if ref and locked.sending_provider_ref == ref:
                if removed:
                    locked.sending_provider_ref = ""
                else:
                    queue_removal(ref, locked.pk)
            locked.save()
        return locked
    finally:
        _unlock_domain(row.domain)


def _reset(row: OrganizationDomain) -> None:
    """Back to "not set up", the ref aside (see `sending_provider_ref`)."""
    row.sending_status = Sending.NONE
    row.sending_dns_records = []
    row.sending_requested_at = None
    row.sending_last_checked_at = None
    row.sending_last_error = ""


def queue_removal(ref: str, row_id=None) -> None:
    """Remove a registration in the background, once the transaction commits."""
    from apps.email_channel.tasks import remove_sending_registration

    transaction.on_commit(
        lambda: remove_sending_registration.delay(
            ref, str(row_id) if row_id is not None else None
        )
    )


def remove_registration(ref: str, row_id=None) -> None:
    """Remove a registration at the provider, then forget it on the row.

    SendingProviderError if the provider couldn't: the caller retries.
    """
    provider().remove(ref)
    if row_id is not None:
        _forget_ref(ref, row_id)


def _forget_ref(ref: str, row_id) -> None:
    """Clear the row's ref if it still is this one."""
    OrganizationDomain.objects.filter(pk=row_id, sending_provider_ref=ref).update(
        sending_provider_ref="", updated_at=timezone.now()
    )
