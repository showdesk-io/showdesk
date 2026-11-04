"""Sending from an organization's domain: enable, check, disable (§7).

Every service takes an `OrganizationDomain` row. Provider calls are made
outside any transaction; what they return is written under a row lock, after
re-reading the row, so a transfer or a disable that happened meanwhile wins.

A registration a row lets go of (turned off, replaced, lost with the
domain, deleted with the row) is recorded as a `SendingRemoval` in the same
transaction that clears the row's `sending_provider_ref`; the record stays
until the provider confirmed the removal, retried by
`remove_sending_registration`, and nobody registers that domain meanwhile.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.email_channel.models import SendingRemoval
from apps.organizations.models import OrganizationDomain, is_public_email_domain

from .providers import (
    AlreadyRegisteredError,
    CheckStatus,
    DomainCheck,
    ProviderUnavailableError,
    SendingDomainProvider,
    SendingProviderError,
    get_provider,
    sending_enabled,
)

logger = logging.getLogger(__name__)

# Longer than a registration and its first check could take (a few provider
# calls with a 10 s timeout each), and released as soon as they are done.
ENABLE_LOCK_SECONDS = 300
# "Check now" at most this often per domain: each one hits DNS or the provider.
CHECK_NOW_SECONDS = 30
MAX_ERROR_LENGTH = 500
# Tries of a removal before its task gives up; the hourly sweep tries again.
MAX_REMOVAL_ATTEMPTS = 8

Ownership = OrganizationDomain.Status
Sending = OrganizationDomain.SendingStatus


class SendingError(Exception):
    """A refusal shown to the admin, with the API's `code` and status."""

    code = "sending_error"
    http_status = 400


class NotOwnedError(SendingError):
    code = "not_owned"
    http_status = 400


class PublicDomainError(SendingError):
    code = "public_domain"
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


def sendable_domains(organization_id) -> set[str]:
    """The organization's domains mail may go out from now (§7.1).

    Owned, and verified by the sending provider. None while it is `none`.
    """
    if not sending_enabled():
        return set()
    return set(
        OrganizationDomain.objects.filter(
            organization_id=organization_id,
            status=Ownership.VERIFIED,
            sending_status=Sending.VERIFIED,
        ).values_list("domain", flat=True)
    )


def sendable_address(mailbox, domains: set[str] | None = None) -> str | None:
    """The mailbox's public address, if mail may go out from it (§7.1).

    Decided at each send, never stored: a transfer or a regression takes
    effect on the next mail. `domains`: the organization's sendable domains,
    when already known.
    """
    address = mailbox.public_address
    if not (sending_enabled() and address):
        return None
    domain = address.rpartition("@")[2]
    if domains is None:
        sendable = OrganizationDomain.objects.filter(
            organization_id=mailbox.organization_id,
            domain=domain,
            status=Ownership.VERIFIED,
            sending_status=Sending.VERIFIED,
        ).exists()
    else:
        sendable = domain in domains
    return address if sendable else None


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

    Needs the domain owned, and no registration of it still being removed.
    Already pending or verified: nothing to do. A registration made but not
    stored on the row (the row went, or changed hands, or the write failed)
    is recorded for removal.
    """
    _lock_domain(row.domain)
    try:
        row.refresh_from_db()
        if is_public_email_domain(row.domain):
            raise PublicDomainError("Mail can't be sent from a public webmail domain.")
        if row.status != Ownership.VERIFIED:
            raise NotOwnedError(f"Verify {row.domain} for your organization first.")
        if row.sending_status in (Sending.PENDING, Sending.VERIFIED):
            return row
        try:
            sender = provider()
        except SendingProviderError as exc:
            raise ProviderError(str(exc)) from exc
        if row.sending_provider_ref:
            # A failed registration: replace it, once it is gone.
            _replace_registration(row)
        if SendingRemoval.objects.filter(domain=row.domain).exists():
            raise _removal_pending(row.domain)
        try:
            registered = sender.register(row.domain)
        except AlreadyRegisteredError as exc:
            raise _removal_pending(row.domain) from exc
        except SendingProviderError as exc:
            raise ProviderError(str(exc)) from exc

        try:
            locked = _store_registration(row, registered)
        except Exception:
            with transaction.atomic():
                queue_removal(record_removal(row.domain, registered.ref))
            raise
        if locked is None:
            raise NotOwnedError(f"Verify {row.domain} for your organization first.")
        check_sending(locked, sender=sender)
        return locked
    finally:
        _unlock_domain(row.domain)


def _removal_pending(domain: str) -> RemovalPendingError:
    return RemovalPendingError(
        f"{domain}'s previous sending setup is still being removed. "
        "Try again in a few minutes."
    )


def _replace_registration(row: OrganizationDomain) -> None:
    """Remove the row's own failed registration now, before registering again.

    ProviderError if the provider couldn't: the removal goes on in the
    background, and enabling waits for it.
    """
    with transaction.atomic():
        locked = OrganizationDomain.objects.select_for_update().get(pk=row.pk)
        removal = forget_registration(locked)
        locked.save()
    row.sending_provider_ref = ""
    if removal is not None and not remove_now(removal):
        raise ProviderError(
            f"{row.domain}'s previous sending setup couldn't be removed yet. "
            "Try again in a few minutes."
        )


def _store_registration(row, registered) -> OrganizationDomain | None:
    """Store a new registration on the row, if it still is there and owned.

    Otherwise record the registration for removal and return None.
    """
    with transaction.atomic():
        locked = (
            OrganizationDomain.objects.select_for_update().filter(pk=row.pk).first()
        )
        if locked is None or locked.status != Ownership.VERIFIED:
            # Deleted or transferred while registering: not ours to keep.
            queue_removal(record_removal(row.domain, registered.ref))
            return None
        locked.is_sending = True
        locked.sending_status = Sending.PENDING
        locked.sending_provider_ref = registered.ref
        locked.sending_dns_records = registered.records
        locked.sending_requested_at = timezone.now()
        locked.sending_last_checked_at = None
        locked.sending_last_error = ""
        locked.save()
        return locked


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
    """Stop sending from the domain: reset the state, remove the registration.

    The purpose (`is_sending`) stays. The removal is recorded with the reset,
    tried at once, and retried in the background if the provider failed.
    """
    _lock_domain(row.domain)
    try:
        with transaction.atomic():
            locked = OrganizationDomain.objects.select_for_update().get(pk=row.pk)
            removal = forget_registration(locked)
            _reset(locked)
            locked.save()
        if removal is not None:
            remove_now(removal)
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


def on_ownership_verified(row: OrganizationDomain) -> None:
    """The row's organization just proved it owns the domain: free it elsewhere.

    Called inside the verification's transaction, once the row is saved
    verified; does nothing unless it still is.

    Other organizations' mailboxes lose a public address on the domain, and
    their rows of it lose their sending state; a registration they still hold
    is removed in the background.
    """
    from apps.email_channel.models import Mailbox

    if is_public_email_domain(row.domain):
        return  # Nobody owns it: nothing to take from anybody.
    with transaction.atomic():
        if not OrganizationDomain.objects.filter(
            pk=row.pk, status=Ownership.VERIFIED
        ).exists():
            return  # A stale call: the row lost the domain meanwhile.
        freed = (
            Mailbox.objects.filter(public_address__endswith=f"@{row.domain}")
            .exclude(organization_id=row.organization_id)
            .update(public_address="", updated_at=timezone.now())
        )
        if freed:
            logger.info(
                "Freed %d public address(es) on %s, now verified by %s",
                freed,
                row.domain,
                row.organization_id,
            )
        others = (
            OrganizationDomain.objects.select_for_update()
            .filter(domain=row.domain)
            .exclude(pk=row.pk)
        )
        for other in others:
            if other.sending_status == Sending.NONE and not other.sending_provider_ref:
                continue
            queue_removal(forget_registration(other))
            _reset(other)
            other.save()


def forget_registration(row: OrganizationDomain) -> SendingRemoval | None:
    """Take the row's registration off it and record it for removal.

    In the caller's transaction, with the row locked; the caller saves the
    row. None if it held none.
    """
    ref = row.sending_provider_ref
    if not ref:
        return None
    row.sending_provider_ref = ""
    return record_removal(row.domain, ref)


def record_removal(domain: str, ref: str) -> SendingRemoval:
    """Record a registration to remove; one record per ref."""
    removal, _created = SendingRemoval.objects.get_or_create(
        ref=ref, defaults={"domain": domain}
    )
    return removal


def queue_removal(removal: SendingRemoval | None) -> None:
    """Remove a recorded registration in the background, once committed."""
    from apps.email_channel.tasks import remove_sending_registration

    if removal is not None:
        transaction.on_commit(lambda: remove_sending_registration.delay(removal.pk))


def remove_now(removal: SendingRemoval) -> bool:
    """Try a recorded removal at once; queue it if the provider failed."""
    from apps.email_channel.tasks import remove_sending_registration

    try:
        run_removal(removal.pk)
    except SendingProviderError as exc:
        logger.warning(
            "Removing %s's sending registration failed: %s", removal.domain, exc
        )
        remove_sending_registration.delay(removal.pk)
        return False
    return True


def run_removal(removal_id) -> None:
    """Remove a recorded registration at the provider, then forget the record.

    SendingProviderError if the provider couldn't, counted on the record
    (unless there is no provider at all: ProviderUnavailableError).
    """
    removal = SendingRemoval.objects.filter(pk=removal_id).first()
    if removal is None:
        return  # Done meanwhile.
    try:
        provider().remove(removal.ref)
    except ProviderUnavailableError:
        raise
    except SendingProviderError as exc:
        SendingRemoval.objects.filter(pk=removal.pk).update(
            attempts=F("attempts") + 1, last_error=str(exc)[:MAX_ERROR_LENGTH]
        )
        raise
    removal.delete()
    logger.info("Removed sending registration %s of %s", removal.ref, removal.domain)
