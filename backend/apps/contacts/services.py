"""Contact identity resolution shared by the widget and inbound channels.

Security rules:

- A *declared* email (typed by the user, set in page JavaScript, or the sender
  of an inbound mail) grants nothing: it never moves an email between contacts,
  never merges two contacts, never marks anything verified, and never writes
  on a contact that already exists.
- Only a proven email (``email_verified=True``) may attach an identified
  session to an existing email-only contact, and it only counts when it is the
  email the contact ends up with.
- An anonymized contact is never written to again.

Every value here comes from the browser or a mail header. Names are display
data and get truncated to fit their column. Identifiers (email, external id,
domain) are dropped instead when they don't fit: a truncated identifier is
somebody else's identifier.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import DomainNameValidator, validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.organizations.models import extract_email_domain, is_public_email_domain

from .attributes import clean_attributes, is_storable
from .models import Company, CompanyAttributeDef, Contact, ContactAttributeDef

_EMAIL_MAX = Contact._meta.get_field("email").max_length
_NAME_MAX = Contact._meta.get_field("name").max_length
_EXTERNAL_ID_MAX = Contact._meta.get_field("external_id").max_length
_COMPANY_NAME_MAX = Company._meta.get_field("name").max_length
_COMPANY_EXTERNAL_ID_MAX = Company._meta.get_field("external_id").max_length
_DOMAIN_MAX = Company._meta.get_field("domain").max_length

_domain_validator = DomainNameValidator()


def _clean_text(value: Any) -> str:
    """Return ``value`` as stripped, storable text, or "" if it isn't usable.

    Only strings and integers qualify. Calling ``str()`` on anything else is
    pointless at best, and raises RecursionError on a deeply nested container.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    try:
        text = str(value).strip()
    except ValueError:  # An integer beyond Python's int-to-str digit limit.
        return ""
    return text if is_storable(text) else ""


def _clean_email(value: Any) -> str:
    """Return the canonical form of an email address, or "" if it isn't valid."""
    if not isinstance(value, str):
        return ""
    email = _clean_text(value).lower()
    if not email or len(email) > _EMAIL_MAX:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email


def _clean_domain(value: Any) -> str:
    """Return the canonical form of a domain name, or "" if it isn't valid."""
    if not isinstance(value, str):
        return ""
    domain = _clean_text(value).lower().rstrip(".")
    if not domain or len(domain) > _DOMAIN_MAX:
        return ""
    try:
        _domain_validator(domain)
    except ValidationError:
        return ""
    return domain


def _clean_external_id(value: Any, max_length: int) -> str:
    text = _clean_text(value)
    return text if len(text) <= max_length else ""


def _email_taken(organization, email: str, *, contact: Contact) -> bool:
    return (
        Contact.objects.filter(organization=organization, email=email)
        .exclude(pk=contact.pk)
        .exists()
    )


def _autolink_company(contact: Contact) -> None:
    if contact.company_id or not contact.email:
        return
    domain = extract_email_domain(contact.email)
    if not domain or is_public_email_domain(domain):
        return
    company = Company.objects.filter(
        organization=contact.organization, domain=domain
    ).first()
    if company:
        contact.company = company


def _touch(contact: Contact) -> None:
    now = timezone.now()
    contact.first_seen_at = contact.first_seen_at or now
    contact.last_seen_at = now


def resolve_contact_for_email(
    organization, email: Any, *, name: Any = ""
) -> Contact | None:
    """Find or create the contact owning a *declared* email address.

    Return None when the address is unusable or belongs to an anonymized
    contact. The name only applies to a contact created here.
    """
    email = _clean_email(email)
    if not email:
        return None
    contact, _ = Contact.objects.get_or_create(
        organization=organization,
        email=email,
        defaults={"name": _clean_text(name)[:_NAME_MAX]},
    )
    if contact.is_anonymized:
        return None
    _autolink_company(contact)
    contact.save()
    return contact


def _upsert_company(organization, payload: Any) -> Company | None:
    if not isinstance(payload, dict):
        return None
    external_id = _clean_external_id(payload.get("id"), _COMPANY_EXTERNAL_ID_MAX)
    name = _clean_text(payload.get("name"))[:_COMPANY_NAME_MAX]
    if not external_id or not name:
        return None
    company, _ = Company.objects.get_or_create(
        organization=organization, external_id=external_id, defaults={"name": name}
    )
    company.name = name
    domain = _clean_domain(payload.get("domain"))
    if (
        domain
        and not Company.objects.filter(organization=organization, domain=domain)
        .exclude(pk=company.pk)
        .exists()
    ):
        company.domain = domain
    defs = CompanyAttributeDef.objects.filter(organization=organization)
    company.attributes = {
        **company.attributes,
        **clean_attributes(defs, payload.get("traits")),
    }
    company.save()
    return company


def _resolve_identified(
    session, external_id: str, email: str, email_verified: bool
) -> Contact:
    org = session.organization
    contact = Contact.objects.filter(organization=org, external_id=external_id).first()
    if contact is None and email and email_verified:
        contact = Contact.objects.filter(
            organization=org, email=email, external_id="", is_anonymized=False
        ).first()
        if contact is not None:
            contact.external_id = external_id
    if contact is None:
        contact, _ = Contact.objects.get_or_create(
            organization=org, external_id=external_id
        )
    # Fill a blank email only: a contact's email is never replaced from here,
    # even by a proven one, and never taken from the contact that owns it.
    if (
        email
        and not contact.is_anonymized
        and not contact.email
        and not _email_taken(org, email, contact=contact)
    ):
        contact.email = email
    return contact


def _detach_from_anonymized(session) -> None:
    """Stop a session from feeding new tickets to an anonymized contact."""
    if session.contact_id and session.contact.is_anonymized:
        session.contact = None
        session.save(update_fields=["contact"])


def _resolve_session_once(session, email_verified, traits, company) -> Contact | None:
    org = session.organization
    email = _clean_email(session.email)
    name = _clean_text(session.name)[:_NAME_MAX]
    identified = bool(session.external_user_id)

    if identified:
        external_id = _clean_external_id(session.external_user_id, _EXTERNAL_ID_MAX)
        if external_id != session.external_user_id or not external_id:
            # Not something we'd store as is, so it can't be looked up either.
            # Don't fall back on the email: this session claimed an identity.
            contact = None
        else:
            contact = _resolve_identified(session, external_id, email, email_verified)
    elif email:
        contact, _ = Contact.objects.get_or_create(
            organization=org, email=email, defaults={"name": name}
        )
    else:
        contact = None

    if contact is None or contact.is_anonymized:
        _detach_from_anonymized(session)
        return None

    # The email is proven only if it's the one this contact holds: a contact
    # that kept another email, or lost this one to its owner, proves nothing.
    email_proven = bool(email_verified and email and contact.email == email)

    # What the browser says about a contact only counts once it proved who it
    # is. A declared email must not let anyone edit the contact owning it.
    if identified or email_proven:
        if name and not contact.name:
            contact.name = name
        defs = ContactAttributeDef.objects.filter(organization=org)
        contact.attributes = {**contact.attributes, **clean_attributes(defs, traits)}
    if identified:
        contact.company = _upsert_company(org, company) or contact.company
    if email_proven:
        contact.email_verified_at = contact.email_verified_at or timezone.now()
    _autolink_company(contact)
    _touch(contact)
    contact.save()

    session.contact = contact
    update_fields = ["contact"]
    if email_proven and session.email_verified_at is None:
        session.email_verified_at = timezone.now()
        update_fields.append("email_verified_at")
    session.save(update_fields=update_fields)
    return contact


def resolve_contact_for_widget_session(
    session,
    *,
    email_verified: bool = False,
    traits: Any = None,
    company: Any = None,
) -> Contact | None:
    """Find or create the contact behind a widget session and link them.

    ``session.external_user_id`` must only be set by callers after a
    successful HMAC check. ``email_verified`` must only be True when the
    host app signed the email (``email_hash``) or the user proved ownership.

    Return None when the session has no usable identity or points at an
    anonymized contact, in which case nothing is written on any contact.
    """
    try:
        with transaction.atomic():
            return _resolve_session_once(session, email_verified, traits, company)
    except IntegrityError:
        # A concurrent request claimed the email, external id or domain between
        # our check and our save. The second pass sees it and leaves it alone.
        with transaction.atomic():
            return _resolve_session_once(session, email_verified, traits, company)
