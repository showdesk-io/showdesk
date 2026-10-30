"""Contact identity resolution shared by the widget and inbound channels.

Threat model: a widget session's email, name, traits and company come from page
JavaScript, so a legitimately identified user can forge them. Only ``user_hash``
(the external id), ``email_hash`` and ``company_hash`` (a company's id, name and
domain, not its traits) are signed by the host app.

Email rules:

- ``Contact.email`` never receives an unproven email on an identified contact.
  An identified session's unproven email goes to ``declared_email`` on its own
  contact, where the latest value wins.
- A proven email (``email_verified=True``) fills the blank ``email`` of the
  session's contact unless another contact owns it, or attaches the session to
  an email-only contact when the external id is new. It is never moved between
  contacts, and it only counts when it is the email the contact ends up with.
- Anonymous sessions and inbound mail still use email-only contacts, first come,
  unverified: that grants no access, and a proof later attaches to the contact.
- An anonymous session's unproven email writes nothing on a contact that already
  exists: no seen dates, no ``updated_at``, no company. It only links the session.
  An inbound mail writes one thing at most: a missing company, from the domain of
  the email the contact already holds (see ``resolve_contact_for_email``).
- Two contacts are never merged.

Company rules, without a valid ``company_hash``: an existing company is never
modified, only linked, and a contact that already has a company is never moved.
A new company takes the name and traits, and the domain only if it's the domain
of the email proven by this session. With ``company_verified=True``, the name and
domain are upserted and the contact may be moved, but traits only apply to a company
this payload creates. Nobody takes another company's domain.
Auto-linking on the email domain happens on an identified contact only from a
proven email, and on an anonymous session only when it creates the contact.

An anonymized contact is never written to again. Every write happens under a row
lock taken by the lookup that found the contact, so its state is current: an
anonymization committed before the lock is seen, and one that comes after has to
wait for this transaction. ``anonymize_contact`` must lock the same row.

Every value here comes from the browser or a mail header. Names are display
data and get truncated to fit their column. Identifiers (email, external id,
domain) are dropped instead when they don't fit: a truncated identifier is
somebody else's identifier.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import DomainNameValidator, validate_email
from django.db import DatabaseError, IntegrityError, models, transaction
from django.utils import timezone

from apps.organizations.models import (
    RESERVED_EXTERNAL_ID_PREFIXES,
    User,
    extract_email_domain,
    is_public_email_domain,
)

from .attributes import clean_attributes, is_storable
from .models import Company, CompanyAttributeDef, Contact, ContactAttributeDef

_EMAIL_MAX = Contact._meta.get_field("email").max_length
_NAME_MAX = Contact._meta.get_field("name").max_length
_EXTERNAL_ID_MAX = Contact._meta.get_field("external_id").max_length
_COMPANY_NAME_MAX = Company._meta.get_field("name").max_length
_COMPANY_EXTERNAL_ID_MAX = Company._meta.get_field("external_id").max_length

_domain_validator = DomainNameValidator()

# A visit isn't an edit of the record: these alone don't bump ``updated_at``.
_SEEN_FIELDS = {"first_seen_at", "last_seen_at"}


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
    domain = _clean_text(value).lower().rstrip(".")
    if not domain:
        return ""
    try:
        _domain_validator(domain)
    except ValidationError:
        return ""
    return domain


def _clean_external_id(value: Any, max_length: int) -> str:
    text = _clean_text(value)
    return text if len(text) <= max_length else ""


def _locked(model: type[models.Model], **lookup) -> Any:
    """Return the matching row, locked for this transaction, or None.

    Under READ COMMITTED a lookup that had to wait for the lock checks its
    filters again on the committed row, so what it returns is current. NO KEY
    lets inserts referencing the row (a new ticket's contact) go through.
    """
    return model.objects.select_for_update(no_key=True).filter(**lookup).first()


def _get_or_create_locked(
    model: type[models.Model], defaults: dict[str, Any], **lookup
) -> tuple[Any, bool]:
    """``get_or_create`` returning a row that's locked unless we just created it.

    The row is None if a concurrent transaction deleted it in the meantime.
    """
    row = _locked(model, **lookup)
    if row is not None:
        return row, False
    row, created = model.objects.get_or_create(**lookup, defaults=defaults)
    return (row, True) if created else (_locked(model, pk=row.pk), False)


def _set(instance: models.Model, changed: set[str], **values: Any) -> None:
    """Assign ``values``, recording in ``changed`` the fields that really differ."""
    for field, value in values.items():
        if getattr(instance, field) != value:
            setattr(instance, field, value)
            changed.add(field)


def _save_changes(instance: models.Model, changed: set[str]) -> None:
    """Write only the fields in ``changed``, and nothing at all if it's empty."""
    if not changed:
        return
    fields = set(changed)
    if fields - _SEEN_FIELDS:
        fields.add("updated_at")
    instance.save(update_fields=fields)


def _merged_attributes(stored: Any, cleaned: dict[str, Any]) -> Any:
    """Return ``stored`` updated with ``cleaned``. Nothing cleaned changes nothing."""
    if not cleaned:
        return stored
    return {**(stored if isinstance(stored, dict) else {}), **cleaned}


def _email_taken(organization, email: str) -> bool:
    return Contact.objects.filter(organization=organization, email=email).exists()


def _domain_taken(organization, domain: str) -> bool:
    return Company.objects.filter(organization=organization, domain=domain).exists()


def _autolink_company(contact: Contact, changed: set[str]) -> None:
    if contact.company_id or not contact.email:
        return
    domain = extract_email_domain(contact.email)
    if not domain or is_public_email_domain(domain):
        return
    company = Company.objects.filter(
        organization_id=contact.organization_id, domain=domain
    ).first()
    if company:
        contact.company = company
        changed.add("company")


def _touch(contact: Contact, changed: set[str]) -> None:
    now = timezone.now()
    _set(contact, changed, first_seen_at=contact.first_seen_at or now, last_seen_at=now)


def resolve_contact_for_email(
    organization, email: Any, *, name: Any = ""
) -> Contact | None:
    """Find or create the contact owning a *declared* email address.

    Return None when the address is unusable or belongs to an anonymized
    contact. The name only applies to a contact created here. The only write on
    an existing contact is a missing company, from the domain of the email it
    already holds, and not on an identified contact until that email is proven.
    An address merely declared by an identified session sits in
    ``declared_email``, so it never leads here to that session's contact.
    """
    email = _clean_email(email)
    if not email:
        return None
    with transaction.atomic():
        contact, _ = _get_or_create_locked(
            Contact,
            {"name": _clean_text(name)[:_NAME_MAX]},
            organization=organization,
            email=email,
        )
        if contact is None or contact.is_anonymized:
            return None
        if not contact.external_id or contact.email_verified_at:
            changed: set[str] = set()
            _autolink_company(contact, changed)
            _save_changes(contact, changed)
    return contact


def resolve_contact_for_ticket(ticket) -> Contact | None:
    """Find or create the contact of a ticket filed through the API.

    It goes by the ticket's email, or else its requester's when that's an end-user
    account not belonging to another organization. Either way it's only declared. An
    agent or admin of the organization never becomes a contact, by account or address.
    """
    organization_id = ticket.organization_id
    account = ticket.requester
    if account is not None and (
        account.role != User.Role.END_USER
        or account.organization_id not in (None, organization_id)
    ):
        account = None
    email = _clean_email(ticket.requester_email)
    account_email = _clean_email(account.email) if account else ""
    email = email or account_email
    if (
        not email
        or User.objects.filter(organization_id=organization_id, email__iexact=email)
        .exclude(role=User.Role.END_USER)
        .exists()
    ):
        return None
    name = _clean_text(ticket.requester_name)
    if not name and email == account_email:
        name = account.get_full_name()
    return resolve_contact_for_email(ticket.organization, email, name=name)


def _upsert_signed_company(
    organization, external_id: str, name: str, domain: str, traits: dict[str, Any]
) -> Company | None:
    """Apply a payload signed by the host app, except for another company's domain.

    The hash doesn't cover ``traits``, so they only apply to a company created here.
    """
    company, _ = _get_or_create_locked(
        Company,
        {"name": name, "attributes": traits},
        organization=organization,
        external_id=external_id,
    )
    if company is None:
        return None
    changed: set[str] = set()
    _set(company, changed, name=name)
    if domain and domain != company.domain and not _domain_taken(organization, domain):
        _set(company, changed, domain=domain)
    _save_changes(company, changed)
    return company


def _get_or_create_unsigned_company(
    organization,
    external_id: str,
    name: str,
    domain: str,
    traits: dict[str, Any],
    proven_email: str,
) -> Company:
    """Link to an existing company untouched, or create one from the payload."""
    company = Company.objects.filter(
        organization=organization, external_id=external_id
    ).first()
    if company is not None:
        return company
    # The proven mailbox is the only evidence that this user is at that domain,
    # and a shared webmail domain is no evidence of being at any company.
    if (
        not domain
        or domain != extract_email_domain(proven_email)
        or is_public_email_domain(domain)
        or _domain_taken(organization, domain)
    ):
        domain = ""
    company, _ = Company.objects.get_or_create(
        organization=organization,
        external_id=external_id,
        defaults={"name": name, "domain": domain, "attributes": traits},
    )
    return company


def _resolve_company(
    organization, payload: Any, *, verified: bool, proven_email: str
) -> Company | None:
    if not isinstance(payload, dict):
        return None
    external_id = _clean_external_id(payload.get("id"), _COMPANY_EXTERNAL_ID_MAX)
    name = _clean_text(payload.get("name"))[:_COMPANY_NAME_MAX]
    if not external_id or not name:
        return None
    domain = _clean_domain(payload.get("domain"))
    defs = CompanyAttributeDef.objects.filter(organization=organization)
    traits = clean_attributes(defs, payload.get("traits"))
    if verified:
        return _upsert_signed_company(organization, external_id, name, domain, traits)
    return _get_or_create_unsigned_company(
        organization, external_id, name, domain, traits, proven_email
    )


def _find_identified(
    org, external_id: str, proven_email: str, changed: set[str]
) -> Contact | None:
    """Return the locked contact of an external id, attaching or creating it."""
    contact = _locked(Contact, organization=org, external_id=external_id)
    if contact is None and proven_email:
        contact = _locked(
            Contact,
            organization=org,
            email=proven_email,
            external_id="",
            is_anonymized=False,
        )
        if contact is not None:
            _set(contact, changed, external_id=external_id)
    if contact is None:
        contact, _ = _get_or_create_locked(
            Contact, {}, organization=org, external_id=external_id
        )
    return contact


def _record_identified_email(
    org, contact: Contact, email: str, email_verified: bool, changed: set[str]
) -> None:
    """Store what an identified session says its email is, on its own contact."""
    if not email_verified:
        # The email it already holds is no separate claim for agents to review.
        _set(contact, changed, declared_email="" if email == contact.email else email)
    elif not contact.email and not _email_taken(org, email):
        # A verification date left by a previous email is about that email.
        _set(contact, changed, email=email, email_verified_at=None)


def _resolve_session_once(
    session, email_verified: bool, traits: Any, company: Any, company_verified: bool
) -> Contact | None:
    org = session.organization
    email = _clean_email(session.email)
    name = _clean_text(session.name)[:_NAME_MAX]
    identified = bool(session.external_user_id)
    created = False
    changed: set[str] = set()

    if identified:
        external_id = _clean_external_id(session.external_user_id, _EXTERNAL_ID_MAX)
        if (
            not external_id
            or external_id != session.external_user_id
            or external_id.startswith(RESERVED_EXTERNAL_ID_PREFIXES)
        ):
            # Not something we'd store as is, so it can't be looked up either, or a
            # hash from before those prefixes were reserved: it may sign something
            # else. Don't fall back on the email: this session claimed an identity.
            contact = None
        else:
            proven_email = email if email_verified else ""
            contact = _find_identified(org, external_id, proven_email, changed)
    elif email:
        contact, created = _get_or_create_locked(
            Contact, {"name": name}, organization=org, email=email
        )
    else:
        contact = None

    if contact is None or contact.is_anonymized:
        if session.contact_id:
            session.contact = None
            session.save(update_fields=["contact", "updated_at"])
        return None

    if identified and email:
        _record_identified_email(org, contact, email, email_verified, changed)

    # The email is proven only if it's the one this contact holds: a contact
    # that kept another email, or lost this one to its owner, proves nothing.
    email_proven = bool(email_verified and email and contact.email == email)
    if email_proven:
        _set(
            contact,
            changed,
            email_verified_at=contact.email_verified_at or timezone.now(),
        )
        if contact.declared_email == email:
            _set(contact, changed, declared_email="")

    # What the browser says about a contact only counts once it proved who it
    # is. A declared email must not let anyone edit the contact owning it.
    trusted = identified or email_proven
    if trusted:
        if name and not contact.name:
            _set(contact, changed, name=name)
        defs = ContactAttributeDef.objects.filter(organization=org)
        _set(
            contact,
            changed,
            attributes=_merged_attributes(
                contact.attributes, clean_attributes(defs, traits)
            ),
        )
    if identified and (company_verified or not contact.company_id):
        linked = _resolve_company(
            org,
            company,
            verified=company_verified,
            proven_email=email if email_proven else "",
        )
        if linked is not None and linked.pk != contact.company_id:
            contact.company = linked
            changed.add("company")
    if created or (identified and contact.email_verified_at):
        _autolink_company(contact, changed)
    if trusted or created:
        _touch(contact, changed)
    _save_changes(contact, changed)

    session_changed: set[str] = set()
    if session.contact_id != contact.pk:
        session.contact = contact
        session_changed.add("contact")
    if email_proven and session.email_verified_at is None:
        session.email_verified_at = timezone.now()
        session_changed.add("email_verified_at")
    _save_changes(session, session_changed)
    return contact


def _resolve_session_atomically(
    session, email_verified: bool, traits: Any, company: Any, company_verified: bool
) -> Contact | None:
    """Run one pass. If it fails, forget in memory the writes it rolled back.

    The session object outlives the pass, and the next one only writes what
    differs from it, so it has to see those writes as still to be made.
    """
    contact_id = session.contact_id
    email_verified_at = session.email_verified_at
    try:
        with transaction.atomic():
            return _resolve_session_once(
                session, email_verified, traits, company, company_verified
            )
    except DatabaseError:
        session.contact_id = contact_id
        session.email_verified_at = email_verified_at
        raise


def resolve_contact_for_widget_session(
    session,
    *,
    email_verified: bool = False,
    traits: Any = None,
    company: Any = None,
    company_verified: bool = False,
) -> Contact | None:
    """Find or create the contact behind a widget session and link them.

    ``session.external_user_id`` must only be set by callers after a
    successful HMAC check. ``email_verified`` must only be True when the
    host app signed the email (``email_hash``) or the user proved ownership.
    ``company_verified`` must only be True when the host app signed the company's
    id, name and domain (``company_hash``); it has no effect on a session that
    isn't identified.

    Return None when the session has no usable identity or points at an
    anonymized contact, in which case nothing is written on any contact and a
    contact previously linked to the session is unlinked.

    The retry assumes READ COMMITTED: a concurrent request claimed the email,
    external id or domain between our check and our save, and the second pass
    has to see that commit to leave the value alone. A snapshot taken at the
    start of an enclosing REPEATABLE READ transaction would hide it.
    """
    args = (session, email_verified, traits, company, company_verified)
    try:
        return _resolve_session_atomically(*args)
    except IntegrityError:
        return _resolve_session_atomically(*args)


def delete_contact_if_left_empty(contact_id) -> bool:
    """Delete an email-only contact that a login emptied, and tell if it did.

    Only a contact with nothing of its own: no ticket, session or note, and nothing
    an agent or a proven session entered, which no one could get back. Under the same
    row lock as a resolution, so one that's linking a session either goes first and
    keeps the contact, or finds it gone and creates another.

    The caller must have committed its move: the identity lock order is contact, then
    sessions, and a move holds its session's row.
    """
    with transaction.atomic():
        contact = (
            Contact.objects.select_for_update()
            .filter(
                pk=contact_id,
                external_id="",
                is_anonymized=False,
                is_unsubscribed=False,
                phone="",
                avatar_url="",
                job_title="",
                locale="",
                timezone="",
                attributes={},
            )
            .first()
        )
        if (
            contact is None
            or contact.tickets.exists()
            or contact.sessions.exists()
            or contact.notes.exists()
        ):
            return False
        contact.delete()
        return True
