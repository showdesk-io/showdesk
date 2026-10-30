# Contacts & Companies Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add org-scoped `Contact` / `Company` records (with custom attributes, notes, GDPR export/anonymize) and link every widget session and ticket to a Contact, as specified in `docs/plans/2026-10-29-contacts-design.md`.

**Architecture:** New Django app `apps.contacts` (models, one identity service module, DRF viewsets, one Celery task). Existing widget endpoints in `apps/tickets/views.py` call the identity service; a data migration back-fills contacts. Frontend gets API modules, React Query hooks, Contacts/Companies pages, a ticket sidebar card and two settings tabs. The widget forwards an optional `email_hash`, `traits` and `company`.

**Tech Stack:** Django 6.1, DRF, django-filter, Celery, pytest + factory_boy; React 19, TypeScript, React Query, React Router 8, Tailwind 4, Vitest; widget in vanilla TS.

**Branch:** `feat/contacts`, created from `docs/channels-design` (carries the design docs). PR → `develop`.

---

## Conventions for every task

- Code, comments, UI strings: English.
- Backend tests live in `backend/tests/contacts/` (create `__init__.py`), use fixtures from `backend/tests/conftest.py` (`organization`, `agent`, `admin_user`, `authenticated_client`, `admin_client`) and factories from `backend/tests/factories.py`.
- Run backend tests from `backend/` with the env below. Never touch containers other than the two disposable ones.
- Commit after each green task with a Conventional Commit (`feat(backend): …`, `feat(frontend): …`, `feat(widget): …`), ending with the `Co-Authored-By` trailer.

### Test environment (once per session)

```bash
docker run -d --rm --name showdesk-test-pg -p 25432:5432 \
  -e POSTGRES_DB=showdesk_test -e POSTGRES_USER=showdesk -e POSTGRES_PASSWORD=showdesk \
  postgres:17-alpine
docker run -d --rm --name showdesk-test-redis -p 26379:6379 redis:8-alpine
export DATABASE_URL=postgres://showdesk:showdesk@localhost:25432/showdesk_test
export REDIS_URL=redis://localhost:26379/0
export CELERY_BROKER_URL=redis://localhost:26379/1
export CELERY_RESULT_BACKEND=redis://localhost:26379/2
cd backend && python -m pytest -q   # baseline: all green before starting
```

Lint: `ruff check backend/ && ruff format --check backend/` (ruff 0.17).
Frontend (Node 26): `cd frontend && npm run lint && npm test && npm run build`.
Widget: `cd widget && npm run lint && npm run build`.
Teardown at the end: `docker stop showdesk-test-pg showdesk-test-redis`.

---

### Task 1: App skeleton, `Contact` and `Company` models

**Files:**
- Create: `backend/apps/contacts/__init__.py`, `apps.py`, `models.py`, `admin.py`, `migrations/__init__.py`
- Modify: `backend/config/settings/base.py` (`LOCAL_APPS`), `backend/tests/factories.py`
- Test: `backend/tests/contacts/__init__.py`, `backend/tests/contacts/test_models.py`

**Step 1: Write the failing tests**

```python
"""Tests for Contact and Company models."""

import pytest
from django.db import IntegrityError

from tests.factories import CompanyFactory, ContactFactory, OrganizationFactory

pytestmark = pytest.mark.django_db


def test_contact_email_unique_per_org():
    contact = ContactFactory(email="alice@startup.com")
    with pytest.raises(IntegrityError):
        ContactFactory(organization=contact.organization, email="alice@startup.com")


def test_contact_same_email_allowed_in_other_org():
    ContactFactory(email="alice@startup.com")
    ContactFactory(organization=OrganizationFactory(), email="alice@startup.com")


def test_contact_blank_email_not_unique():
    org = OrganizationFactory()
    ContactFactory(organization=org, email="")
    ContactFactory(organization=org, email="")


def test_contact_external_id_unique_per_org():
    contact = ContactFactory(external_id="user_1")
    with pytest.raises(IntegrityError):
        ContactFactory(organization=contact.organization, external_id="user_1")


def test_contact_email_is_lowercased_on_save():
    assert ContactFactory(email="Alice@Startup.COM").email == "alice@startup.com"


def test_contact_display_name_falls_back_to_email():
    assert ContactFactory(name="", email="bob@x.io").display_name == "bob@x.io"
    assert ContactFactory(name="Bob", email="bob2@x.io").display_name == "Bob"


def test_company_domain_unique_per_org_and_lowercased():
    company = CompanyFactory(domain="Startup.com")
    assert company.domain == "startup.com"
    with pytest.raises(IntegrityError):
        CompanyFactory(organization=company.organization, domain="startup.com")
```

Factories (import `Company, Contact` from `apps.contacts.models`):

```python
class CompanyFactory(factory.django.DjangoModelFactory):
    """Factory for creating Company instances."""

    class Meta:
        model = Company

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Company {n}")
    domain = factory.Sequence(lambda n: f"company{n}.example")


class ContactFactory(factory.django.DjangoModelFactory):
    """Factory for creating Contact instances."""

    class Meta:
        model = Contact

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Faker("name")
    email = factory.Sequence(lambda n: f"contact{n}@customer.example")
```

**Step 2: Run to verify failure**

Run: `python -m pytest tests/contacts/test_models.py -q`
Expected: `ModuleNotFoundError: No module named 'apps.contacts'`.

**Step 3: Implement**

`apps.py`:

```python
from django.apps import AppConfig


class ContactsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contacts"
    verbose_name = "Contacts"
```

`models.py`:

```python
"""Contacts (end-users) and Companies of an Organization."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel


class Company(TimestampedModel):
    """The business a Contact belongs to (a customer of the Organization)."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="companies",
    )
    external_id = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True, default="")
    logo_url = models.URLField(blank=True)
    industry = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=50, blank=True)
    website = models.URLField(blank=True)
    plan = models.CharField(max_length=100, blank=True)
    mrr_cents = models.PositiveIntegerField(null=True, blank=True)
    health_score = models.PositiveSmallIntegerField(null=True, blank=True)
    signed_up_at = models.DateTimeField(null=True, blank=True)
    churned_at = models.DateTimeField(null=True, blank=True)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "external_id"],
                condition=~Q(external_id=""),
                name="unique_company_external_id_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "domain"],
                condition=~Q(domain=""),
                name="unique_company_domain_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.domain = (self.domain or "").strip().lower()
        super().save(*args, **kwargs)


class Contact(TimestampedModel):
    """An end-user talking to an Organization's support."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts",
    )
    email = models.EmailField(blank=True, default="")
    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once the contact proved they own this email address.",
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="User ID in the host application (HMAC-verified widget identity).",
    )
    phone = models.CharField(max_length=30, blank=True)
    name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(blank=True)
    job_title = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=10, blank=True)
    timezone = models.CharField(max_length=50, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    is_unsubscribed = models.BooleanField(default=False)
    is_anonymized = models.BooleanField(default=False)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_seen_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=~Q(email=""),
                name="unique_contact_email_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "external_id"],
                condition=~Q(external_id=""),
                name="unique_contact_external_id_per_org",
            ),
        ]
        indexes = [models.Index(fields=["organization", "company"])]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        return self.name or self.email or self.external_id or "Anonymous contact"

    def save(self, *args, **kwargs) -> None:
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)
```

`admin.py`: register `Contact` (list_display name, email, organization, last_seen_at; search email, name, external_id) and `Company`.

Add `"apps.contacts",` to `LOCAL_APPS` after `"apps.tickets"`. Run `python manage.py makemigrations contacts`.

**Step 4: Verify** — `python -m pytest tests/contacts/test_models.py -q` → PASS.

**Step 5: Commit** — `feat(backend): add Contact and Company models`

---

### Task 2: Custom attribute definitions and contact notes

**Files:**
- Modify: `backend/apps/contacts/models.py`, `admin.py`, `backend/tests/factories.py`
- Test: `backend/tests/contacts/test_models.py` (append)

**Step 1: Failing tests**

```python
from apps.contacts.models import CompanyAttributeDef, ContactAttributeDef
from tests.factories import ContactAttributeDefFactory, ContactNoteFactory


def test_attribute_key_unique_per_org():
    attr = ContactAttributeDefFactory(key="plan")
    with pytest.raises(IntegrityError):
        ContactAttributeDefFactory(organization=attr.organization, key="plan")


def test_contact_and_company_attribute_keys_are_independent():
    attr = ContactAttributeDefFactory(key="plan")
    CompanyAttributeDef.objects.create(
        organization=attr.organization, key="plan", label="Plan", type="string"
    )


def test_attribute_limit_constant():
    assert ContactAttributeDef.MAX_PER_ORGANIZATION == 50


def test_contact_note_str():
    note = ContactNoteFactory(body="Called them")
    assert note.contact.display_name in str(note)
```

Factories:

```python
class ContactAttributeDefFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContactAttributeDef

    organization = factory.SubFactory(OrganizationFactory)
    key = factory.Sequence(lambda n: f"attr_{n}")
    label = factory.Sequence(lambda n: f"Attribute {n}")
    type = "string"


class ContactNoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContactNote

    contact = factory.SubFactory(ContactFactory)
    author = factory.SubFactory(
        UserFactory, organization=factory.SelfAttribute("..contact.organization")
    )
    body = factory.Faker("sentence")
```

**Step 2:** run → FAIL (import errors).

**Step 3: Implement** (append to `models.py`):

```python
class CustomAttributeDef(TimestampedModel):
    """Definition of a custom attribute an Organization adds to an entity."""

    MAX_PER_ORGANIZATION = 50

    class Type(models.TextChoices):
        STRING = "string", "Text"
        NUMBER = "number", "Number"
        BOOLEAN = "boolean", "Yes/No"
        DATE = "date", "Date"
        ENUM = "enum", "List"
        URL = "url", "URL"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    key = models.SlugField(max_length=64, help_text="snake_case, immutable.")
    label = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=Type.choices)
    description = models.TextField(blank=True)
    options = models.JSONField(default=list, blank=True)
    is_required = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["position", "label"]

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"


class ContactAttributeDef(CustomAttributeDef):
    class Meta(CustomAttributeDef.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="unique_contact_attr_key"
            )
        ]


class CompanyAttributeDef(CustomAttributeDef):
    class Meta(CustomAttributeDef.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="unique_company_attr_key"
            )
        ]


class ContactNote(TimestampedModel):
    """Internal note written by an agent on a contact."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    body = models.TextField()

    def __str__(self) -> str:
        return f"Note on {self.contact.display_name}"
```

Register in admin; `makemigrations contacts`.

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): add custom attribute definitions and contact notes`

---

### Task 3: Link tickets and widget sessions to contacts

**Files:**
- Modify: `backend/apps/tickets/models.py` (`WidgetSession` ~line 140, `Ticket` ~line 254)
- Test: `backend/tests/contacts/test_models.py` (append)

**Step 1: Failing test**

```python
from tests.factories import TicketFactory


def test_ticket_contact_set_null_on_contact_delete():
    contact = ContactFactory()
    ticket = TicketFactory(organization=contact.organization, contact=contact)
    contact.delete()
    ticket.refresh_from_db()
    assert ticket.contact is None
```

**Step 2:** FAIL (unexpected keyword `contact`).

**Step 3: Implement**

`WidgetSession`:

```python
    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
    )
    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when this session proved ownership of its email.",
    )
```

`Ticket` (after `requester`):

```python
    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
```

`makemigrations tickets`.

**Step 4:** full suite `python -m pytest -q` → PASS. **Step 5: Commit** — `feat(backend): link tickets and widget sessions to contacts`

---

### Task 4: Attribute validation

**Files:**
- Create: `backend/apps/contacts/attributes.py`
- Test: `backend/tests/contacts/test_attributes.py`

**Step 1: Failing tests**

```python
import pytest

from apps.contacts.attributes import clean_attributes
from apps.contacts.models import ContactAttributeDef
from tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def defs():
    org = OrganizationFactory()
    for key, type_, options in [
        ("plan", "enum", ["free", "pro"]),
        ("seats", "number", []),
        ("beta", "boolean", []),
        ("signup", "date", []),
        ("site", "url", []),
        ("role", "string", []),
    ]:
        ContactAttributeDef.objects.create(
            organization=org, key=key, label=key, type=type_, options=options
        )
    ContactAttributeDef.objects.create(
        organization=org, key="old", label="old", type="string", is_archived=True
    )
    return ContactAttributeDef.objects.filter(organization=org)


def test_valid_values_are_kept_and_coerced(defs):
    cleaned = clean_attributes(
        defs,
        {
            "plan": "pro",
            "seats": "12",
            "beta": True,
            "signup": "2026-01-15T10:00:00Z",
            "site": "https://acme.io",
            "role": 42,
        },
    )
    assert cleaned == {
        "plan": "pro",
        "seats": 12,
        "beta": True,
        "signup": "2026-01-15",
        "site": "https://acme.io",
        "role": "42",
    }


@pytest.mark.parametrize(
    "traits",
    [
        {"plan": "enterprise"},
        {"seats": "many"},
        {"seats": True},
        {"beta": "yes"},
        {"signup": "not a date"},
        {"site": "javascript:alert(1)"},
        {"unknown": "x"},
        {"old": "x"},
    ],
)
def test_invalid_or_unknown_values_are_dropped(defs, traits):
    assert clean_attributes(defs, traits) == {}


def test_none_clears_a_value(defs):
    assert clean_attributes(defs, {"plan": None}) == {"plan": None}
```

**Step 2:** FAIL (module missing).

**Step 3: Implement** `attributes.py`:

```python
"""Validation of custom attribute values against their definitions."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.dateparse import parse_date, parse_datetime

logger = logging.getLogger(__name__)

_STRING_MAX = 1000
_url_validator = URLValidator(schemes=["http", "https"])


class _Invalid(Exception):
    pass


def _coerce(type_: str, value: Any, options: list) -> Any:
    if type_ == "string":
        if isinstance(value, (dict, list)):
            raise _Invalid
        return str(value)[:_STRING_MAX]
    if type_ == "number":
        if isinstance(value, bool):
            raise _Invalid
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise _Invalid from exc
        return int(number) if number.is_integer() else number
    if type_ == "boolean":
        if not isinstance(value, bool):
            raise _Invalid
        return value
    if type_ == "date":
        if isinstance(value, date):
            return value.isoformat()[:10]
        text = str(value)
        try:
            parsed = parse_datetime(text) or parse_date(text)
        except ValueError as exc:
            raise _Invalid from exc
        if parsed is None:
            raise _Invalid
        return parsed.isoformat()[:10]
    if type_ == "enum":
        if value not in options:
            raise _Invalid
        return value
    if type_ == "url":
        try:
            _url_validator(str(value))
        except ValidationError as exc:
            raise _Invalid from exc
        return str(value)
    raise _Invalid


def clean_attributes(definitions, values: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of ``values`` that matches active ``definitions``.

    Unknown keys, archived definitions and values of the wrong type are
    dropped (and logged) instead of raising, so a host app sending extra
    traits never breaks the widget. ``None`` clears a value.
    """
    by_key = {d.key: d for d in definitions if not d.is_archived}
    cleaned: dict[str, Any] = {}
    for key, value in (values or {}).items():
        definition = by_key.get(key)
        if definition is None:
            logger.info("Dropping unknown attribute %r", key)
            continue
        if value is None:
            cleaned[key] = None
            continue
        try:
            cleaned[key] = _coerce(definition.type, value, definition.options)
        except _Invalid:
            logger.info("Dropping invalid value for attribute %r", key)
    return cleaned
```

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): validate custom attribute values`

---

### Task 5: Identity service

**Files:**
- Create: `backend/apps/contacts/services.py`
- Test: `backend/tests/contacts/test_services.py`

Rules from design §3. The service never merges two existing contacts.

**Step 1: Failing tests**

```python
import pytest

from apps.contacts.models import Company, Contact, ContactAttributeDef
from apps.contacts.services import (
    resolve_contact_for_email,
    resolve_contact_for_widget_session,
)
from apps.tickets.models import WidgetSession
from tests.factories import CompanyFactory, ContactFactory, OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return OrganizationFactory()


def _session(org, **kwargs):
    return WidgetSession.objects.create(organization=org, **kwargs)


class TestEmail:
    def test_creates_contact_from_declared_email(self, org):
        contact = resolve_contact_for_email(org, "Alice@Startup.com", name="Alice")
        assert contact.email == "alice@startup.com"
        assert contact.name == "Alice"
        assert contact.email_verified_at is None

    def test_reuses_existing_contact_and_keeps_name(self, org):
        existing = ContactFactory(organization=org, email="a@x.io", name="Real")
        assert resolve_contact_for_email(org, "a@x.io", name="Fake") == existing
        existing.refresh_from_db()
        assert existing.name == "Real"

    def test_autolinks_company_by_domain(self, org):
        company = CompanyFactory(organization=org, domain="startup.com")
        assert resolve_contact_for_email(org, "bob@startup.com").company == company

    def test_never_autolinks_public_webmail(self, org):
        CompanyFactory(organization=org, domain="gmail.com")
        assert resolve_contact_for_email(org, "bob@gmail.com").company is None


class TestWidgetSession:
    def test_anonymous_without_email_has_no_contact(self, org):
        assert resolve_contact_for_widget_session(_session(org)) is None

    def test_anonymous_with_email_uses_email_contact(self, org):
        session = _session(org, email="c@x.io")
        contact = resolve_contact_for_widget_session(session)
        assert contact.email == "c@x.io"
        session.refresh_from_db()
        assert session.contact == contact

    def test_identified_creates_contact_by_external_id(self, org):
        session = _session(org, external_user_id="u1", email="d@x.io", name="D")
        contact = resolve_contact_for_widget_session(session)
        assert (contact.external_id, contact.email, contact.name) == ("u1", "d@x.io", "D")

    def test_identified_does_not_steal_email_of_other_contact(self, org):
        victim = ContactFactory(organization=org, email="victim@x.io")
        session = _session(org, external_user_id="attacker", email="victim@x.io")
        contact = resolve_contact_for_widget_session(session)
        assert contact != victim
        assert contact.email == ""

    def test_identified_attaches_to_verified_email_contact(self, org):
        session = _session(org, external_user_id="u2", email="e@x.io")
        existing = ContactFactory(organization=org, email="e@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        assert contact == existing
        assert contact.external_id == "u2"
        assert contact.email_verified_at is not None

    def test_verified_email_marks_session_and_contact(self, org):
        session = _session(org, email="f@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        session.refresh_from_db()
        assert session.email_verified_at is not None
        assert contact.email_verified_at is not None

    def test_traits_are_validated(self, org):
        ContactAttributeDef.objects.create(
            organization=org, key="plan", label="Plan", type="string"
        )
        session = _session(org, external_user_id="u3")
        contact = resolve_contact_for_widget_session(
            session, traits={"plan": "pro", "junk": 1}
        )
        assert contact.attributes == {"plan": "pro"}

    def test_company_payload_only_for_identified(self, org):
        identified = _session(org, external_user_id="u4")
        contact = resolve_contact_for_widget_session(
            identified, company={"id": "c42", "name": "Startup", "domain": "startup.io"}
        )
        assert contact.company.external_id == "c42"
        anon = _session(org, email="g@other.io")
        contact = resolve_contact_for_widget_session(
            anon, company={"id": "c43", "name": "Evil"}
        )
        assert contact.company is None
        assert not Company.objects.filter(external_id="c43").exists()

    def test_updates_seen_timestamps(self, org):
        contact = resolve_contact_for_widget_session(_session(org, external_user_id="u5"))
        assert contact.first_seen_at is not None
        assert contact.last_seen_at is not None

    def test_existing_external_id_is_reused(self, org):
        ContactFactory(organization=org, external_id="u6")
        contact = resolve_contact_for_widget_session(_session(org, external_user_id="u6"))
        assert Contact.objects.filter(organization=org, external_id="u6").count() == 1
        assert contact.external_id == "u6"
```

**Step 2:** FAIL (module missing).

**Step 3: Implement** `services.py`:

```python
"""Contact identity resolution shared by the widget and inbound channels.

Security rule: a *declared* email (typed by the user, or set in page
JavaScript) never grants access to anything and never moves an email from
one contact to another. Only a proven email (``email_verified=True``) may
attach an identified session to an existing email-only contact.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.organizations.models import extract_email_domain, is_public_email_domain

from .attributes import clean_attributes
from .models import Company, CompanyAttributeDef, Contact, ContactAttributeDef


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


def _get_or_create(model, lookup: dict, defaults: dict):
    """get_or_create that tolerates a concurrent insert on a unique constraint."""
    try:
        with transaction.atomic():
            return model.objects.get_or_create(**lookup, defaults=defaults)
    except IntegrityError:
        return model.objects.get(**lookup), False


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


def resolve_contact_for_email(organization, email: str, *, name: str = "") -> Contact:
    """Find or create the contact owning a *declared* email address."""
    contact, _ = _get_or_create(
        Contact,
        {"organization": organization, "email": _normalize(email)},
        {"name": name},
    )
    if name and not contact.name:
        contact.name = name
    _autolink_company(contact)
    contact.save()
    return contact


def _upsert_company(organization, payload: dict[str, Any]) -> Company | None:
    external_id = str(payload.get("id") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not external_id or not name:
        return None
    company, _ = _get_or_create(
        Company,
        {"organization": organization, "external_id": external_id},
        {"name": name},
    )
    company.name = name
    domain = str(payload.get("domain") or "").strip().lower()
    domain_taken = (
        Company.objects.filter(organization=organization, domain=domain)
        .exclude(pk=company.pk)
        .exists()
    )
    if domain and not domain_taken:
        company.domain = domain
    traits = payload.get("traits") or {}
    if isinstance(traits, dict) and traits:
        defs = CompanyAttributeDef.objects.filter(organization=organization)
        company.attributes = {**company.attributes, **clean_attributes(defs, traits)}
    company.save()
    return company


def _resolve_identified(session, email: str, email_verified: bool) -> Contact:
    org = session.organization
    contact = Contact.objects.filter(
        organization=org, external_id=session.external_user_id
    ).first()
    if contact is None and email and email_verified:
        contact = Contact.objects.filter(
            organization=org, email=email, external_id=""
        ).first()
        if contact is not None:
            contact.external_id = session.external_user_id
    if contact is None:
        contact, _ = _get_or_create(
            Contact,
            {"organization": org, "external_id": session.external_user_id},
            {"name": session.name},
        )
    if email and not contact.email:
        owned_elsewhere = (
            Contact.objects.filter(organization=org, email=email)
            .exclude(pk=contact.pk)
            .exists()
        )
        if not owned_elsewhere:
            contact.email = email
    return contact


def resolve_contact_for_widget_session(
    session,
    *,
    email_verified: bool = False,
    traits: dict[str, Any] | None = None,
    company: dict[str, Any] | None = None,
) -> Contact | None:
    """Find or create the contact behind a widget session and link them.

    ``session.external_user_id`` must only be set by callers after a
    successful HMAC check. ``email_verified`` must only be True when the
    host app signed the email (``email_hash``) or the user proved ownership.
    """
    email = _normalize(session.email)
    identified = bool(session.external_user_id)

    if identified:
        contact = _resolve_identified(session, email, email_verified)
    elif email:
        contact, _ = _get_or_create(
            Contact, {"organization": session.organization, "email": email}, {}
        )
    else:
        return None

    if session.name and not contact.name:
        contact.name = session.name
    if email_verified and email and contact.email == email:
        contact.email_verified_at = contact.email_verified_at or timezone.now()
    if traits:
        defs = ContactAttributeDef.objects.filter(organization=session.organization)
        contact.attributes = {**contact.attributes, **clean_attributes(defs, traits)}
    if identified and company:
        linked = _upsert_company(session.organization, company)
        if linked:
            contact.company = linked
    _autolink_company(contact)
    _touch(contact)
    contact.save()

    session.contact = contact
    update_fields = ["contact"]
    if email_verified and email and session.email_verified_at is None:
        session.email_verified_at = timezone.now()
        update_fields.append("email_verified_at")
    session.save(update_fields=update_fields)
    return contact
```

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): resolve contacts from widget sessions and emails`

---

### Task 6: `email_hash` verification on Organization

**Files:**
- Modify: `backend/apps/organizations/models.py` (next to `verify_user_hash`, ~line 278)
- Test: `backend/tests/organizations/test_models.py` (append)

**Step 1: Failing tests**

```python
import hashlib
import hmac


@pytest.mark.django_db
def test_verify_email_hash_is_case_insensitive():
    org = OrganizationFactory(widget_secret="s3cret")
    good = hmac.new(b"s3cret", b"alice@startup.com", hashlib.sha256).hexdigest()
    assert org.verify_email_hash("Alice@Startup.com", good)
    assert not org.verify_email_hash("bob@startup.com", good)
    assert not org.verify_email_hash("alice@startup.com", "")


@pytest.mark.django_db
def test_verify_email_hash_without_secret():
    org = OrganizationFactory(widget_secret="")
    assert not org.verify_email_hash("a@b.io", "anything")
```

**Step 2:** FAIL (`AttributeError`).

**Step 3: Implement**

```python
    def verify_email_hash(self, email: str, email_hash: str) -> bool:
        """Verify HMAC-SHA256(widget_secret, lowercase email) from the host app."""
        if not self.widget_secret or not email or not email_hash:
            return False
        return self.verify_user_hash(email.strip().lower(), email_hash)
```

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): verify host-signed widget emails`

---

### Task 7: Wire the identity service into widget endpoints

**Files:**
- Modify: `backend/apps/tickets/views.py` — `widget_session` (~613), `widget_submit` (~241), ticket creation in `widget_message` (~733), `widget_upload_attachment` (~289), `widget_message_attachment` (~839)
- Test: `backend/tests/contacts/test_widget_identity.py`

Read `tests/tickets/test_widget_session.py`, `test_widget_identity.py` and `test_widget_submit.py` first and reuse their request shapes (headers, minimal payloads).

**Step 1: Failing tests**

```python
import hashlib
import hmac

import pytest

from apps.contacts.models import Contact
from apps.tickets.models import Ticket, WidgetSession
from tests.factories import ContactFactory, OrganizationFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/tickets/widget_session/"


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def org():
    return OrganizationFactory(widget_secret="s3cret")


def _post(api_client, org, **body):
    return api_client.post(URL, body, format="json", HTTP_X_WIDGET_TOKEN=str(org.api_token))


def test_identified_session_creates_contact(api_client, org):
    res = _post(
        api_client, org,
        external_user_id="u1", user_hash=_sign("s3cret", "u1"),
        email="alice@startup.com", name="Alice",
    )
    assert res.status_code == 201
    session = WidgetSession.objects.get(id=res.data["session_id"])
    assert session.contact.external_id == "u1"
    assert session.contact.email_verified_at is None


def test_signed_email_verifies_contact(api_client, org):
    res = _post(
        api_client, org,
        external_user_id="u1", user_hash=_sign("s3cret", "u1"),
        email="alice@startup.com", email_hash=_sign("s3cret", "alice@startup.com"),
    )
    session = WidgetSession.objects.get(id=res.data["session_id"])
    assert session.email_verified_at is not None
    assert session.contact.email_verified_at is not None


def test_forged_email_hash_is_ignored_not_rejected(api_client, org):
    res = _post(api_client, org, email="alice@startup.com", email_hash="forged")
    assert res.status_code == 201
    assert WidgetSession.objects.get(id=res.data["session_id"]).email_verified_at is None


def test_company_is_stored_for_identified(api_client, org):
    res = _post(
        api_client, org,
        external_user_id="u2", user_hash=_sign("s3cret", "u2"),
        company={"id": "c1", "name": "Startup Inc", "domain": "startup.com"},
    )
    contact = WidgetSession.objects.get(id=res.data["session_id"]).contact
    assert contact.company.name == "Startup Inc"


def test_patch_email_links_contact(api_client, org):
    session_id = _post(api_client, org).data["session_id"]
    api_client.patch(
        URL, {"email": "bob@x.io"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=session_id,
    )
    assert WidgetSession.objects.get(id=session_id).contact.email == "bob@x.io"


def test_first_widget_message_links_ticket_to_contact(api_client, org):
    session_id = _post(
        api_client, org, external_user_id="u3", user_hash=_sign("s3cret", "u3")
    ).data["session_id"]
    api_client.post(
        "/api/v1/tickets/widget_message/", {"body": "Help"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=session_id,
    )
    assert Ticket.objects.get(widget_session_id=session_id).contact.external_id == "u3"


def test_widget_submit_links_contact_by_email(api_client, org):
    ContactFactory(organization=org, email="carol@x.io")
    payload = {  # adjust to the minimal valid payload of test_widget_submit.py
        "title": "Bug", "description": "Broken",
        "requester_name": "Carol", "requester_email": "carol@x.io",
    }
    res = api_client.post(
        "/api/v1/tickets/widget_submit/", payload, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
    )
    assert res.status_code == 201
    assert Ticket.objects.get(id=res.data["id"]).contact.email == "carol@x.io"
    assert Contact.objects.filter(organization=org).count() == 1
```

**Step 2:** FAIL.

**Step 3: Implement**

Import at the top of `views.py`:

```python
from apps.contacts.services import (
    resolve_contact_for_email,
    resolve_contact_for_widget_session,
)
```

Helper next to `_get_widget_session`:

```python
def _link_session_contact(request, org, session) -> None:
    """Resolve the session's contact from the widget init payload.

    ``email_hash`` is optional: an invalid one is ignored (the email stays
    merely declared) so a misconfigured host app never breaks the widget.
    """
    email_hash = request.data.get("email_hash", "")
    email_verified = bool(
        session.email and email_hash and org.verify_email_hash(session.email, email_hash)
    )
    traits = request.data.get("traits")
    company = request.data.get("company")
    resolve_contact_for_widget_session(
        session,
        email_verified=email_verified,
        traits=traits if isinstance(traits, dict) else None,
        company=company if isinstance(company, dict) else None,
    )
```

In `widget_session`:
- PATCH: after `session.save(...)` call `_link_session_contact(request, org, session)`.
- POST: call `_link_session_contact(request, org, session)` immediately before each of the three `return Response(WidgetSessionSerializer(session).data …)` (resume, HMAC, anonymous).

Every `Ticket.objects.create(...)` with `widget_session=session` (in `widget_message`, `widget_upload_attachment`, `widget_message_attachment`) gets `contact=session.contact,`.

In `widget_submit`, after `serializer.save(...)`:

```python
        if ticket.requester_email:
            ticket.contact = resolve_contact_for_email(
                organization, ticket.requester_email, name=ticket.requester_name
            )
            ticket.save(update_fields=["contact"])
```

**Step 4:** `python -m pytest tests/contacts tests/tickets -q` → PASS (existing widget tests stay green). **Step 5: Commit** — `feat(backend): resolve contacts from the widget`

---

### Task 8: Back-fill migration

**Files:**
- Create: `backend/apps/contacts/backfill.py`, `backend/apps/contacts/migrations/0003_backfill_contacts.py`
- Test: `backend/tests/contacts/test_backfill.py`

The function takes `(apps, schema_editor)` so it can be unit-tested with the real registry.

**Step 1: Failing tests**

```python
import pytest
from django.apps import apps as django_apps

from apps.contacts.backfill import backfill
from apps.contacts.models import Contact
from apps.tickets.models import WidgetSession
from tests.factories import OrganizationFactory, TicketFactory

pytestmark = pytest.mark.django_db


def test_backfill_groups_by_external_id_then_email():
    org = OrganizationFactory()
    s1 = WidgetSession.objects.create(organization=org, external_user_id="u1", email="A@x.io")
    t1 = TicketFactory(organization=org, external_user_id="u1", requester_email="a@x.io")
    t2 = TicketFactory(organization=org, requester=None, requester_email="b@x.io")
    t3 = TicketFactory(organization=org, requester=None, requester_email="B@x.io")

    backfill(django_apps, None)

    assert Contact.objects.filter(organization=org).count() == 2
    for obj in (s1, t1, t2, t3):
        obj.refresh_from_db()
    assert s1.contact == t1.contact
    assert (s1.contact.external_id, s1.contact.email) == ("u1", "a@x.io")
    assert t2.contact == t3.contact
    assert t2.contact.email_verified_at is None


def test_backfill_is_idempotent():
    org = OrganizationFactory()
    TicketFactory(organization=org, requester=None, requester_email="c@x.io")
    backfill(django_apps, None)
    backfill(django_apps, None)
    assert Contact.objects.filter(organization=org).count() == 1


def test_backfill_does_not_reuse_email_owned_by_other_external_id():
    org = OrganizationFactory()
    WidgetSession.objects.create(organization=org, external_user_id="u1", email="d@x.io")
    WidgetSession.objects.create(organization=org, external_user_id="u2", email="d@x.io")
    backfill(django_apps, None)
    emails = sorted(Contact.objects.filter(organization=org).values_list("email", flat=True))
    assert emails == ["", "d@x.io"]
```

**Step 2:** FAIL.

**Step 3: Implement** `backfill.py`:

```python
"""One-off back-fill of Contacts from existing tickets and widget sessions.

Historical models have no custom ``save()``, so emails are lowercased here.
"""


def backfill(apps, schema_editor) -> None:
    Contact = apps.get_model("contacts", "Contact")
    Ticket = apps.get_model("tickets", "Ticket")
    WidgetSession = apps.get_model("tickets", "WidgetSession")

    def norm(email):
        return (email or "").strip().lower()

    def for_external(org_id, external_id, email, name):
        contact = Contact.objects.filter(
            organization_id=org_id, external_id=external_id
        ).first()
        if contact:
            return contact
        taken = bool(email) and Contact.objects.filter(
            organization_id=org_id, email=email
        ).exists()
        return Contact.objects.create(
            organization_id=org_id,
            external_id=external_id,
            email="" if taken else email,
            name=name,
        )

    def for_email(org_id, email, name):
        contact = Contact.objects.filter(organization_id=org_id, email=email).first()
        return contact or Contact.objects.create(
            organization_id=org_id, email=email, name=name
        )

    sessions = WidgetSession.objects.filter(contact__isnull=True)
    for session in sessions.exclude(external_user_id="").order_by("-last_seen_at"):
        session.contact = for_external(
            session.organization_id, session.external_user_id,
            norm(session.email), session.name,
        )
        session.save(update_fields=["contact"])

    tickets = Ticket.objects.filter(contact__isnull=True)
    for ticket in tickets.exclude(external_user_id=""):
        ticket.contact = for_external(
            ticket.organization_id, ticket.external_user_id,
            norm(ticket.requester_email), ticket.requester_name,
        )
        ticket.save(update_fields=["contact"])

    for session in WidgetSession.objects.filter(contact__isnull=True).exclude(email=""):
        session.contact = for_email(session.organization_id, norm(session.email), session.name)
        session.save(update_fields=["contact"])

    for ticket in Ticket.objects.filter(contact__isnull=True).exclude(requester_email=""):
        session = (
            WidgetSession.objects.filter(pk=ticket.widget_session_id).first()
            if ticket.widget_session_id
            else None
        )
        if session and session.contact_id:
            ticket.contact_id = session.contact_id
        else:
            ticket.contact = for_email(
                ticket.organization_id, norm(ticket.requester_email), ticket.requester_name
            )
        ticket.save(update_fields=["contact"])
```

Migration (fill in the generated migration names):

```python
from django.db import migrations

from apps.contacts.backfill import backfill


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0002_<generated>"),
        ("tickets", "0010_<generated>"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
```

**Step 4:** tests PASS; `python manage.py migrate` succeeds on the test DB. **Step 5: Commit** — `feat(backend): back-fill contacts from existing tickets`

---

### Task 9: Contact serializers and viewset

**Files:**
- Create: `backend/apps/contacts/serializers.py`, `views.py`, `permissions.py`, `summary.py`
- Modify: `backend/config/api_urls.py`
- Test: `backend/tests/contacts/test_contacts_api.py`

Endpoints: `GET/POST /api/v1/contacts/`, `GET/PATCH/DELETE /api/v1/contacts/{id}/` (DELETE admin only), `GET /contacts/{id}/tickets/`, `GET/POST /contacts/{id}/notes/`. Query params: `search` (name, email, external_id), `company`, `email_verified=true|false`, `last_seen_after`, `last_seen_before` (ISO datetimes; invalid values ignored), `attr.<key>=<value>`, `page`, `page_size` (≤ 100).

**Step 1: Failing tests**

```python
import pytest
from django.utils import timezone

from tests.factories import (
    ContactAttributeDefFactory,
    ContactFactory,
    ContactNoteFactory,
    OrganizationFactory,
    TicketFactory,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/contacts/"


def test_list_is_scoped_to_org(authenticated_client, organization):
    mine = ContactFactory(organization=organization)
    ContactFactory(organization=OrganizationFactory())
    res = authenticated_client.get(URL)
    assert res.status_code == 200
    assert [c["id"] for c in res.data["results"]] == [str(mine.id)]


def test_list_includes_counts(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=organization, contact=contact, status="open")
    TicketFactory(organization=organization, contact=contact, status="closed")
    row = authenticated_client.get(URL).data["results"][0]
    assert (row["open_tickets_count"], row["tickets_count"]) == (1, 2)
    assert row["email_verified"] is False


def test_search_and_attribute_filter(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, key="plan", type="string")
    ContactFactory(organization=organization, name="Alice", attributes={"plan": "pro"})
    ContactFactory(organization=organization, name="Bob", attributes={"plan": "free"})
    assert len(authenticated_client.get(URL, {"search": "ali"}).data["results"]) == 1
    res = authenticated_client.get(URL, {"attr.plan": "pro"})
    assert [c["name"] for c in res.data["results"]] == ["Alice"]


def test_invalid_date_filter_is_ignored(authenticated_client, organization):
    ContactFactory(organization=organization)
    assert authenticated_client.get(URL, {"last_seen_after": "garbage"}).status_code == 200


def test_create_validates_attributes(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, key="seats", type="number")
    res = authenticated_client.post(
        URL, {"email": "New@X.io", "attributes": {"seats": "3", "junk": 1}}, format="json"
    )
    assert res.status_code == 201
    assert res.data["email"] == "new@x.io"
    assert res.data["attributes"] == {"seats": 3}


def test_create_duplicate_email_is_400(authenticated_client, organization):
    ContactFactory(organization=organization, email="dup@x.io")
    assert authenticated_client.post(URL, {"email": "dup@x.io"}, format="json").status_code == 400


def test_patch_merges_attributes(authenticated_client, organization):
    ContactAttributeDefFactory(organization=organization, key="plan", type="string")
    ContactAttributeDefFactory(organization=organization, key="role", type="string")
    contact = ContactFactory(organization=organization, attributes={"plan": "pro"})
    res = authenticated_client.patch(
        f"{URL}{contact.id}/", {"attributes": {"role": "cto"}}, format="json"
    )
    assert res.data["attributes"] == {"plan": "pro", "role": "cto"}


def test_email_verified_is_read_only(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    authenticated_client.patch(
        f"{URL}{contact.id}/", {"email_verified_at": "2026-01-01T00:00:00Z"}, format="json"
    )
    contact.refresh_from_db()
    assert contact.email_verified_at is None


def test_changing_email_clears_verification(authenticated_client, organization):
    contact = ContactFactory(organization=organization, email_verified_at=timezone.now())
    authenticated_client.patch(f"{URL}{contact.id}/", {"email": "other@x.io"}, format="json")
    contact.refresh_from_db()
    assert contact.email_verified_at is None


def test_delete_requires_admin(authenticated_client, admin_client, organization):
    contact = ContactFactory(organization=organization)
    assert authenticated_client.delete(f"{URL}{contact.id}/").status_code == 403
    assert admin_client.delete(f"{URL}{contact.id}/").status_code == 204


def test_other_org_contact_is_404(authenticated_client):
    other = ContactFactory(organization=OrganizationFactory())
    assert authenticated_client.get(f"{URL}{other.id}/").status_code == 404


def test_tickets_and_notes(authenticated_client, organization, agent):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=organization, contact=contact)
    ContactNoteFactory(contact=contact, author=agent)
    assert len(authenticated_client.get(f"{URL}{contact.id}/tickets/").data) == 1
    res = authenticated_client.post(f"{URL}{contact.id}/notes/", {"body": "VIP"}, format="json")
    assert res.status_code == 201
    assert res.data["author_name"]
    assert len(authenticated_client.get(f"{URL}{contact.id}/notes/").data) == 2
```

**Step 2:** FAIL (404).

**Step 3: Implement**

`permissions.py`:

```python
from rest_framework.exceptions import PermissionDenied

from apps.organizations.models import User


def require_org_admin(user) -> None:
    if user.role != User.Role.ADMIN and not user.is_superuser:
        raise PermissionDenied("Only admins can perform this action.")
```

`summary.py` (no import of `apps.tickets`, so `tickets/serializers.py` can import it without a cycle):

```python
from rest_framework import serializers

from .models import Company, Contact


class CompanySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "domain", "logo_url", "plan"]


class ContactSummarySerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    email_verified = serializers.SerializerMethodField()
    company_detail = CompanySummarySerializer(source="company", read_only=True)

    class Meta:
        model = Contact
        fields = [
            "id", "display_name", "name", "email", "email_verified",
            "avatar_url", "company_detail",
        ]

    def get_email_verified(self, obj) -> bool:
        return obj.email_verified_at is not None
```

`serializers.py`:

```python
from rest_framework import serializers

from apps.tickets.serializers import TicketListSerializer

from .attributes import clean_attributes
from .models import Contact, ContactAttributeDef, ContactNote
from .summary import CompanySummarySerializer


class ContactSerializer(serializers.ModelSerializer):
    company_detail = CompanySummarySerializer(source="company", read_only=True)
    email_verified = serializers.SerializerMethodField()
    display_name = serializers.CharField(read_only=True)
    tickets_count = serializers.IntegerField(read_only=True, default=0)
    open_tickets_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Contact
        fields = [
            "id", "display_name", "name", "email", "email_verified",
            "email_verified_at", "external_id", "phone", "avatar_url", "job_title",
            "locale", "timezone", "company", "company_detail", "first_seen_at",
            "last_seen_at", "last_contacted_at", "is_unsubscribed", "is_anonymized",
            "attributes", "tickets_count", "open_tickets_count", "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "email_verified_at", "first_seen_at", "last_seen_at",
            "last_contacted_at", "is_anonymized", "created_at", "updated_at",
        ]

    def get_email_verified(self, obj) -> bool:
        return obj.email_verified_at is not None

    def validate_email(self, value: str) -> str:
        return (value or "").strip().lower()

    def validate_company(self, value):
        if value is not None and value.organization_id != self.context["organization"].id:
            raise serializers.ValidationError("Unknown company.")
        return value

    def validate_attributes(self, value):
        defs = ContactAttributeDef.objects.filter(organization=self.context["organization"])
        current = self.instance.attributes if self.instance else {}
        return {**current, **clean_attributes(defs, value or {})}

    def validate(self, attrs):
        org = self.context["organization"]
        for field in ("email", "external_id"):
            value = attrs.get(field)
            if value:
                qs = Contact.objects.filter(organization=org, **{field: value})
                if self.instance:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError(
                        {field: "Another contact already uses this value."}
                    )
        if self.instance and "email" in attrs and attrs["email"] != self.instance.email:
            attrs["email_verified_at"] = None
        return attrs


class ContactNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = ContactNote
        fields = ["id", "body", "author", "author_name", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

    def get_author_name(self, obj) -> str:
        if not obj.author:
            return ""
        return obj.author.get_full_name() or obj.author.email


class ContactTicketSerializer(TicketListSerializer):
    """Ticket rows shown on contact and company timelines."""
```

`views.py`:

```python
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import get_active_org
from apps.tickets.models import Ticket

from .models import Contact
from .permissions import require_org_admin
from .serializers import ContactNoteSerializer, ContactSerializer, ContactTicketSerializer

OPEN_STATUSES = [Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING]


class DirectoryPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_dt(value):
    try:
        return parse_datetime(value or "")
    except ValueError:
        return None


def attribute_filters(params) -> dict:
    """Translate ``attr.<key>=<value>`` query params into JSON lookups."""
    filters = {}
    for key, value in params.items():
        name = key.removeprefix("attr.")
        if name == key or not name.isidentifier():
            continue
        filters[f"attributes__{name}"] = value == "true" if value in ("true", "false") else value
    return filters


class OrgScopedMixin:
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "organization": get_active_org(self.request)}

    def perform_create(self, serializer):
        serializer.save(organization=get_active_org(self.request))

    def perform_destroy(self, instance):
        require_org_admin(self.request.user)
        instance.delete()


class ContactViewSet(OrgScopedMixin, viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    pagination_class = DirectoryPagination
    search_fields = ["name", "email", "external_id"]
    ordering_fields = ["name", "email", "last_seen_at", "created_at"]

    def get_queryset(self):
        org = get_active_org(self.request)
        if not org:
            return Contact.objects.none()
        qs = (
            Contact.objects.filter(organization=org)
            .select_related("company")
            .annotate(
                tickets_count=Count("tickets", distinct=True),
                open_tickets_count=Count(
                    "tickets", filter=Q(tickets__status__in=OPEN_STATUSES), distinct=True
                ),
            )
        )
        params = self.request.query_params
        if company := params.get("company"):
            qs = qs.filter(company_id=company)
        if (verified := params.get("email_verified")) in ("true", "false"):
            qs = qs.filter(email_verified_at__isnull=verified == "false")
        if after := _parse_dt(params.get("last_seen_after")):
            qs = qs.filter(last_seen_at__gte=after)
        if before := _parse_dt(params.get("last_seen_before")):
            qs = qs.filter(last_seen_at__lte=before)
        return qs.filter(**attribute_filters(params))

    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        tickets = self.get_object().tickets.order_by("-updated_at")[:100]
        return Response(ContactTicketSerializer(tickets, many=True).data)

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        contact = self.get_object()
        if request.method == "POST":
            serializer = ContactNoteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(contact=contact, author=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        notes = contact.notes.select_related("author").order_by("-created_at")
        return Response(ContactNoteSerializer(notes, many=True).data)
```

An invalid `company` UUID must not 500: validate with `uuid.UUID(...)` and ignore on `ValueError` (add a test). Register `router.register(r"contacts", ContactViewSet, basename="contact")`.

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): contacts API`

---

### Task 10: Company viewset

**Files:**
- Modify: `backend/apps/contacts/serializers.py`, `views.py`, `backend/config/api_urls.py`
- Test: `backend/tests/contacts/test_companies_api.py`

**Step 1: Failing tests** (follow `test_contacts_api.py`): scoped list with `contacts_count` and `open_tickets_count`; search by name/domain; create lowercases domain, duplicate domain → 400; attributes validated against `CompanyAttributeDef` and merged on PATCH; `GET /companies/{id}/contacts/` lists its contacts; `GET /companies/{id}/tickets/` lists tickets of all its contacts; DELETE admin-only; other org → 404.

**Step 2:** FAIL.

**Step 3: Implement** `CompanySerializer` (all model fields + read-only `contacts_count`, `open_tickets_count`; `validate_domain` lowercases; `validate` enforces per-org uniqueness of `domain` and `external_id`; `validate_attributes` with `CompanyAttributeDef`) and:

```python
class CompanyViewSet(OrgScopedMixin, viewsets.ModelViewSet):
    serializer_class = CompanySerializer
    pagination_class = DirectoryPagination
    search_fields = ["name", "domain", "external_id"]
    ordering_fields = ["name", "created_at", "mrr_cents"]

    def get_queryset(self):
        org = get_active_org(self.request)
        if not org:
            return Company.objects.none()
        qs = Company.objects.filter(organization=org).annotate(
            contacts_count=Count("contacts", distinct=True),
            open_tickets_count=Count(
                "contacts__tickets",
                filter=Q(contacts__tickets__status__in=OPEN_STATUSES),
                distinct=True,
            ),
        )
        return qs.filter(**attribute_filters(self.request.query_params))

    @action(detail=True, methods=["get"])
    def contacts(self, request, pk=None):
        contacts = self.get_object().contacts.order_by("name")[:200]
        serializer = ContactSerializer(
            contacts, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        tickets = Ticket.objects.filter(contact__company=self.get_object()).order_by(
            "-updated_at"
        )[:100]
        return Response(ContactTicketSerializer(tickets, many=True).data)
```

Register `companies`.

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): companies API`

---

### Task 11: Attribute definition endpoints

**Files:**
- Modify: `serializers.py`, `views.py`, `api_urls.py`
- Test: `backend/tests/contacts/test_attribute_defs_api.py`

Behaviour (one test each on `/api/v1/contact-attributes/`, plus a smoke test on `/api/v1/company-attributes/`):
- agents can list (unpaginated, ordered by position/label); agents get 403 on POST/PATCH;
- `key` must match `^[a-z][a-z0-9_]{0,63}$` and is immutable (PATCH with another key → 400);
- `enum` requires a non-empty list of strings in `options`;
- creation beyond `MAX_PER_ORGANIZATION` non-archived definitions → 400;
- DELETE → 405; archive with `PATCH {"is_archived": true}`.

**Step 3: Implement** an `AttributeDefSerializer` base (`fields = ["id", "key", "label", "type", "description", "options", "is_required", "is_archived", "position"]`, validation above; the limit check counts `self.Meta.model.objects.filter(organization=org, is_archived=False)`), two subclasses binding `ContactAttributeDef` / `CompanyAttributeDef`, and:

```python
class AttributeDefViewSet(OrgScopedMixin, viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None
    model = None

    def get_queryset(self):
        org = get_active_org(self.request)
        return self.model.objects.filter(organization=org) if org else self.model.objects.none()

    def perform_create(self, serializer):
        require_org_admin(self.request.user)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        require_org_admin(self.request.user)
        serializer.save()
```

with `ContactAttributeDefViewSet` / `CompanyAttributeDefViewSet` setting `model` and `serializer_class`. Register `contact-attributes`, `company-attributes`.

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): custom attribute definition API`

---

### Task 12: Anonymize a contact

**Files:**
- Create: `backend/apps/contacts/gdpr.py`
- Modify: `views.py`
- Test: `backend/tests/contacts/test_gdpr.py`

**Step 1: Failing tests**

```python
import pytest

from apps.contacts.gdpr import REMOVED_BODY, anonymize_contact
from apps.tickets.models import TicketMessage, WidgetSession
from tests.factories import ContactFactory, TicketFactory, TicketMessageFactory

pytestmark = pytest.mark.django_db


def test_anonymize_scrubs_contact_and_user_messages(organization, agent):
    contact = ContactFactory(
        organization=organization, name="Alice", email="alice@x.io",
        external_id="u1", phone="+33", attributes={"plan": "pro"},
    )
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, email="alice@x.io",
        name="Alice", external_user_id="u1",
    )
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=None,
        requester_email="alice@x.io", requester_name="Alice", external_user_id="u1",
        context_url="https://app/x?token=1",
        context_metadata={"browser": "Chrome", "url_params": {"t": 1}},
    )
    user_msg = TicketMessageFactory(
        ticket=ticket, author=None, sender_type=TicketMessage.SenderType.USER, body="secret"
    )
    agent_msg = TicketMessageFactory(ticket=ticket, author=agent, body="reply")

    anonymize_contact(contact)

    for obj in (contact, session, ticket, user_msg, agent_msg):
        obj.refresh_from_db()
    assert contact.is_anonymized
    assert contact.email.endswith("@example.invalid")
    assert (contact.name, contact.phone, contact.external_id) == ("Anonymized contact", "", "")
    assert contact.attributes == {}
    assert (session.email, session.name, session.external_user_id) == ("", "", "")
    assert ticket.requester_email == contact.email
    assert ticket.external_user_id == ""
    assert ticket.context_url == ""
    assert ticket.context_metadata == {"browser": "Chrome"}
    assert user_msg.body == REMOVED_BODY
    assert agent_msg.body == "reply"


def test_anonymize_endpoint_admin_only(authenticated_client, admin_client, organization):
    contact = ContactFactory(organization=organization)
    url = f"/api/v1/contacts/{contact.id}/anonymize/"
    assert authenticated_client.post(url).status_code == 403
    assert admin_client.post(url).status_code == 200
    contact.refresh_from_db()
    assert contact.is_anonymized
```

**Step 2:** FAIL.

**Step 3: Implement** `gdpr.py`:

```python
"""GDPR operations on contacts (export, anonymization)."""

import uuid

from django.db import transaction

from apps.tickets.models import TicketMessage

REMOVED_BODY = "[Content removed at the contact's request]"
KEPT_CONTEXT_KEYS = {"browser", "os", "language", "timezone", "screen_resolution"}


@transaction.atomic
def anonymize_contact(contact) -> None:
    """Irreversibly strip personal data while keeping ticket structure."""
    contact.email = f"anonymized-{uuid.uuid4().hex}@example.invalid"
    contact.name = "Anonymized contact"
    contact.phone = ""
    contact.external_id = ""
    contact.avatar_url = ""
    contact.job_title = ""
    contact.attributes = {}
    contact.email_verified_at = None
    contact.is_anonymized = True
    contact.save()

    contact.sessions.update(email="", name="", external_user_id="", email_verified_at=None)
    TicketMessage.objects.filter(
        ticket__contact=contact, sender_type=TicketMessage.SenderType.USER
    ).update(body=REMOVED_BODY)
    for ticket in contact.tickets.all():
        ticket.requester_email = contact.email
        ticket.requester_name = contact.name
        ticket.external_user_id = ""
        ticket.context_url = ""
        ticket.context_user_agent = ""
        ticket.context_metadata = {
            k: v for k, v in (ticket.context_metadata or {}).items() if k in KEPT_CONTEXT_KEYS
        }
        ticket.save(update_fields=[
            "requester_email", "requester_name", "external_user_id",
            "context_url", "context_user_agent", "context_metadata",
        ])
```

Action on `ContactViewSet`:

```python
    @action(detail=True, methods=["post"])
    def anonymize(self, request, pk=None):
        require_org_admin(request.user)
        contact = self.get_object()
        anonymize_contact(contact)
        return Response(self.get_serializer(self.get_queryset().get(pk=contact.pk)).data)
```

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): anonymize contacts (GDPR art. 17)`

---

### Task 13: Export a contact

**Files:**
- Modify: `backend/apps/core/email.py` (optional `attachments`)
- Modify: `backend/apps/contacts/gdpr.py` (`build_contact_export`); create `backend/apps/contacts/tasks.py`
- Create: `backend/templates/emails/contact_export_ready.html`, `.txt` (model them on `ticket_resolved.*`)
- Modify: `views.py`
- Test: `backend/tests/core/test_email.py`, `backend/tests/contacts/test_gdpr.py` (append)

**Step 1: Failing tests**
- `send_branded_email(..., attachments=[("a.zip", b"PK", "application/zip")])` → `mail.outbox[0].attachments == [("a.zip", b"PK", "application/zip")]`.
- `build_contact_export(contact)` returns ZIP bytes with `contact.json` (profile, attributes, notes), `tickets.json` (tickets + public replies + attachment metadata; an internal note's body must be absent), `tickets.csv` (header `reference,title,status,created_at,resolved_at`).
- `POST /contacts/{id}/export/` as admin with `settings.CELERY_TASK_ALWAYS_EAGER = True` → 202, one email to the admin, subject `Contact export ready`, one zip attachment; as agent → 403.

**Step 3: Implement**
- `send_branded_email` gains `attachments: Iterable[tuple[str, bytes, str]] | None = None` and calls `message.attach(name, content, mimetype)` for each.
- The ZIP is attached to the email (no download link) so personal data never sits on a public storage URL.

```python
# tasks.py
from celery import shared_task

from apps.core.email import send_branded_email


@shared_task
def export_contact_data(contact_id: str, requested_by_id: str) -> None:
    from apps.contacts.gdpr import build_contact_export
    from apps.contacts.models import Contact
    from apps.organizations.models import User

    contact = Contact.objects.select_related("organization").get(id=contact_id)
    user = User.objects.get(id=requested_by_id)
    send_branded_email(
        template="contact_export_ready",
        subject="Contact export ready",
        to=[user.email],
        organization=contact.organization,
        context={"contact_name": contact.display_name},
        attachments=[
            (f"contact-{contact.id}.zip", build_contact_export(contact), "application/zip")
        ],
    )
```

`build_contact_export` uses `zipfile.ZipFile(io.BytesIO(), "w", zipfile.ZIP_DEFLATED)`, `json.dumps(..., default=str, indent=2)`, `csv.writer`; messages filtered on `message_type == TicketMessage.MessageType.REPLY`.

Action: `require_org_admin`, `export_contact_data.delay(str(contact.id), str(request.user.id))`, return `Response({"status": "queued"}, status=202)`.

**Step 4:** PASS (including existing `tests/core/test_email.py`). **Step 5: Commit** — `feat(backend): export contact data (GDPR art. 15)`

---

### Task 14: Expose the contact on tickets

**Files:**
- Modify: `backend/apps/tickets/serializers.py` (`TicketSerializer` ~180, `TicketListSerializer` ~246), `backend/apps/tickets/views.py` (`TicketViewSet.get_queryset` ~148)
- Test: `backend/tests/contacts/test_ticket_contact.py`

**Step 1: Failing tests** — `GET /api/v1/tickets/{id}/` returns `contact` and `contact_detail` (`id, display_name, email, email_verified, company_detail`); list rows include `contact_detail`; `PATCH {"contact": <other org contact id>}` → 400.

**Step 3: Implement** — import `ContactSummarySerializer` from `apps.contacts.summary`; add `contact_detail = ContactSummarySerializer(source="contact", read_only=True)` and `"contact", "contact_detail"` to both `fields`; `validate_contact` rejects contacts of another organization (compare with `self.instance.organization_id`, or the active org passed in context on create); add `"contact__company"` to the queryset's `select_related`.

**Step 4:** full suite PASS. **Step 5: Commit** — `feat(backend): expose contact on tickets`

---

### Task 15: Widget forwards `email_hash`, `traits`, `company`

**Files:**
- Modify: `widget/src/types.ts`, `widget/src/widget.ts` (`buildUserFromDataAttrs` ~73), `widget/src/api/chat-api.ts` (`createOrResumeSession` ~25)
- Modify: widget integration docs (`grep -rn "data-user-hash" docs README.md widget` to find them)

No widget test runner exists; verification is `npm run lint && npm run build` plus the backend tests of Task 7.

```ts
export interface ShowdeskUserIdentity {
  id?: string;
  name?: string;
  email?: string;
  /** HMAC-SHA256(widget_secret, id) — computed server-side, enables ticket history. */
  hash?: string;
  /** HMAC-SHA256(widget_secret, lowercase email) — optional, proves the email. */
  emailHash?: string;
  /** Custom contact attributes (defined in Settings → Contact attributes). */
  traits?: Record<string, unknown>;
}

export interface ShowdeskCompany {
  id: string;
  name: string;
  domain?: string;
  traits?: Record<string, unknown>;
}
```

Add `company?: ShowdeskCompany;` to `ShowdeskConfig`; read `el.dataset["userEmailHash"]` in `buildUserFromDataAttrs`; in `createOrResumeSession` type `body` as `Record<string, unknown>` and add:

```ts
  if (config.user?.emailHash) body.email_hash = config.user.emailHash;
  if (config.user?.traits) body.traits = config.user.traits;
  if (config.company) body.company = config.company;
```

Docs: `data-user-email-hash`, `init({ user: { emailHash, traits }, company })`, a server-side snippet computing both HMACs, and the note that `traits` / `company` are honoured only for HMAC-identified users.

**Commit** — `feat(widget): send signed email, traits and company`

---

### Task 16: Frontend types, API modules and hooks

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/contacts.ts`, `companies.ts`, `attributeDefs.ts`
- Create: `frontend/src/hooks/useContacts.ts`, `useCompanies.ts`, `useAttributeDefs.ts`
- Test: `frontend/src/api/__tests__/contacts.test.ts` (or next to existing hook tests in `frontend/src/hooks/__tests__/`)

Types: `Contact`, `ContactSummary`, `Company`, `CompanySummary`, `ContactNote`, `AttributeDef` (`type: "string" | "number" | "boolean" | "date" | "enum" | "url"`); add `contact: string | null; contact_detail: ContactSummary | null;` to both ticket types.

API (mirror `api/tags.ts`): `fetchContacts(params)` → `PaginatedResponse<Contact>` with `search, company, email_verified, page, page_size` and `attrs: Record<string, string>` mapped to `attr.<key>`; `fetchContact`, `createContact`, `updateContact`, `deleteContact`, `fetchContactTickets`, `fetchContactNotes`, `createContactNote`, `exportContact`, `anonymizeContact`; companies: list/get/create/update/delete, `fetchCompanyContacts`, `fetchCompanyTickets`; `fetchAttributeDefs(entity)`, `createAttributeDef(entity, data)`, `updateAttributeDef(entity, id, data)`.

Hooks (mirror `hooks/useTags.ts`) with keys `["contacts", params]`, `["contact", id]`, `["contact", id, "tickets"]`, `["contact", id, "notes"]`, `["companies", params]`, `["company", id]`, `["attributeDefs", entity]`; mutations invalidate the matching keys (and `["tickets"]` after anonymize).

Test: `fetchContacts({ attrs: { plan: "pro" }, search: "a" })` calls `apiClient.get("/contacts/", { params: { "attr.plan": "pro", search: "a" } })` (mock `./client`).

Run `npm test -- contacts` → FAIL, then PASS. **Commit** — `feat(frontend): contacts API client and hooks`

---

### Task 17: Contacts and Companies lists, routing, sidebar

**Files:**
- Create: `frontend/src/pages/ContactsPage.tsx`, `frontend/src/components/contacts/ContactList.tsx`, `CompanyList.tsx`, `UnverifiedBadge.tsx`
- Modify: `frontend/src/App.tsx` (routes `contacts`, `contacts/:id`, `companies`, `companies/:id` next to `tickets`), `frontend/src/components/layout/AppLayout.tsx` (`navItems`: "Contacts" between Tickets and Team, active on `/contacts*` and `/companies*`)
- Test: `frontend/src/pages/__tests__/ContactsPage.test.tsx`

Behaviour:
- Tabs "Contacts | Companies" driven by the route.
- Contacts table: avatar (initials fallback), name, email + `UnverifiedBadge` when the email is set and not verified, company, last seen (relative), open tickets; row click → `/contacts/:id`.
- Debounced (300 ms) search, company select (`useCompanies({ page_size: 100 })`), "Verified email only" checkbox, one select per non-archived `enum`/`boolean` attribute.
- Pagination: 25/50/100 selector, previous/next from `count`.
- "Add contact" modal (name, email); show field errors from a 400.
- Companies table: logo + name, domain, contacts, open tickets, plan; "Add company" modal.

Tests: rows rendered from mocked API; typing in search refetches with `search`; badge shown for unverified; Companies tab navigates.

Run `npm test`, `npm run lint`. **Commit** — `feat(frontend): contacts and companies lists`

---

### Task 18: Contact detail page

**Files:**
- Create: `frontend/src/pages/ContactDetailPage.tsx`, `frontend/src/components/contacts/AttributeEditor.tsx` (shared), `ContactTimeline.tsx`
- Test: `frontend/src/pages/__tests__/ContactDetailPage.test.tsx`

Layout (`lg:grid-cols-4`):
- Left: avatar, inline-editable name, email + verified/unverified badge, phone, company link, external id (read-only, monospace), `AttributeEditor` (typed inputs per non-archived def: text, number, checkbox, date, select, url; saves `updateContact({ attributes: { [key]: value } })`); admin-only "Export data" (toast "Export queued — you will receive it by email") and "Anonymize" (confirm modal requiring the contact's email to be typed; hidden when `is_anonymized`).
- Centre (2 cols): filter All / Tickets / Notes, "Add note" box, list sorted by date (tickets: reference, title, status badge, link; notes: author, body).
- Right: total and open tickets, first/last seen, company plan and MRR, company link.

Tests: profile and timeline render; adding a note calls `createContactNote`; anonymize hidden for agents; editing an attribute calls `updateContact` with the attribute payload.

**Commit** — `feat(frontend): contact detail page`

---

### Task 19: Company detail page

**Files:**
- Create: `frontend/src/pages/CompanyDetailPage.tsx`
- Test: `frontend/src/pages/__tests__/CompanyDetailPage.test.tsx`

Left: logo, name, domain, website link, plan, MRR (`mrr_cents / 100`, no currency), health score, `AttributeEditor` for company defs, inline edits via `updateCompany`. Centre: tabs Tickets (`fetchCompanyTickets`) / People (`fetchCompanyContacts`, rows link to contacts). Test both tabs with mocked data.

**Commit** — `feat(frontend): company detail page`

---

### Task 20: Contact card on the ticket detail

**Files:**
- Create: `frontend/src/components/contacts/ContactCard.tsx`
- Modify: `frontend/src/components/tickets/TicketDetail.tsx` (the "Requester" block, ~line 970)
- Test: `frontend/src/components/contacts/__tests__/ContactCard.test.tsx`

When `ticket.contact_detail` exists: heading "Contact", name linking to `/contacts/:id`, email + `UnverifiedBadge`, company line (logo, name, plan) linking to `/companies/:id`, "Other tickets: N" from `useContactTickets` excluding the current ticket. Otherwise keep the current requester rendering.

**Commit** — `feat(frontend): contact card on ticket detail`

---

### Task 21: Settings tabs for attribute definitions

**Files:**
- Create: `frontend/src/components/settings/AttributeDefsTab.tsx` (prop `entity: "contact" | "company"`)
- Modify: `frontend/src/pages/SettingsPage.tsx` (`tabs` ~line 48: add "Contact attributes", "Company attributes"; render the tab with `isAdmin`)
- Test: `frontend/src/components/settings/__tests__/AttributeDefsTab.test.tsx`

Table: label, key (monospace), type, options, archived toggle. Admin-only form: label → suggested snake_case key (editable until saved, then read-only), type select, comma-separated options for enum, counter "N / 50". Agents see a read-only table. Tests: key suggestion, enum requires options, no form for agents.

**Commit** — `feat(frontend): manage custom attributes in settings`

---

### Task 22: Docs, final verification, PR

**Steps**
1. `ROADMAP.md`: add under Phase 3.5 a "Contacts & Companies (P0)" checklist, checked, and keep P1 items as open bullets. Confirm no `.env.example` change is needed (this PR adds no variable).
2. `cd backend && python -m pytest -q` → all green; `ruff check backend/ && ruff format --check backend/` → clean; `python manage.py makemigrations --check --dry-run` → "No changes detected".
3. `cd frontend && npm run lint && npm test && npm run build` → clean, 0 warnings.
4. `cd widget && npm run lint && npm run build` → clean.
5. Manual smoke with `make dev`: Contacts page, create a contact, a widget session with `data-user-*` attributes creates/updates a contact, the ticket card links to it.
6. Use superpowers:requesting-code-review; address findings.
7. Push `feat/contacts`; open a PR → `develop` titled `feat: contacts and companies` with summary, migration note (back-fill runs during the deploy migrate step), test instructions for the development environment, the `CONTRIBUTING.md` checklist, and the Claude Code attribution line.
8. `docker stop showdesk-test-pg showdesk-test-redis`.
