"""Domain verification services.

Two paths flip an OrganizationDomain row from `pending` to `verified`:
  - admin_email auto-verify: an admin in the org has a verified email
    on this domain. Cheap, runs synchronously at create-domain time.
    Refused if the domain is already verified by another org.
  - DNS TXT challenge: the org publishes a Showdesk-issued token on
    `_showdesk.<domain>`. Triggered by the verify endpoint or the
    Celery pending-poller; on success transfers ownership atomically
    if another org previously held the domain verified.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.email import send_branded_email

from .dns_verification import verify_domain_dns
from .models import (
    Organization,
    OrganizationDomain,
    User,
    is_public_email_domain,
)

logger = logging.getLogger(__name__)


class DomainVerificationError(Exception):
    """Base class for domain-verification errors raised to API callers."""

    code = "verification_failed"


class CannotAutoVerifyError(DomainVerificationError):
    """admin_email auto-verify is not eligible for this org+domain."""

    code = "cannot_autoverify"


class DomainAlreadyClaimedError(DomainVerificationError):
    """Another org has this domain verified — must use DNS to take it over."""

    code = "use_dns_instead"


# ---------------------------------------------------------------------------
# admin_email auto-verify
# ---------------------------------------------------------------------------


def has_eligible_admin(org: Organization, domain: str) -> bool:
    """True if some active admin in `org` has a verified email on `domain`."""
    return org.users.filter(
        role=User.Role.ADMIN,
        is_active=True,
        is_verified=True,
        email__iendswith=f"@{domain.lower()}",
    ).exists()


def is_domain_taken_elsewhere(domain: str, *, exclude_org: Organization | None = None) -> bool:
    """True if some other org currently holds `domain` verified."""
    qs = OrganizationDomain.objects.filter(
        domain=domain.lower(),
        status=OrganizationDomain.Status.VERIFIED,
    )
    if exclude_org is not None:
        qs = qs.exclude(organization=exclude_org)
    return qs.exists()


@transaction.atomic
def try_admin_email_autoverify(
    *,
    organization: Organization,
    domain: str,
    is_branding: bool = False,
    is_email_routing: bool = True,
) -> OrganizationDomain:
    """Create or upgrade a row to verified via admin_email.

    Refuses for public webmail providers, when no eligible admin exists,
    or when another org has already claimed the domain. The caller is
    expected to surface those refusals to the user with the structured
    `code` from the raised exception.
    """
    domain = domain.lower().strip()

    if is_email_routing and is_public_email_domain(domain):
        raise CannotAutoVerifyError(
            "Public webmail providers cannot be used for email routing."
        )

    if not has_eligible_admin(organization, domain):
        raise CannotAutoVerifyError(
            "No admin in this organization has a verified email on this domain."
        )

    if is_domain_taken_elsewhere(domain, exclude_org=organization):
        raise DomainAlreadyClaimedError(
            "This domain is already verified by another organization. "
            "Use DNS verification to claim ownership."
        )

    row, _created = OrganizationDomain.objects.update_or_create(
        organization=organization,
        domain=domain,
        defaults={
            "is_branding": is_branding,
            "is_email_routing": is_email_routing,
            "status": OrganizationDomain.Status.VERIFIED,
            "verification_method": OrganizationDomain.VerificationMethod.ADMIN_EMAIL,
            "verified_at": timezone.now(),
            "last_check_at": timezone.now(),
        },
    )
    logger.info(
        "Domain %s auto-verified for org %s via admin_email",
        domain,
        organization.slug,
    )
    return row


# ---------------------------------------------------------------------------
# DNS TXT challenge
# ---------------------------------------------------------------------------


def start_dns_challenge(
    *,
    organization: Organization,
    domain: str,
    is_branding: bool = False,
    is_email_routing: bool = False,
) -> OrganizationDomain:
    """Create or reset a row in pending state with a fresh DNS token."""
    domain = domain.lower().strip()
    row, _created = OrganizationDomain.objects.update_or_create(
        organization=organization,
        domain=domain,
        defaults={
            "is_branding": is_branding,
            "is_email_routing": is_email_routing,
            "status": OrganizationDomain.Status.PENDING,
            "verification_method": OrganizationDomain.VerificationMethod.DNS_TXT,
            "verification_token": OrganizationDomain.generate_token(),
            "verified_at": None,
            "last_check_at": None,
        },
    )
    return row


def regenerate_dns_token(domain_obj: OrganizationDomain) -> OrganizationDomain:
    """Issue a fresh token, reset to pending. Caller is the row's admin."""
    domain_obj.verification_token = OrganizationDomain.generate_token()
    domain_obj.status = OrganizationDomain.Status.PENDING
    domain_obj.verification_method = OrganizationDomain.VerificationMethod.DNS_TXT
    domain_obj.last_check_at = None
    domain_obj.save(
        update_fields=[
            "verification_token",
            "status",
            "verification_method",
            "last_check_at",
        ]
    )
    return domain_obj


def perform_dns_check(domain_obj: OrganizationDomain) -> bool:
    """Query DNS once. On success, apply the verified transition atomically.

    Returns True iff the domain just transitioned to verified (or was
    already verified by this row). False means the TXT was not found;
    the row's `last_check_at` is updated either way.
    """
    if domain_obj.status == OrganizationDomain.Status.VERIFIED:
        domain_obj.last_check_at = timezone.now()
        domain_obj.save(update_fields=["last_check_at"])
        return True

    if not verify_domain_dns(domain_obj):
        domain_obj.last_check_at = timezone.now()
        domain_obj.save(update_fields=["last_check_at"])
        return False

    apply_dns_verification_success(domain_obj)
    return True


@transaction.atomic
def apply_dns_verification_success(domain_obj: OrganizationDomain) -> None:
    """Flip to verified and transfer ownership if another org held it.

    Wrapped in select_for_update so concurrent verifies on the same
    domain serialize: whoever commits last wins (which matches the real
    DNS state — only one org's token can be live at a time).
    """
    locked_rows = list(
        OrganizationDomain.objects.select_for_update().filter(
            domain=domain_obj.domain
        )
    )

    loser = next(
        (
            r
            for r in locked_rows
            if r.id != domain_obj.id
            and r.status == OrganizationDomain.Status.VERIFIED
        ),
        None,
    )
    if loser is not None:
        loser.status = OrganizationDomain.Status.FAILED
        loser.last_check_at = timezone.now()
        loser.save(update_fields=["status", "last_check_at"])
        _notify_ownership_transferred(loser, new_owner=domain_obj.organization)
        logger.info(
            "Domain %s ownership transferred from %s to %s",
            domain_obj.domain,
            loser.organization.slug,
            domain_obj.organization.slug,
        )

    now = timezone.now()
    domain_obj.status = OrganizationDomain.Status.VERIFIED
    domain_obj.verified_at = now
    domain_obj.last_check_at = now
    domain_obj.verification_method = OrganizationDomain.VerificationMethod.DNS_TXT
    domain_obj.save(
        update_fields=[
            "status",
            "verified_at",
            "last_check_at",
            "verification_method",
        ]
    )
    _notify_domain_verified(domain_obj)
    logger.info(
        "Domain %s verified for %s via DNS",
        domain_obj.domain,
        domain_obj.organization.slug,
    )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def _admin_emails(org: Organization) -> list[str]:
    return list(
        org.users.filter(role=User.Role.ADMIN, is_active=True).values_list(
            "email", flat=True
        )
    )


def _notify_domain_verified(domain_obj: OrganizationDomain) -> None:
    recipients = _admin_emails(domain_obj.organization)
    if not recipients:
        return
    send_branded_email(
        template="domain_verified",
        subject=f"{domain_obj.domain} is now verified on Showdesk",
        to=recipients,
        organization=domain_obj.organization,
        context={
            "domain": domain_obj.domain,
            "org_name": domain_obj.organization.name,
            "settings_url": f"{getattr(settings, 'SITE_URL', '')}/settings",
        },
        fail_silently=True,
    )


def _notify_ownership_transferred(
    losing_row: OrganizationDomain, *, new_owner: Organization
) -> None:
    recipients = _admin_emails(losing_row.organization)
    if not recipients:
        return
    send_branded_email(
        template="domain_ownership_transferred",
        subject=f"You no longer own the domain {losing_row.domain}",
        to=recipients,
        organization=losing_row.organization,
        context={
            "domain": losing_row.domain,
            "losing_org_name": losing_row.organization.name,
            "new_owner_name": new_owner.name,
            "settings_url": f"{getattr(settings, 'SITE_URL', '')}/settings",
        },
        fail_silently=True,
    )
