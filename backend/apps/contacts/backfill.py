"""One-off back-fill of contacts from existing widget sessions and tickets.

Plain function called from a migration, so it takes the app registry. Historical
models have no custom ``save()``, so emails are normalized here. It keeps its own
copy of the rules it needs: a migration must keep doing what it did when it was
written, whatever ``services.py`` becomes.

The rules follow the identity service, for data nothing was proven about:

- An external id gets a contact of its own, whose email goes to ``declared_email``.
  Nothing is marked verified, and ``email`` stays blank.
- Otherwise a usable email gets an email-only contact, shared by everyone giving it.
- A session decides for its tickets, so they end on the same contact whatever their
  own values are. A session that identifies nobody takes its identity from its
  tickets: an external id, or else the most recent usable email.
- An external id with padding is no identity, and the row doesn't fall back on its
  email: it claimed an identity. The service treats it the same way.
- An anonymized contact is neither linked nor written, and neither are its rows.

It only ever fills in. A linked row stays as it is, even when a concurrent request
linked it after we read it, and a contact it didn't create is only linked to. So
it's idempotent, and it never fails on a unique conflict.

Linking bumps no ``updated_at`` or ``last_seen_at`` on the rows: nothing happened on
them, and list orders must not change. ``updated_at`` of a new contact is the time of
the migration, as its ``created_at``. Its seen dates come from the rows linked to it.
"""

from __future__ import annotations

from itertools import batched, groupby
from operator import itemgetter

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import (
    Case,
    CharField,
    F,
    Max,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    UUIDField,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest, Least, Trim

BATCH_SIZE = 1000

_EMAIL_MAX = 254

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


def _identity(external_id: str, email: str) -> Identity | None:
    if external_id:
        return (
            ("external_id", external_id) if external_id == external_id.strip() else None
        )
    email = clean_email(email)
    return ("email", email) if email else None


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


def _set_values(queryset: QuerySet, field: str, values: dict, output_field) -> None:
    """Write ``values`` (by pk) in one statement, on the rows of ``queryset`` only."""
    if values:
        queryset.filter(pk__in=values).update(
            **{
                field: Case(
                    *[When(pk=pk, then=Value(v)) for pk, v in values.items()],
                    output_field=output_field,
                )
            }
        )


def _link_batch(
    Contact, Model, rows: tuple, identities: dict, created: set, *, declares: bool
) -> None:
    """Link ``rows`` (pk, org id, external id, email) to their identity's contact.

    With ``declares``, a new identified contact declares the email of its row.
    Sessions do, being unique per external id. Tickets are left to
    ``_declare_ticket_emails``, as the latest usable one of several has to win.
    """
    keys = {}
    declared_emails = {}
    for pk, org_id, _, email in rows:
        identity = identities.get(pk)
        if identity is None:
            continue
        keys[pk] = (org_id, *identity)
        identified = identity[0] == "external_id"
        declared_emails[keys[pk]] = (
            clean_email(email) if declares and identified else ""
        )
    contact_ids = _contact_ids(Contact, declared_emails, created)
    _set_values(
        Model.objects.filter(contact__isnull=True),
        "contact_id",
        {pk: contact_ids[key] for pk, key in keys.items() if key in contact_ids},
        UUIDField(),
    )


def _identities_from_tickets(Ticket, session_ids: list) -> dict:
    """Return the identity each session gets from its own tickets, if any."""
    rows = (
        Ticket.objects.filter(
            widget_session_id__in=session_ids,
            organization_id=F("widget_session__organization_id"),
        )
        .order_by("-created_at")
        .values_list("widget_session_id", "external_user_id", "requester_email")
    )
    identities: dict = {}
    for session_id, external_id, email in rows.iterator(chunk_size=BATCH_SIZE):
        identity = _identity(external_id, email)
        if identity is None:
            continue
        current = identities.get(session_id)
        if current is None or (current[0], identity[0]) == ("email", "external_id"):
            identities[session_id] = identity
    return identities


def _link_sessions(Contact, Ticket, WidgetSession, created: set) -> None:
    rows = (
        WidgetSession.objects.filter(contact__isnull=True)
        .order_by()
        .values_list("pk", "organization_id", "external_user_id", "email")
    )
    for batch in batched(rows.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        identities = {row[0]: _identity(row[2], row[3]) for row in batch}
        # A session with an external id it can't have made a claim, unlike one with
        # nothing: its tickets don't get to say who it is.
        nobody = [row[0] for row in batch if not row[2] and identities[row[0]] is None]
        if nobody:
            identities |= _identities_from_tickets(Ticket, nobody)
        _link_batch(Contact, WidgetSession, batch, identities, created, declares=True)


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


def _link_tickets_without_session(Contact, Ticket, created: set) -> None:
    """Link the tickets that don't depend on a session of their organization.

    A ticket whose session ended without a contact stays without one: that session
    is anonymized or made a claim we can't honor, or nobody gave any identity.
    """
    rows = (
        Ticket.objects.filter(contact__isnull=True)
        .filter(
            Q(widget_session__isnull=True)
            | ~Q(widget_session__organization_id=F("organization_id"))
        )
        .order_by()
        .values_list("pk", "organization_id", "external_user_id", "requester_email")
    )
    for batch in batched(rows.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        identities = {row[0]: _identity(row[2], row[3]) for row in batch}
        _link_batch(Contact, Ticket, batch, identities, created, declares=False)


def _declare_ticket_emails(Ticket, Contact, new_contacts: QuerySet) -> None:
    """Give a new identified contact without an email its latest usable ticket's."""
    undeclared = new_contacts.filter(declared_email="").exclude(external_id="")
    rows = (
        Ticket.objects.filter(contact__in=undeclared)
        .exclude(requester_email="")
        .order_by("contact_id", "-created_at")
        .values_list("contact_id", "requester_email")
    )
    declared = {}
    for contact_id, group in groupby(
        rows.iterator(chunk_size=BATCH_SIZE), key=itemgetter(0)
    ):
        email = next(filter(None, (clean_email(row[1]) for row in group)), "")
        if email:
            declared[contact_id] = email
    _set_values(Contact.objects.all(), "declared_email", declared, CharField())


def _fill_new_contacts(Ticket, WidgetSession, new_contacts: QuerySet) -> None:
    """Set the name and seen dates of new contacts, from the rows linked to them."""

    def linked(Model):
        return Model.objects.filter(contact_id=OuterRef("pk")).order_by()

    def aggregate(Model, function, field):
        rows = linked(Model).values("contact_id").annotate(value=function(field))
        return Subquery(rows.values("value"))

    def latest_name(Model, name_field, date_field):
        rows = linked(Model).annotate(clean_name=Trim(name_field))
        rows = rows.exclude(clean_name="").order_by(f"-{date_field}")
        return Subquery(rows.values("clean_name")[:1])

    new_contacts.update(
        # LEAST and GREATEST ignore NULLs on Postgres: either side can have no row.
        first_seen_at=Least(
            aggregate(WidgetSession, Min, "created_at"),
            aggregate(Ticket, Min, "created_at"),
        ),
        last_seen_at=Greatest(
            aggregate(WidgetSession, Max, "last_seen_at"),
            aggregate(Ticket, Max, "created_at"),
        ),
        name=Coalesce(
            latest_name(WidgetSession, "name", "last_seen_at"),
            latest_name(Ticket, "requester_name", "created_at"),
            Value(""),
        ),
    )


def backfill(apps, schema_editor) -> None:
    """Create the contacts behind existing sessions and tickets, and link them all."""
    Contact = apps.get_model("contacts", "Contact")
    Ticket = apps.get_model("tickets", "Ticket")
    WidgetSession = apps.get_model("tickets", "WidgetSession")

    # Only ids, so it stays small next to the rows the batches keep out of memory.
    created: set = set()
    _link_sessions(Contact, Ticket, WidgetSession, created)
    _link_tickets_to_their_session(Ticket, WidgetSession)
    _link_tickets_without_session(Contact, Ticket, created)

    for contact_ids in batched(created, BATCH_SIZE):
        new_contacts = Contact.objects.filter(pk__in=contact_ids)
        _declare_ticket_emails(Ticket, Contact, new_contacts)
        _fill_new_contacts(Ticket, WidgetSession, new_contacts)
