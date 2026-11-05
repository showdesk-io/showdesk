"""Sending from an organization's domain: enable, check, disable (§7).

Every service takes an `OrganizationDomain` row. Provider calls are made
outside any transaction; what they return is written under a row lock, after
re-reading the row, so a transfer or a disable that happened meanwhile wins.

A registration a row lets go of (turned off, replaced, lost with the
domain, deleted with the row) is recorded as a `SendingRemoval` in the same
transaction that clears the row's `sending_provider_ref`, unless the provider
has nothing to remove (`removal_needed`); the record stays until the provider
that made it confirmed the removal, retried by `remove_sending_registration`
and the sweep, and nobody registers that domain meanwhile.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from email.utils import parseaddr
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.email_channel.models import SendingRemoval
from apps.organizations import dns_verification
from apps.organizations.models import (
    OrganizationDomain,
    User,
    is_inbound_email_domain,
    is_public_email_domain,
)

from .providers import (
    AlreadyRegisteredError,
    CheckStatus,
    DomainCheck,
    ProviderUnavailableError,
    SendingDomainProvider,
    SendingProviderError,
    get_provider,
    provider_class,
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
# A pending cycle that hasn't reached verified after this long fails (§7.3).
SENDING_DOMAIN_PENDING_HOURS = 72
# A verified domain is checked again this often by the periodic check.
SENDING_RECHECK_HOURS = 24

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


class OperatorDomainError(SendingError):
    code = "operator_domain"
    http_status = 400


class NotRegisteredError(SendingError):
    code = "not_registered"
    http_status = 400


class RemovalPendingError(SendingError):
    code = "removal_pending"
    http_status = 409


class ProviderConflictError(SendingError):
    code = "provider_conflict"
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


def is_operator_domain(domain: str) -> bool:
    """Whether the domain is the instance's own, never an organization's to
    send from, whatever the provider.

    The domain of `DEFAULT_FROM_EMAIL` and the host of `SITE_URL`, exactly:
    their parent and sibling domains may well be a customer's (an instance
    at `support.acme.com` serving Acme). `INBOUND_EMAIL_DOMAIN` and every
    subdomain of it: the instance's mailboxes live there, nobody else's.
    """
    domain = _normalized_domain(domain)
    if not domain:
        return False
    from_domain = parseaddr(settings.DEFAULT_FROM_EMAIL or "")[1].rpartition("@")[2]
    site_url = (getattr(settings, "SITE_URL", "") or "").strip()
    if site_url and "//" not in site_url:
        site_url = f"//{site_url}"  # A bare host: no scheme to find it after.
    try:
        site_host = urlsplit(site_url).hostname or ""
    except ValueError:
        site_host = ""
    own = {_normalized_domain(from_domain), _normalized_domain(site_host)} - {""}
    if domain in own:
        return True
    return is_inbound_email_domain(domain)


def _normalized_domain(name: str) -> str:
    """A domain as rows store it: lowercase ASCII, without a trailing dot."""
    name = name.strip().rstrip(".")
    try:
        name = name.encode("idna").decode()
    except UnicodeError:
        pass  # Not a name IDNA encodes: compared as written.
    return name.lower()


def _require_not_operator(domain: str) -> None:
    if is_operator_domain(domain):
        raise OperatorDomainError(
            "This domain is used by the Showdesk instance itself."
        )


def sendable_domains(organization_id) -> set[str]:
    """The organization's domains mail may go out from now (§7.1).

    Owned, and verified by the configured sending provider. None while it is
    `none`. A webmail row verified before those were refused never counts.
    """
    if not sending_enabled():
        return set()
    return {
        domain
        for domain in _sendable_rows()
        .filter(organization_id=organization_id)
        .values_list("domain", flat=True)
        if not (is_public_email_domain(domain) or is_operator_domain(domain))
    }


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
    if is_public_email_domain(domain) or is_operator_domain(domain):
        return None  # Nobody's, even if verified before that was refused.
    if domains is None:
        sendable = (
            _sendable_rows()
            .filter(organization_id=mailbox.organization_id, domain=domain)
            .exists()
        )
    else:
        sendable = domain in domains
    return address if sendable else None


def _sendable_rows():
    """Owned rows verified by the configured provider, and registered with it."""
    return OrganizationDomain.objects.filter(
        status=Ownership.VERIFIED,
        sending_status=Sending.VERIFIED,
        sending_provider=settings.SENDING_DOMAIN_PROVIDER,
    )


def provider_switched(row: OrganizationDomain) -> bool:
    """Whether the row's registration was made by another provider."""
    return bool(
        row.sending_provider_ref
        and row.sending_provider
        and row.sending_provider != settings.SENDING_DOMAIN_PROVIDER
    )


def drop_switched_registration(row: OrganizationDomain) -> bool:
    """Reset a row registered by another provider than the configured one.

    Its records were that provider's: the domain falls back, and the admins
    set it up again (no mail: nothing they did changed). The registration
    is recorded for removal by the provider that made it, if it has one to
    remove; the record waits until that provider is configured again.
    Returns whether the row was reset; `row` is updated in place.
    """
    if not provider_switched(row):
        return False
    with transaction.atomic():
        locked = (
            OrganizationDomain.objects.select_for_update().filter(pk=row.pk).first()
        )
        if locked is None or not provider_switched(locked):
            return False
        made_by = locked.sending_provider
        removal = forget_registration(locked)
        _reset(locked)
        locked.save()
    if removal is not None:
        logger.info(
            "Sending registration %s of %s waits for %s to be configured again.",
            removal.ref,
            removal.domain,
            made_by,
        )
    logger.info(
        "Sending domain %s was set up with %s, not %s: reset.",
        row.domain,
        made_by,
        settings.SENDING_DOMAIN_PROVIDER,
    )
    for field in (
        "sending_status",
        "sending_provider_ref",
        "sending_provider",
        "sending_dns_records",
        "sending_requested_at",
        "sending_last_checked_at",
        "sending_last_error",
    ):
        setattr(row, field, getattr(locked, field))
    return True


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


def _lock_domain(domain: str) -> str:
    """Take the domain's lock; returns the token that releases it."""
    token = secrets.token_hex(16)
    if not cache.add(enable_lock_key(domain), token, ENABLE_LOCK_SECONDS):
        raise InProgressError(f"{domain} is being set up already. Try again shortly.")
    return token


def _unlock_domain(domain: str, token: str) -> None:
    """Release the lock if it still is ours: it may have expired and been
    taken by someone else. Between the get and the delete, it could still
    expire and be taken: only after ENABLE_LOCK_SECONDS, an unlikely window
    we accept rather than a Redis script.
    """
    key = enable_lock_key(domain)
    if cache.get(key) == token:
        cache.delete(key)


def enable_sending(row: OrganizationDomain) -> OrganizationDomain:
    """Register the row's domain with the provider, then check it once.

    Needs the domain owned, and no registration of it still being removed.
    Already pending or verified: nothing to do. A registration made but not
    stored on the row (the row went, or changed hands, or the write failed)
    is recorded for removal.
    """
    _require_owned(row)  # Before the lock: a refusal must not hold it.
    token = _lock_domain(row.domain)
    try:
        row.refresh_from_db()
        _require_owned(row)
        _ensure_ownership_token(row)
        drop_switched_registration(row)
        if row.sending_status in (Sending.PENDING, Sending.VERIFIED):
            return row
        try:
            sender = provider()
        except SendingProviderError as exc:
            raise ProviderError(str(exc)) from exc
        if row.sending_provider_ref:
            # A failed registration: replace it, once it is gone.
            _replace_registration(row)
        if _removal_pending_here(row.domain):
            raise _removal_pending(row.domain)
        try:
            registered = sender.register(row.domain)
        except AlreadyRegisteredError as exc:
            if _removal_pending_here(row.domain):
                raise _removal_pending(row.domain) from exc
            # Not ours to wait for: registered by hand, or a record lost.
            logger.error(
                "The sending provider already holds %s, with no removal of ours "
                "pending: %s",
                row.domain,
                exc,
            )
            raise ProviderConflictError(
                "This domain is already registered with the sending service. "
                "Contact your Showdesk administrator."
            ) from exc
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
        _unlock_domain(row.domain, token)


def _require_owned(row: OrganizationDomain) -> None:
    """Refuse a webmail domain, the instance's own, or one the row's
    organization doesn't own."""
    _require_not_operator(row.domain)
    if is_public_email_domain(row.domain):
        raise PublicDomainError("Mail can't be sent from a public webmail domain.")
    if row.status != Ownership.VERIFIED:
        raise NotOwnedError(f"Verify {row.domain} for your organization first.")


def _ensure_ownership_token(row: OrganizationDomain) -> None:
    """Give the row the token of its `_showdesk` TXT, if it has none.

    A row verified through an admin's email has none. Only the token is
    written: the ownership status and method stay as they are.
    """
    if row.verification_token:
        return
    OrganizationDomain.objects.filter(pk=row.pk, verification_token="").update(
        verification_token=OrganizationDomain.generate_token(),
        updated_at=timezone.now(),
    )
    row.refresh_from_db(fields=["verification_token"])


def ownership_record(row: OrganizationDomain) -> dict[str, str]:
    """The row's `_showdesk` TXT: the organization's own proof in the DNS."""
    return {"type": "TXT", "name": row.txt_record_name, "value": row.txt_record_value}


def _with_ownership_record(row: OrganizationDomain, records) -> list[dict]:
    """The records to publish: the row's current `_showdesk` TXT, then the
    provider's (any older `_showdesk` TXT dropped)."""
    own = ownership_record(row)
    return [
        own,
        *(
            r
            for r in records
            if not (r.get("type") == "TXT" and r.get("name") == own["name"])
        ),
    ]


def _removal_pending_here(domain: str) -> bool:
    """Whether a registration of the domain waits for removal by the
    configured provider (or by whichever is configured: provider unknown).

    One waiting for another provider is held elsewhere: it doesn't conflict
    with a registration here, and may wait for good.
    """
    return SendingRemoval.objects.filter(
        domain=domain, provider__in=("", settings.SENDING_DOMAIN_PROVIDER)
    ).exists()


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

    Otherwise record the registration for removal and return None. A ref
    the row got meanwhile is recorded for removal, never overwritten.
    """
    with transaction.atomic():
        locked = (
            OrganizationDomain.objects.select_for_update().filter(pk=row.pk).first()
        )
        if locked is None or locked.status != Ownership.VERIFIED:
            # Deleted or transferred while registering: not ours to keep.
            queue_removal(record_removal(row.domain, registered.ref))
            return None
        if locked.sending_provider_ref != registered.ref:
            queue_removal(forget_registration(locked))
        locked.is_sending = True
        locked.sending_status = Sending.PENDING
        locked.sending_provider_ref = registered.ref
        locked.sending_provider = settings.SENDING_DOMAIN_PROVIDER
        locked.sending_dns_records = _with_ownership_record(locked, registered.records)
        locked.sending_requested_at = timezone.now()
        locked.sending_last_checked_at = None
        locked.sending_last_error = ""
        locked.save()
        return locked


def check_now(row: OrganizationDomain) -> OrganizationDomain:
    """An admin's "Check now": at most once per CHECK_NOW_SECONDS per domain."""
    _require_checkable(row)
    if drop_switched_registration(row):
        return row
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
    _require_not_operator(row.domain)
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
    `sending_last_checked_at`, and not even that on a verified row: it stays
    due, so the next periodic check tries again.
    """
    _require_checkable(row)
    ref = row.sending_provider_ref
    try:
        result = (sender or provider()).check(ref)
    except SendingProviderError as exc:
        logger.warning("Sending check of %s couldn't conclude: %s", row.domain, exc)
        result = DomainCheck(CheckStatus.UNKNOWN)
    result = _with_ownership_check(row, result)
    apply_check(row, ref, result)
    return result.status


OWNERSHIP_RECORD_MISSING = (
    "The _showdesk TXT record proving your organization controls this domain "
    "is missing."
)


def _with_ownership_check(row: OrganizationDomain, result: DomainCheck) -> DomainCheck:
    """The provider's result, with the row's `_showdesk` TXT checked too.

    Sending needs the organization's own proof in the domain's DNS, whatever
    the provider and however ownership was verified: `manual`'s records are
    the same for every organization, and an admin's mailbox doesn't prove
    control of the DNS. A provider FAILED or UNKNOWN result stands; a TXT
    lookup that can't conclude is UNKNOWN; a missing TXT is PENDING.

    The records come back with the row's current TXT first, refreshed even
    when the provider returns none: the token may have changed since.
    """
    records = _with_ownership_record(
        row, result.records or row.sending_dns_records or []
    )
    if result.status in (CheckStatus.FAILED, CheckStatus.UNKNOWN):
        return DomainCheck(result.status, result.error, records)
    found = dns_verification.lookup_txt(row.txt_record_name)
    if found is None:
        return DomainCheck(CheckStatus.UNKNOWN)
    if row.verification_token and row.txt_record_value in found:
        return DomainCheck(result.status, result.error, records)
    error = f"{OWNERSHIP_RECORD_MISSING} {result.error}".strip()
    return DomainCheck(CheckStatus.PENDING, error, records)


def next_sending_status(
    current: str, result: CheckStatus, *, expired: bool = False
) -> str:
    """The sending status after a check: the one place transitions are decided.

    `expired`: the current pending cycle is older than
    SENDING_DOMAIN_PENDING_HOURS.
    """
    if result == CheckStatus.VERIFIED:
        return Sending.VERIFIED
    if result == CheckStatus.FAILED:
        return Sending.FAILED
    if result == CheckStatus.PENDING and current == Sending.VERIFIED:
        return Sending.PENDING  # A regression.
    if result == CheckStatus.PENDING and current == Sending.PENDING and expired:
        return Sending.FAILED
    return current


def _pending_expired(row: OrganizationDomain, now) -> bool:
    started = row.sending_requested_at
    return started is not None and now - started > timedelta(
        hours=SENDING_DOMAIN_PENDING_HOURS
    )


# The admins' mail for each transition, by the state reached (see
# `_transition_mail`).
STATUS_MAIL_SUBJECTS = {
    "verified": "You now send from {domain}",
    "regressed": (
        "Sending from {domain} stopped: we will keep checking for "
        f"{SENDING_DOMAIN_PENDING_HOURS} hours"
    ),
    "failed": "Sending from {domain} failed",
}


def _transition_mail(previous: str, current: str) -> str | None:
    """Which mail a transition sends the admins, if any."""
    if previous == current:
        return None
    if current == Sending.VERIFIED:
        return "verified"
    if current == Sending.PENDING and previous == Sending.VERIFIED:
        return "regressed"
    if current == Sending.FAILED:
        return "failed"
    return None


def notify_sending_status(row: OrganizationDomain, state: str) -> None:
    """Mail the row's organization's active admins where its sending stands."""
    from apps.core.email import send_branded_email

    organization = row.organization
    recipients = list(
        organization.users.filter(role=User.Role.ADMIN, is_active=True).values_list(
            "email", flat=True
        )
    )
    if not recipients:
        return
    send_branded_email(
        template="sending_domain_status",
        subject=STATUS_MAIL_SUBJECTS[state].format(domain=row.domain),
        to=recipients,
        organization=organization,
        context={
            "state": state,
            "domain": row.domain,
            "org_name": organization.name,
            "error": row.sending_last_error,
            "pending_hours": SENDING_DOMAIN_PENDING_HOURS,
            "settings_url": f"{getattr(settings, 'SITE_URL', '')}/settings",
        },
        fail_silently=True,
    )


def apply_check(
    row: OrganizationDomain, ref: str, result: DomainCheck
) -> tuple[str, str] | None:
    """Store a check's outcome on the row, unless the row moved on meanwhile.

    Returns the sending status before and after, None if nothing was stored;
    `row` is updated in place. Transitions go through `next_sending_status`;
    a regression starts a new pending cycle, and each transition mails the
    admins once committed.

    Two checks of the same ref (the beat's and a "Check now") may finish out
    of order, the older result written last. That is rare (checks are
    seconds apart at most, "Check now" is rate-limited) and bounded: the next
    check, at most a beat away for a pending row, writes the current state.
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
        fields = []
        if result.status != CheckStatus.UNKNOWN or previous != Sending.VERIFIED:
            # An inconclusive check of a verified row leaves it due, so that
            # the next periodic check tries again rather than in a day.
            locked.sending_last_checked_at = now
            fields.append("sending_last_checked_at")
        if result.status != CheckStatus.UNKNOWN:
            expired = _pending_expired(locked, now)
            locked.sending_status = next_sending_status(
                previous, result.status, expired=expired
            )
            if (
                previous == Sending.VERIFIED
                and locked.sending_status == Sending.PENDING
            ):
                locked.sending_requested_at = now
            error = result.error
            if result.status == CheckStatus.PENDING:
                if previous == Sending.PENDING and locked.sending_status == (
                    Sending.FAILED
                ):
                    error = (
                        f"Not verified within {SENDING_DOMAIN_PENDING_HOURS} "
                        f"hours. {error}"
                    ).strip()
                elif previous == Sending.FAILED:
                    # Still failed: the error that failed it stays.
                    error = locked.sending_last_error
            locked.sending_last_error = error[:MAX_ERROR_LENGTH]
            fields += ["sending_status", "sending_requested_at", "sending_last_error"]
            if result.records:
                locked.sending_dns_records = result.records
                fields.append("sending_dns_records")
        if fields:
            locked.save(update_fields=[*fields, "updated_at"])
        if previous != locked.sending_status:
            logger.info(
                "Sending domain %s: %s -> %s",
                locked.domain,
                previous or "none",
                locked.sending_status,
            )
        state = _transition_mail(previous, locked.sending_status)
        if state is not None:
            transaction.on_commit(lambda: notify_sending_status(locked, state))
    for field in fields:
        setattr(row, field, getattr(locked, field))
    return previous, locked.sending_status


def disable_sending(row: OrganizationDomain) -> OrganizationDomain:
    """Stop sending from the domain: reset the state, remove the registration.

    The purpose (`is_sending`) stays. The removal is recorded with the reset,
    tried at once, and retried in the background if the provider failed.
    Needs the domain owned, as enabling does.
    """
    _require_owned(row)  # Before the lock: a refusal must not hold it.
    token = _lock_domain(row.domain)
    try:
        with transaction.atomic():
            locked = OrganizationDomain.objects.select_for_update().get(pk=row.pk)
            _require_owned(locked)
            removal = forget_registration(locked)
            _reset(locked)
            locked.save()
        if removal is not None:
            remove_now(removal)
        return locked
    finally:
        _unlock_domain(row.domain, token)


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
    their rows of it lose their token (a TXT left published must not win the
    domain back: their admins regenerate one) and their sending state; a
    registration they still hold is removed in the background.
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
            other.verification_token = ""
            if other.sending_status != Sending.NONE or other.sending_provider_ref:
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
    made_by = row.sending_provider
    row.sending_provider_ref = ""
    row.sending_provider = ""
    return record_removal(row.domain, ref, made_by)


def record_removal(domain: str, ref: str, made_by: str = "") -> SendingRemoval | None:
    """Record a registration to remove; one record per ref.

    `made_by`: the provider that made it, "" for the configured one. None
    when that provider's registrations exist nowhere but on our row
    (`manual`): nothing to remove, nothing to wait for. Made while no
    provider is configured, the record's provider is unknown (""): the next
    one configured removes it. None as well for the instance's own domains:
    never removed, whatever lets go of them.
    """
    if is_operator_domain(domain):
        # The instance's own sender (or one made before that was refused):
        # it sends the instance's mail, nobody's to take away.
        logger.error(
            "Not removing the sending registration of the instance's own domain "
            "%s (ref %s): remove it by hand if it is really unused.",
            domain,
            ref,
        )
        return None
    configured = settings.SENDING_DOMAIN_PROVIDER
    name = made_by or configured
    if name == "none":
        name = ""
    if name:
        try:
            maker = get_provider() if name == configured else provider_class(name)
            needed = maker.removal_needed
        except ImproperlyConfigured:
            needed = True  # Can't tell: keep the record, it is cheap.
        if not needed:
            return None
    removal, _created = SendingRemoval.objects.get_or_create(
        ref=ref, defaults={"domain": domain, "provider": name}
    )
    return removal


def queue_removal(removal: SendingRemoval | None) -> None:
    """Remove a recorded registration in the background, once committed."""
    if removal is not None:
        transaction.on_commit(lambda: enqueue_removal(removal.pk))


def enqueue_removal(removal_id) -> None:
    """Queue a removal's task. A broker down is only logged: the sweep's job."""
    from apps.email_channel.tasks import remove_sending_registration

    try:
        remove_sending_registration.delay(removal_id)
    except Exception:
        logger.exception(
            "Couldn't queue sending removal %s; the sweep will.", removal_id
        )


def remove_now(removal: SendingRemoval) -> bool:
    """Try a recorded removal at once; queue it if the provider failed."""
    try:
        run_removal(removal.pk)
    except SendingProviderError as exc:
        logger.warning(
            "Removing %s's sending registration failed: %s", removal.domain, exc
        )
        enqueue_removal(removal.pk)
        return False
    return True


def run_removal(removal_id) -> None:
    """Remove a recorded registration at the provider, then forget the record.

    SendingProviderError if the provider couldn't, counted on the record.
    ProviderUnavailableError, not counted, if the configured provider can't
    remove it: `none`, or another than the one that made it. Every try
    stamps `last_attempt_at`, which the sweep goes by.
    """
    removal = SendingRemoval.objects.filter(pk=removal_id).first()
    if removal is None:
        return  # Done meanwhile.
    SendingRemoval.objects.filter(pk=removal.pk).update(last_attempt_at=timezone.now())
    configured = settings.SENDING_DOMAIN_PROVIDER
    if removal.provider and removal.provider != configured:
        raise ProviderUnavailableError(
            f"Registration {removal.ref} was made by {removal.provider}, "
            f"not by the configured provider ({configured})."
        )
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
