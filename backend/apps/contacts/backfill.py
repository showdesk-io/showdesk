"""Back-fill of contacts from existing widget sessions and tickets.

Plain function called from a migration, so it takes the app registry. Historical
models have no custom ``save()``, so emails are normalized here. It keeps its own
copy of the rules it needs: a migration must keep doing what it did when it was
written, whatever ``services.py`` becomes. ``manage.py backfill_contacts`` runs it
again after a deploy, for the rows that pods still running the old code wrote.

The rules follow the identity service, for data nothing was proven about:

- A session's external id was signed when the session was created. A ticket's wasn't:
  ``widget_submit`` takes any value. So a ticket's external id only counts if a session
  of its organization holds the same one, and a contact never takes its name or
  declared email from a ticket whose id doesn't. Such a ticket is treated as if it had
  no id: it goes by its email, or else stays unlinked.
- An external id gets a contact of its own, whose email goes to ``declared_email``.
  Nothing is marked verified, and ``email`` stays blank.
- Otherwise a usable email gets an email-only contact, shared by everyone giving it.
- A ticket with no session of its organization and no identity of its own goes by its
  requester, when that's an end-user account not belonging to another organization.
  Its email counts as declared, like any other here, and an agent or admin never
  becomes a contact. The account names a new contact only if it holds the same email.
- A session decides for its tickets, so they end on the same contact whatever their
  own values are. An anonymous session without a usable email takes the most recent
  usable email of its tickets, and stores it: the service identifies it by its own
  email on every resume, and would unlink a contact it can't find that way. It never
  takes an external id from them, since only a valid hash gives a session one.
- An external id with padding or a reserved prefix is no identity, and the session
  doesn't fall back on its email: it claimed an identity. The service does the same.
- An anonymized contact is neither linked nor written, and neither are its rows.

It only ever fills in. A linked row stays as it is, even when a concurrent request
linked it after we read it, and a contact it didn't create is only linked to. So
it's idempotent, and it never fails on a unique conflict.

Linking bumps no ``updated_at`` or ``last_seen_at`` on the rows: nothing happened on
them, and list orders must not change. ``updated_at`` of a new contact is the time of
the migration, as its ``created_at``. Its seen dates come from the rows linked to it.

The cost has to stay linear in the rows. The values of new contacts come from one
ordered read per batch, not from a subquery per contact: picking a contact's latest
row walks the ``created_at`` index past everyone else's rows when the planner expects
it to find one soon. Statistics are refreshed once ``contact_id`` stops being all
NULL, or the planner picks nested loops for the rows it expects none of.
"""

from __future__ import annotations

from itertools import batched

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import (
    Case,
    CharField,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    UUIDField,
    Value,
    When,
)

BATCH_SIZE = 1000

_EMAIL_MAX = 254
_NAME_MAX = 255

# ``organizations.models.User.Role.END_USER``, as of this migration.
_END_USER = "end_user"

# ``organizations.models.RESERVED_EXTERNAL_ID_PREFIXES``, as of this migration.
_RESERVED_PREFIXES = ("email:", "company\n")

# A contact is looked up on one field: ("external_id" or "email", value).
Identity = tuple[str, str]


def clean_email(value: str) -> str:
    """Return the canonical form of a legacy email, or "" if it isn't usable."""
    email = (value or "").strip().lower()
    if not email or len(email) > _EMAIL_MAX:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email


def _usable_external_id(value: str) -> bool:
    return bool(value and value == value.strip()) and not value.startswith(
        _RESERVED_PREFIXES
    )


def _identity(external_id: str, email: str) -> Identity | None:
    if external_id:
        return (
            ("external_id", external_id) if _usable_external_id(external_id) else None
        )
    email = clean_email(email)
    return ("email", email) if email else None


def _vouched_external_ids(WidgetSession) -> set[tuple]:
    """Return the ``(org id, external id)`` that a session was created with."""
    rows = (
        WidgetSession.objects.exclude(external_user_id="")
        .order_by()
        .values_list("organization_id", "external_user_id")
    )
    return {
        (org_id, external_id)
        for org_id, external_id in rows.iterator(chunk_size=BATCH_SIZE)
        if _usable_external_id(external_id)
    }


def _ticket_identity(
    org_id, external_id: str, email: str, vouched: set
) -> Identity | None:
    if (org_id, external_id) in vouched:
        return ("external_id", external_id)
    return _identity("", email)


def _is_customer(org_id, role: str | None, account_org_id) -> bool:
    return role == _END_USER and account_org_id in (None, org_id)


def _lookup(Contact, keys) -> dict[tuple, tuple]:
    """Return ``(id, is_anonymized)`` of the contacts matching ``(org id, *identity)``."""
    found = {}
    for field in ("external_id", "email"):
        values = {value for _, key_field, value in keys if key_field == field}
        if not values:
            continue
        # The filter is wider than the keys: an org and a value of two different
        # keys also match. Only exact keys get out of here.
        rows = Contact.objects.filter(
            organization_id__in={org_id for org_id, _, _ in keys},
            **{f"{field}__in": values},
        ).values_list("organization_id", field, "pk", "is_anonymized")
        for org_id, value, pk, anonymized in rows:
            key = (org_id, field, value)
            if key in keys:
                found[key] = (pk, anonymized)
    return found


def _contact_ids(Contact, declared_emails: dict[tuple, str], created: set) -> dict:
    """Return the id of the contact of each key, creating those that don't exist.

    ``declared_emails`` maps ``(org id, *identity)`` to the email a contact created
    for it declares. A key whose contact is anonymized isn't in the result. The ids
    of the contacts really created here are added to ``created``.
    """
    found = _lookup(Contact, declared_emails.keys())
    new = {
        (org_id, field, value): Contact(
            organization_id=org_id,
            declared_email=declared_emails[(org_id, field, value)],
            **{field: value},
        )
        for org_id, field, value in declared_emails.keys() - found.keys()
    }
    if new:
        # A concurrent insert makes ours a no-op, and the second read finds its row.
        Contact.objects.bulk_create(new.values(), ignore_conflicts=True)
        found |= _lookup(Contact, new.keys())
        created |= {
            contact.pk
            for key, contact in new.items()
            if key in found and found[key][0] == contact.pk
        }
    return {key: pk for key, (pk, anonymized) in found.items() if not anonymized}


def _case(values: dict, output_field) -> Case:
    return Case(
        *[When(pk=pk, then=Value(v)) for pk, v in values.items()],
        output_field=output_field,
    )


def _set_contacts(queryset: QuerySet, contacts: dict) -> None:
    """Link rows (by pk) in one statement, on those of ``queryset`` only."""
    if contacts:
        queryset.filter(pk__in=contacts).update(contact_id=_case(contacts, UUIDField()))


def _contacts_of_batch(
    Contact, rows: tuple, identities: dict, created: set, *, declares: bool
) -> dict:
    """Return the contact of ``rows`` (pk, org id, external id, email, ...) by pk.

    With ``declares``, a new identified contact declares the email of its row.
    Sessions do, being unique per external id. Tickets are left to
    ``_fill_new_contacts``, as the latest usable one of several has to win.
    """
    keys = {}
    declared_emails = {}
    for pk, org_id, _, email, *_ in rows:
        identity = identities.get(pk)
        if identity is None:
            continue
        keys[pk] = (org_id, *identity)
        identified = identity[0] == "external_id"
        declared_emails[keys[pk]] = (
            clean_email(email) if declares and identified else ""
        )
    contact_ids = _contact_ids(Contact, declared_emails, created)
    return {pk: contact_ids[key] for pk, key in keys.items() if key in contact_ids}


def _emails_from_tickets(Ticket, session_ids: list) -> dict:
    """Return the latest usable email of each session's own tickets, if any."""
    rows = (
        Ticket.objects.filter(
            widget_session_id__in=session_ids,
            organization_id=F("widget_session__organization_id"),
        )
        .exclude(requester_email="")
        .order_by("widget_session_id", "-created_at")
        .values_list("widget_session_id", "requester_email")
    )
    emails: dict = {}
    for session_id, email in rows.iterator(chunk_size=BATCH_SIZE):
        if session_id not in emails and (email := clean_email(email)):
            emails[session_id] = email
    return emails


def _link_sessions(Contact, Ticket, WidgetSession, created: set) -> None:
    rows = (
        WidgetSession.objects.filter(contact__isnull=True)
        .order_by()
        .values_list("pk", "organization_id", "external_user_id", "email")
    )
    unlinked = WidgetSession.objects.filter(contact__isnull=True)
    for batch in batched(rows.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        identities = {row[0]: _identity(row[2], row[3]) for row in batch}
        # A session with an external id it can't have made a claim, unlike one with
        # nothing: its tickets don't get to say who it is.
        nobody = [row[0] for row in batch if not row[2] and identities[row[0]] is None]
        emails = _emails_from_tickets(Ticket, nobody) if nobody else {}
        identities |= {pk: ("email", email) for pk, email in emails.items()}
        contacts = _contacts_of_batch(
            Contact, batch, identities, created, declares=True
        )
        given = {pk: emails[pk] for pk in contacts.keys() & emails.keys()}
        if given:
            # One statement with the link: a session it doesn't link keeps its email.
            # A proof it held was about its previous email.
            unlinked.filter(pk__in=given).update(
                contact_id=_case({pk: contacts.pop(pk) for pk in given}, UUIDField()),
                email=_case(given, CharField()),
                email_verified_at=None,
            )
        _set_contacts(unlinked, contacts)


def _link_tickets_to_their_session(Ticket, WidgetSession) -> None:
    Ticket.objects.filter(
        contact__isnull=True,
        widget_session__contact__isnull=False,
        widget_session__organization_id=F("organization_id"),
        widget_session__contact__organization_id=F("organization_id"),
        widget_session__contact__is_anonymized=False,
    ).update(
        contact_id=Subquery(
            WidgetSession.objects.filter(pk=OuterRef("widget_session_id")).values(
                "contact_id"
            )[:1]
        )
    )


def _link_tickets_without_session(Contact, Ticket, created: set, vouched: set) -> None:
    """Link the tickets that no session of their organization decides for.

    A ticket whose session ended without a contact stays without one if that session
    is anonymized or made a claim we can't honor. Only an anonymous session without a
    usable email leaves its tickets to their own identity.
    """
    rows = (
        Ticket.objects.filter(contact__isnull=True)
        .filter(
            Q(widget_session__isnull=True)
            | ~Q(widget_session__organization_id=F("organization_id"))
            | Q(
                widget_session__contact__isnull=True,
                widget_session__external_user_id="",
            )
        )
        .order_by()
        .values_list(
            "pk",
            "organization_id",
            "external_user_id",
            "requester_email",
            "widget_session__organization_id",
            "widget_session__email",
            "requester__email",
            "requester__role",
            "requester__organization_id",
        )
    )
    unlinked = Ticket.objects.filter(contact__isnull=True)
    for batch in batched(rows.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        identities = {}
        for (
            pk,
            org_id,
            external_id,
            email,
            session_org_id,
            session_email,
            account_email,
            role,
            account_org_id,
        ) in batch:
            has_session = session_org_id == org_id
            # Its session has a usable email and no contact: that one is anonymized.
            if has_session and clean_email(session_email):
                continue
            identity = _ticket_identity(org_id, external_id, email, vouched)
            if (
                identity is None
                and not has_session
                and _is_customer(org_id, role, account_org_id)
            ):
                identity = _identity("", account_email)
            identities[pk] = identity
        _set_contacts(
            unlinked,
            _contacts_of_batch(Contact, batch, identities, created, declares=False),
        )


def _fill_new_contacts(
    Contact, Ticket, WidgetSession, contact_ids: tuple, vouched: set
) -> None:
    """Set the name, declared email and seen dates of new contacts, in one pass.

    Rows come latest first: the first usable value of a contact is the one it keeps.
    A session's name wins over a ticket's, and a session's email was declared already.
    A ticket without a name gives its requester's, if that account holds the contact's
    email: an account says nothing of another address, or of an identified contact.
    """
    fields = ("name", "declared_email", "first_seen_at", "last_seen_at")
    contacts = Contact.objects.filter(pk__in=contact_ids).only(
        "email", "external_id", *fields
    )
    contacts = {contact.pk: contact for contact in contacts}

    def seen(contact, first, last):
        contact.first_seen_at = min(first, contact.first_seen_at or first)
        contact.last_seen_at = max(last, contact.last_seen_at or last)

    sessions = (
        WidgetSession.objects.filter(contact_id__in=contact_ids)
        .order_by("contact_id", "-last_seen_at")
        .values_list("contact_id", "created_at", "last_seen_at", "name")
    )
    for contact_id, created_at, last_seen_at, name in sessions.iterator(
        chunk_size=BATCH_SIZE
    ):
        contact = contacts[contact_id]
        seen(contact, created_at, last_seen_at)
        contact.name = contact.name or name.strip()

    tickets = (
        Ticket.objects.filter(contact_id__in=contact_ids)
        .order_by("contact_id", "-created_at")
        .values_list(
            "contact_id",
            "created_at",
            "organization_id",
            "external_user_id",
            "requester_name",
            "requester_email",
            "requester__email",
            "requester__role",
            "requester__organization_id",
            "requester__first_name",
            "requester__last_name",
        )
    )
    for (
        contact_id,
        created_at,
        org_id,
        external_id,
        name,
        email,
        account_email,
        role,
        account_org_id,
        first_name,
        last_name,
    ) in tickets.iterator(chunk_size=BATCH_SIZE):
        contact = contacts[contact_id]
        seen(contact, created_at, created_at)
        if not (external_id and (org_id, external_id) not in vouched):
            contact.name = contact.name or name.strip()
            if contact.external_id and not contact.declared_email:
                contact.declared_email = clean_email(email)
        if (
            not contact.name
            and contact.email
            and _is_customer(org_id, role, account_org_id)
            and clean_email(account_email) == contact.email
        ):
            contact.name = f"{first_name} {last_name}".strip()[:_NAME_MAX]

    Contact.objects.bulk_update(contacts.values(), fields)


def _analyze(schema_editor, *tables: str) -> None:
    """Refresh the planner's statistics. It's transactional, and sees our own writes."""
    connection = (
        schema_editor.connection if schema_editor else connections[DEFAULT_DB_ALIAS]
    )
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"ANALYZE {connection.ops.quote_name(table)}")


def backfill(apps, schema_editor) -> int:
    """Create the contacts behind existing sessions and tickets, and link them all.

    Return how many contacts were created. The caller provides the transaction: a
    migration is one, and the command opens one.
    """
    Contact = apps.get_model("contacts", "Contact")
    Ticket = apps.get_model("tickets", "Ticket")
    WidgetSession = apps.get_model("tickets", "WidgetSession")

    # Small next to the rows the batches keep out of memory: ids, and one pair per
    # identified session.
    created: set = set()
    vouched = _vouched_external_ids(WidgetSession)

    _link_sessions(Contact, Ticket, WidgetSession, created)
    _analyze(schema_editor, WidgetSession._meta.db_table)
    _link_tickets_to_their_session(Ticket, WidgetSession)
    _link_tickets_without_session(Contact, Ticket, created, vouched)
    _analyze(schema_editor, Ticket._meta.db_table)

    for contact_ids in batched(created, BATCH_SIZE):
        _fill_new_contacts(Contact, Ticket, WidgetSession, contact_ids, vouched)
    return len(created)
