# Contacts & Companies Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add org-scoped `Contact` / `Company` records (with custom attributes, notes, GDPR export/anonymize) and link every widget session and ticket to a Contact, as specified in `docs/plans/2026-10-29-contacts-design.md`.

**Architecture:** New Django app `apps.contacts` (models, one identity service module, DRF viewsets, one Celery task). Existing widget endpoints in `apps/tickets/views.py` call the identity service; a data migration back-fills contacts. Frontend gets API modules, React Query hooks, Contacts/Companies pages, a ticket sidebar card and two settings tabs. The widget forwards an optional `email_hash`, `company_hash`, `traits` and `company`.

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

> **Superseded after the identity review.** The snippets below are the first version. `backend/apps/contacts/services.py` and its tests are authoritative: `declared_email`, `company_verified`, row locks, `update_fields`. Later tasks are written against that version: `resolve_contact_for_widget_session(session, *, email_verified, traits, company, company_verified)`.

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

### Task 6: `email_hash` and `company_hash` verification on Organization

**Files:**
- Modify: `backend/apps/organizations/models.py` (next to `verify_user_hash`, ~line 278)
- Test: `backend/tests/organizations/test_models.py` (append)

Each hash signs a prefixed message, so hashes aren't interchangeable with `user_hash` or with each other: `HMAC(secret, "email:" + lowercase(email))` and `HMAC(secret, "company\n" + id + "\n" + name + "\n" + lowercase(domain))`, with `domain` empty if absent. The company hash covers the name and domain so a member can't replay it with a forged name or domain. `traits` aren't signed (see Task 7 and design rule 4). A colon separator would be ambiguous (`c1:x` + `Acme` and `c1` + `x:Acme` would sign the same message), so fields are separated by newlines and an id, name or domain containing a newline never verifies.

Malformed input is never an error: a non-string value, a non-ASCII hash (`hmac.compare_digest` raises `TypeError` on one) or a lone surrogate (`str.encode` raises `UnicodeEncodeError`) returns False. A non-ASCII email or company name is legitimate and is signed as UTF-8.

**Step 1: Failing tests**

```python
import hashlib
import hmac


def _sign(message: bytes) -> str:
    return hmac.new(b"s3cret", message, hashlib.sha256).hexdigest()


@pytest.mark.django_db
def test_verify_email_hash_is_case_insensitive():
    org = OrganizationFactory(widget_secret="s3cret")
    good = _sign(b"email:alice@startup.com")
    assert org.verify_email_hash("Alice@Startup.com", good)
    assert not org.verify_email_hash("bob@startup.com", good)
    assert not org.verify_email_hash("alice@startup.com", "")


@pytest.mark.django_db
def test_verify_email_hash_without_secret():
    org = OrganizationFactory(widget_secret="")
    assert not org.verify_email_hash("a@b.io", "anything")


@pytest.mark.django_db
def test_verify_company_hash():
    org = OrganizationFactory(widget_secret="s3cret")
    good = _sign(b"company\nc1\nAcme\nacme.io")
    assert org.verify_company_hash("c1", "Acme", "acme.io", good)
    assert org.verify_company_hash("c1", "Acme", "ACME.io", good)
    assert not org.verify_company_hash("c2", "Acme", "acme.io", good)
    assert not org.verify_company_hash("c1", "Forged", "acme.io", good)
    assert not org.verify_company_hash("c1", "Acme", "forged.io", good)
    assert not org.verify_company_hash("c1", "Acme", "", good)
    assert not org.verify_company_hash("c1", "Acme", "acme.io", "")
    assert not OrganizationFactory(widget_secret="").verify_company_hash(
        "c1", "Acme", "acme.io", good
    )


@pytest.mark.django_db
@pytest.mark.parametrize("domain", ["", None])
def test_verify_company_hash_without_domain(domain):
    org = OrganizationFactory(widget_secret="s3cret")
    assert org.verify_company_hash("c1", "Acme", domain, _sign(b"company\nc1\nAcme\n"))


@pytest.mark.django_db
def test_non_ascii_names_are_signed_as_utf8():
    org = OrganizationFactory(widget_secret="s3cret")
    good = _sign("company\nc1\nSociété\n".encode())
    assert org.verify_company_hash("c1", "Société", "", good)


@pytest.mark.django_db
def test_malformed_hash_input_returns_false_without_raising():
    org = OrganizationFactory(widget_secret="s3cret")
    good = _sign(b"email:a@b.io")
    assert not org.verify_email_hash("a@b.io", "é")
    assert not org.verify_email_hash("a@b.io", 1)
    assert not org.verify_email_hash(["a@b.io"], good)
    assert not org.verify_email_hash("\ud800@b.io", good)
    assert not org.verify_email_hash("   ", _sign(b"email:"))
    assert not org.verify_user_hash("u1", "é")
    assert not org.verify_user_hash(1, good)
    assert not org.verify_user_hash("\ud800", good)
    assert not org.verify_company_hash("c1", "A", "", "é")
    assert not org.verify_company_hash(1, "A", "", good)
    assert not org.verify_company_hash("c1", 1, "", good)
    assert not org.verify_company_hash("c1", "A", 1, good)
    assert not org.verify_company_hash("\ud800", "A", "", good)
    assert not org.verify_company_hash("c1", "", "", _sign(b"company\nc1\n\n"))


@pytest.mark.django_db
def test_hashes_are_not_interchangeable():
    org = OrganizationFactory(widget_secret="s3cret")
    assert not org.verify_email_hash("a@b.io", _sign(b"a@b.io"))
    assert not org.verify_company_hash("c1", "A", "", _sign(b"c1\nA\n"))
    assert not org.verify_company_hash("c1", "A", "", _sign(b"email:c1\nA\n"))
    assert not org.verify_email_hash("c1\nA\n", _sign(b"company\nc1\nA\n"))
    assert not org.verify_user_hash("a@b.io", _sign(b"email:a@b.io"))


@pytest.mark.django_db
def test_company_hash_old_colon_format_no_longer_verifies():
    org = OrganizationFactory(widget_secret="s3cret")
    assert not org.verify_company_hash(
        "c1", "Acme", "acme.io", _sign(b"company:c1:Acme:acme.io")
    )


@pytest.mark.django_db
def test_company_hash_fields_cant_be_shifted_across_colons():
    """Under the old format these three signed the very same message."""
    org = OrganizationFactory(widget_secret="s3cret")
    good = _sign(b"company\nc1\nx:Acme\n")
    assert org.verify_company_hash("c1", "x:Acme", "", good)
    assert not org.verify_company_hash("c1:x", "Acme", "", good)
    assert not org.verify_company_hash("c1", "x", "Acme", good)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("company_id", "name", "domain"),
    [
        ("c1\nAcme", "x", ""),
        ("c1", "Acme\nacme.io", ""),
        ("c1", "Acme", "acme.io\n"),
        ("c1", "Acme\n", "acme.io"),
    ],
)
def test_company_hash_refuses_a_newline_in_any_field(company_id, name, domain):
    """Even correctly signed: a newline could shift a value into the next field."""
    org = OrganizationFactory(widget_secret="s3cret")
    message = f"company\n{company_id}\n{name}\n{domain}".encode()
    assert not org.verify_company_hash(company_id, name, domain, _sign(message))
```

**Step 2:** FAIL (`AttributeError`).

**Step 3: Implement** (import `Any` from `typing`; `verify_user_hash` is rewritten on the same helper)

```python
    def _verify_signature(self, message: Any, signature: Any) -> bool:
        """Verify HMAC-SHA256(widget_secret, message). Bad input is just invalid."""
        if (
            not self.widget_secret
            or not isinstance(message, str)
            or not isinstance(signature, str)
            or not signature.isascii()  # compare_digest raises TypeError otherwise.
        ):
            return False
        try:
            encoded = message.encode()
        except UnicodeEncodeError:  # A lone surrogate survives JSON parsing.
            return False
        expected = hmac.new(
            self.widget_secret.encode(), encoded, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_user_hash(self, external_user_id: Any, user_hash: Any) -> bool:
        """Verify an HMAC-SHA256 user hash against the widget secret."""
        return self._verify_signature(external_user_id, user_hash)

    def verify_email_hash(self, email: Any, email_hash: Any) -> bool:
        """Verify HMAC-SHA256(widget_secret, "email:" + lowercase email)."""
        email = email.strip().lower() if isinstance(email, str) else ""
        if not email or not email_hash:
            return False
        return self._verify_signature(f"email:{email}", email_hash)

    def verify_company_hash(
        self, company_id: Any, name: Any, domain: Any, company_hash: Any
    ) -> bool:
        """Verify HMAC-SHA256(widget_secret, "company\\nid\\nname\\nlowercase domain").

        Newlines separate the fields, so a value holding one could spill into the
        next field: it's refused, even correctly signed.
        """
        domain = "" if domain is None else domain
        fields = (company_id, name, domain)
        if (
            not all(isinstance(value, str) for value in fields)
            or any("\n" in value for value in fields)
            or not company_id
            or not name
            or not company_hash
        ):
            return False
        return self._verify_signature(
            f"company\n{company_id}\n{name}\n{domain.lower()}", company_hash
        )
```

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): verify host-signed widget emails and companies`

---

### Task 7: Wire the identity service into widget endpoints

**Files:**
- Modify: `backend/apps/tickets/views.py` — `widget_session` (~613), `widget_submit` (~241), `widget_tickets` (~347), ticket creation in `widget_message` (~733) and `widget_message_attachment` (~839)
- Modify: `backend/apps/tickets/serializers.py`
- Test: `backend/tests/contacts/test_widget_identity.py`

Read `tests/tickets/test_widget_session.py`, `test_widget_identity.py` and `test_widget_submit.py` first and reuse their request shapes (headers, minimal payloads).

**Step 1: Failing tests**

```python
import hashlib
import hmac
import json
from unittest import mock

import pytest
from django.db import DatabaseError, IntegrityError, OperationalError, connection
from django.test.utils import CaptureQueriesContext

from apps.contacts.models import Company, CompanyAttributeDef, Contact
from apps.tickets.models import Ticket, WidgetSession
from tests.factories import (
    CompanyFactory,
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
)

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
    assert session.contact.email == ""
    assert session.contact.declared_email == "alice@startup.com"
    assert session.contact.email_verified_at is None


def test_signed_email_verifies_contact(api_client, org):
    res = _post(
        api_client, org,
        external_user_id="u1", user_hash=_sign("s3cret", "u1"),
        email="alice@startup.com", email_hash=_sign("s3cret", "email:alice@startup.com"),
    )
    session = WidgetSession.objects.get(id=res.data["session_id"])
    assert session.email_verified_at is not None
    assert session.contact.email == "alice@startup.com"
    assert session.contact.email_verified_at is not None


def test_user_hash_of_the_email_does_not_prove_it(api_client, org):
    res = _post(api_client, org, email="alice@startup.com", email_hash=_sign("s3cret", "alice@startup.com"))
    assert WidgetSession.objects.get(id=res.data["session_id"]).email_verified_at is None


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
    assert contact.company.domain == ""  # Unsigned, and no proven email.


def test_signed_company_is_upserted_and_forged_hash_is_not(api_client, org):
    company = CompanyFactory(organization=org, external_id="c1", name="Old")
    identity = {"external_user_id": "u2", "user_hash": _sign("s3cret", "u2")}
    payload = {"id": "c1", "name": "New"}
    _post(api_client, org, **identity, company=payload, company_hash="forged")
    company.refresh_from_db()
    assert company.name == "Old"
    _post(
        api_client, org, **identity,
        company=payload, company_hash=_sign("s3cret", "company\nc1\nNew\n"),
    )
    company.refresh_from_db()
    assert company.name == "New"


@pytest.mark.parametrize(
    "forged",
    [
        {"id": "c1", "name": "Forged", "domain": "real.io"},
        {"id": "c1", "name": "Real", "domain": "forged.io"},
        {"id": "c1", "name": "Real"},
    ],
)
def test_company_hash_cant_be_replayed_with_another_name_or_domain(api_client, org, forged):
    company = CompanyFactory(organization=org, external_id="c1", name="Old", domain="")
    other = CompanyFactory(organization=org, external_id="other")
    contact = ContactFactory(organization=org, external_id="u2", company=other)
    res = _post(
        api_client, org,
        external_user_id="u2", user_hash=_sign("s3cret", "u2"),
        company=forged, company_hash=_sign("s3cret", "company\nc1\nReal\nreal.io"),
    )
    assert res.status_code == 201
    company.refresh_from_db()
    contact.refresh_from_db()
    assert (company.name, company.domain) == ("Old", "")
    assert contact.company == other  # Unsigned, so a contact with a company stays put.


def test_signed_traits_only_apply_to_a_new_company(api_client, org):
    CompanyAttributeDef.objects.create(
        organization=org, key="tier", label="Tier", type="string"
    )
    company = CompanyFactory(
        organization=org, external_id="c1", name="N", attributes={"tier": "gold"}
    )
    identity = {"external_user_id": "u2", "user_hash": _sign("s3cret", "u2")}
    _post(
        api_client, org, **identity,
        company={"id": "c1", "name": "N", "traits": {"tier": "free"}},
        company_hash=_sign("s3cret", "company\nc1\nN\n"),
    )
    company.refresh_from_db()
    assert company.attributes == {"tier": "gold"}
    _post(
        api_client, org, **identity,
        company={"id": "c2", "name": "N", "traits": {"tier": "free"}},
        company_hash=_sign("s3cret", "company\nc2\nN\n"),
    )
    assert Company.objects.get(organization=org, external_id="c2").attributes == {"tier": "free"}


@pytest.mark.parametrize(
    "external_user_id", [True, 1.5, 2**63, "x" * 256, "\ud800", ["x"], {"a": 1}]
)
def test_malformed_external_id_is_refused_before_touching_the_session(api_client, org, external_user_id):
    # Raw JSON: DRF's test renderer can't encode the lone surrogates a real
    # request can carry as "\ud800" escapes.
    raw = {
        "data": json.dumps({"external_user_id": external_user_id, "user_hash": "x"}),
        "content_type": "application/json",
    }
    session = WidgetSession.objects.create(organization=org, email="a@x.io", name="A")
    res = api_client.patch(
        URL, **raw,
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=str(session.id),
    )
    assert res.status_code == 400
    session.refresh_from_db()
    assert (session.email, session.name) == ("a@x.io", "A")
    assert api_client.post(URL, **raw, HTTP_X_WIDGET_TOKEN=str(org.api_token)).status_code == 400
    assert WidgetSession.objects.filter(organization=org).count() == 1


# Invalid means ignored, never a 400. See test_widget_identity.py for the rest:
# bad-shape hashes, non-text names and emails, deep nesting.
BAD_HASHES = [1, 1.5, True, ["x"], {"a": 1}, "é", "\ud800", "x" * 129]


@pytest.mark.parametrize("bad", BAD_HASHES)
def test_bad_shape_user_hash_is_a_wrong_hash_on_find_or_create(api_client, org, bad):
    raw = json.dumps({"external_user_id": "u1", "user_hash": bad})
    res = api_client.post(
        URL, raw, content_type="application/json", HTTP_X_WIDGET_TOKEN=str(org.api_token)
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "company",
    [
        {"id": "\ud800", "name": "C"},
        {"id": "c1", "name": "\ud800"},
        {"id": "c1", "name": "C", "domain": "\ud800"},
    ],
)
def test_lone_surrogate_in_a_signed_company_is_ignored_not_raised(api_client, org, company):
    # ``company`` isn't an identity field: as with any invalid payload, the
    # widget goes on and the value counts as unsigned.
    body = {
        "external_user_id": "u2",
        "user_hash": _sign("s3cret", "u2"),
        "company": company,
        "company_hash": "a" * 64,
    }
    res = api_client.post(
        URL, json.dumps(body), content_type="application/json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
    )
    assert res.status_code == 201
    assert not Company.objects.filter(organization=org).exclude(name="C").exists()


@pytest.mark.parametrize("prefix", ["email:", "company\n"])
def test_external_id_that_could_double_as_another_hash_is_refused(api_client, org, prefix):
    external_id = f"{prefix}alice@startup.com"
    res = _post(
        api_client, org,
        external_user_id=external_id, user_hash=_sign("s3cret", external_id),
    )
    assert res.status_code == 400
    assert not Contact.objects.filter(organization=org).exists()
    assert not WidgetSession.objects.filter(organization=org).exists()


def test_email_hash_cant_be_replayed_as_a_user_hash(api_client, org):
    email_hash = _sign("s3cret", "email:alice@startup.com")
    res = _post(
        api_client, org, external_user_id="email:alice@startup.com", user_hash=email_hash
    )
    assert res.status_code == 400


@pytest.mark.parametrize("resume_by", ["session_id", "external_user_id"])
def test_resume_writes_only_its_own_fields(api_client, org, resume_by):
    """A full save would restore personal data wiped by a concurrent anonymization."""
    session = WidgetSession.objects.create(
        organization=org, external_user_id="u1", name="", email=""
    )
    body = {"session_id": str(session.id)} if resume_by == "session_id" else {}
    with CaptureQueriesContext(connection) as queries:
        res = _post(
            api_client, org, external_user_id="u1", user_hash=_sign("s3cret", "u1"),
            name="Alice", **body,
        )
    assert res.status_code == 200
    updates = [
        query["sql"]
        for query in queries
        if query["sql"].startswith('UPDATE "tickets_widgetsession"')
    ]
    assert updates
    for sql in updates:
        assert '"external_user_id"' not in sql.split(" WHERE ")[0]
        assert '"email_verified_at"' not in sql.split(" WHERE ")[0]


def test_contact_nudge_links_the_tickets_already_opened(api_client, org):
    session_id = _post(api_client, org).data["session_id"]
    api_client.post(
        "/api/v1/tickets/widget_message/", {"body": "Help"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=session_id,
    )
    ticket = Ticket.objects.get(widget_session_id=session_id)
    assert ticket.contact is None
    api_client.patch(
        URL, {"email": "bob@x.io"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=session_id,
    )
    ticket.refresh_from_db()
    assert ticket.contact.email == "bob@x.io"


def test_linking_leaves_a_ticket_with_a_contact_alone(api_client, org):
    other = ContactFactory(organization=org)
    session_id = _post(api_client, org).data["session_id"]
    ticket = TicketFactory(organization=org, widget_session_id=session_id, contact=other)
    api_client.patch(
        URL, {"email": "bob@x.io"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=session_id,
    )
    ticket.refresh_from_db()
    assert ticket.contact == other


def test_patch_changing_the_email_clears_its_verification(api_client, org):
    res = _post(
        api_client, org,
        email="alice@x.io", email_hash=_sign("s3cret", "email:alice@x.io"),
    )
    session_id = res.data["session_id"]
    api_client.patch(
        URL, {"email": "ALICE@x.io"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=session_id,
    )
    assert WidgetSession.objects.get(id=session_id).email_verified_at is not None
    api_client.patch(
        URL, {"email": "other@x.io"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token), HTTP_X_WIDGET_SESSION=session_id,
    )
    assert WidgetSession.objects.get(id=session_id).email_verified_at is None


@pytest.mark.parametrize("error", [IntegrityError, OperationalError, DatabaseError])
def test_database_error_never_breaks_widget_init(api_client, org, error):
    with mock.patch(
        "apps.tickets.views.resolve_contact_for_widget_session", side_effect=error
    ):
        assert _post(api_client, org, email="a@x.io").status_code == 201


def test_database_error_linking_tickets_never_breaks_widget_init(api_client, org):
    with mock.patch(
        "apps.tickets.views.Ticket.objects.filter", side_effect=OperationalError
    ):
        assert _post(api_client, org, email="a@x.io").status_code == 201


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

The test file also covers what real clients send (`TestRealClientPayloads`): an empty body, a stored `session_id` alone, null in every field on POST and PATCH, an email that passes the widget's check but isn't valid, a numeric user id with and without its hash, and a stored `session_id` that isn't a UUID. Also a deeply nested `name` (100,000 levels), and an attachment as first message (with `InMemoryStorage`, tests have no object storage).

**Step 2:** FAIL.

**Step 3: Implement**

Import at the top of `views.py`:

```python
from apps.contacts.services import (
    resolve_contact_for_email,
    resolve_contact_for_widget_session,
)
```

Only `external_user_id` is refused (400) before the session is touched. Everything else follows the design: invalid means ignored, so a host page that gets a field wrong doesn't stop the widget. Real clients set the limits:

- Null means absent, on every field. Direct integrations can send it, and PATCH already treated it that way.
- A badly shaped `email_hash` or `company_hash` (wrong type, over 128 characters, non-ASCII, on which `hmac.compare_digest` raises `TypeError`) reads as `""`: the value stays unsigned.
- A badly shaped `user_hash` behaves like a wrong hash: ignored when resuming an anonymous session, 403 on find-or-create. It reads as a value no signature can equal rather than `""`, which would pass for an id sent without a hash.
- `name`: a number becomes text, and a long value is cut to the column. Anything else that isn't text (a boolean, which would stick since a resume only fills a blank name, a list, a value Postgres can't store) reads as absent.
- `email` is checked as text, not as an email. The contact nudge only checks for an `@` and ignores the response, so a 400 would silently lose the name sent with `a@b`, and `init()` would fail on whatever a host page passes. It's stored as before, and the identity service ignores what isn't a valid email. A non-string, a value Postgres can't store or one over 254 characters reads as absent: a cut email would be somebody else's.
- `session_id`: a non-string counts as absent, before any `str()` overflows the stack on a deeply nested list.
- `traits` and `company`: anything but an object reads as absent. The service looks inside the object.
- `external_user_id` also accepts an integer, as plain JavaScript can pass `init({ user: { id: 42 } })`. It's read as its decimal string, which the HMAC covers. The same goes for `company.id`.

`external_user_id` isn't trimmed, since the HMAC covers its exact value. An id starting with `email:` or `company\n` is refused (400), so a `user_hash` can never double as an `email_hash` or `company_hash`: otherwise a page holding a valid `email_hash` could present it as the `user_hash` of the user `email:<address>`, and a host app whose users choose their id could be made to sign an `email_hash` by accident. `Organization.verify_user_hash` refuses those prefixes itself (`RESERVED_EXTERNAL_ID_PREFIXES` lives in `apps/organizations/models.py`), so that holds for every caller, and the serializer and `widget_tickets` keep their 400. Put this serializer in `apps/tickets/serializers.py`:

```python
class StrictCharField(serializers.CharField):
    """A CharField that refuses non-strings instead of coercing numbers."""

    def run_validation(self, data=empty):
        # Before the parent's str(data), a RecursionError on a deeply nested list.
        if data is not empty and data is not None and not isinstance(data, str):
            self.fail("invalid")
        return super().run_validation(data)


class WidgetHashField(serializers.Field):
    def __init__(self, *, bad_shape: str = "", **kwargs):
        self.bad_shape = bad_shape
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        if isinstance(data, str) and len(data) <= 128 and data.isascii():
            return data
        return self.bad_shape


class WidgetNameField(serializers.Field):
    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            data = str(data)
        if not isinstance(data, str) or not is_storable(data):
            return None
        return data.strip()[: WidgetSession._meta.get_field("name").max_length]


class WidgetEmailField(serializers.Field):
    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, str) or not is_storable(data):
            return None
        email = data.strip()
        if len(email) > WidgetSession._meta.get_field("email").max_length:
            return None
        return email


class WidgetObjectField(serializers.Field):
    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        return data if isinstance(data, dict) else None


class WidgetExternalIdField(StrictCharField):
    def __init__(self, **kwargs):
        super().__init__(
            required=False, allow_null=True, allow_blank=True, max_length=255,
            trim_whitespace=False, **kwargs,
        )

    def run_validation(self, data=empty):
        if type(data) is int and abs(data) < 2**63:
            data = str(data)
        return super().run_validation(data)


# A value no signature can equal: a digest is hexadecimal.
BAD_SHAPE_USER_HASH = "invalid"


class WidgetIdentitySerializer(serializers.Serializer):
    name = WidgetNameField()
    email = WidgetEmailField()
    external_user_id = WidgetExternalIdField()
    user_hash = WidgetHashField(bad_shape=BAD_SHAPE_USER_HASH)
    email_hash = WidgetHashField()
    company_hash = WidgetHashField()
    traits = WidgetObjectField()
    company = WidgetObjectField()

    def validate_external_user_id(self, value: str | None) -> str | None:
        # DRF calls this with None too.
        if value and value.startswith(RESERVED_EXTERNAL_ID_PREFIXES):
            raise serializers.ValidationError("This prefix is reserved.")
        return value
```

In `widget_session` (POST and PATCH), right after the token check, run the serializer and read `name`, `email`, `external_user_id` and the hashes from its `validated_data` (null becomes `""` on POST, and leaves the field alone on PATCH): `request.data` would give the untrimmed values and null. A `session_id` that isn't a UUID raises Django's `ValidationError` rather than `ValueError`: catch it at both lookups, so it starts a new session on POST and is a 401 in the `X-Widget-Session` header. The ticket history endpoint (`verify_user_hash` at ~391 in `views.py`) refuses the same prefixes with a 400.

Both resume paths of `widget_session` (the `session.save()` calls at ~680 and ~710) go through one helper, `_record_session_resume(org, session, name, email, email_hash)`, which writes `last_seen_at`, `updated_at` and only the fields it actually fills. A different email (compared lowercased and stripped) fills a blank one, and replaces it on an identified session, or on any session if `email_hash` signs it: an anonymous session otherwise keeps its first email. Whenever the email changes `email_verified_at` is cleared, and the service sets it again if it can. A full save writes the whole row as it was read, which restores the personal data a concurrent anonymization just wiped, and so would listing `name` and `email` unconditionally. PATCH likewise writes only the fields it was given.

In the PATCH branch, when the email actually changes (compare lowercased, stripped values), also set `session.email_verified_at = None` and add it to the session's `update_fields`: the proof was about the previous email.

Helper next to `_get_widget_session`:

```python
def _company_hash_is_valid(org, company, company_hash) -> bool:
    if not company_hash or not isinstance(company, dict):
        return False
    company_id = company.get("id")
    # Same values the service accepts as an id, without str() on a huge integer.
    if type(company_id) is int and abs(company_id) < 2**63:
        company_id = str(company_id)
    return org.verify_company_hash(
        company_id, company.get("name"), company.get("domain"), company_hash
    )


def _contact_claims(identity) -> dict:
    """Pick from the validated payload what ``_link_session_contact`` takes."""
    keys = ("email_hash", "company_hash", "traits", "company")
    return {key: identity.get(key) for key in keys}


def _link_session_contact(
    org, session, *, email_hash=None, company_hash=None, traits=None, company=None
) -> None:
    """Resolve the session's contact from the widget init payload.

    All of it is validated ``WidgetIdentitySerializer`` data. ``email_hash`` and
    ``company_hash`` are optional: an invalid one is ignored (the value stays
    unsigned) so a misconfigured host app never breaks the widget. For the same
    reason a database error (a conflict the service's retry couldn't settle, a
    deadlock, a lock timeout) is logged, and the session goes on without a contact
    until the next init.
    """
    email_verified = bool(
        session.email and email_hash and org.verify_email_hash(session.email, email_hash)
    )
    previous_contact_id = session.contact_id
    try:
        # Together: the tickets only get linked when the contact changes, so a
        # contact committed without them would leave them unlinked for good.
        with transaction.atomic():
            resolve_contact_for_widget_session(
                session,
                email_verified=email_verified,
                traits=traits,
                company=company,
                company_verified=_company_hash_is_valid(org, company, company_hash),
            )
            # The normal flow is first message, then contact nudge: tickets opened
            # before the session had a contact would otherwise never get one. Only
            # then: on any other visit, a ticket without a contact is one an agent
            # cleared.
            if session.contact_id and session.contact_id != previous_contact_id:
                Ticket.objects.filter(
                    organization=org, widget_session=session, contact__isnull=True
                ).update(contact_id=session.contact_id)
    except DatabaseError:
        session.contact_id = previous_contact_id
        logger.exception("Could not link widget session %s to a contact", session.pk)
```

Import `DatabaseError` and `transaction` from `django.db` in `views.py`. Catching it is safe because `ATOMIC_REQUESTS` is off: there's no request transaction for the error to break.

A valid `company_hash` proves the `id`, `name` and `domain` of the payload (`company_verified=True`), not its `traits`: the service updates the name and domain of an existing company and may move the contact, and applies `traits` to a company it creates only (design rule 4).

`widget_session` splits into `_update_session` (PATCH) and `_create_or_resume_session` (POST). Both call `_link_session_contact(org, session, **_contact_claims(identity))` before each `return Response(WidgetSessionSerializer(session).data …)`.

On POST, only a valid `user_hash` gives access to an identified session. The session the widget stored decides what happens (design rule 8):

| Stored session | Payload | Result |
|---|---|---|
| Anonymous | no valid hash (wrong, badly shaped, absent, or no widget secret) | Resumed. The id sent is ignored. |
| Anonymous | valid hash | Login: the identified session is found or created and returned, and takes the conversations. |
| Identified | valid hash | Find-or-create on the id sent: the user's own session, or the session of another user who logged in since. |
| Identified | no hash, with or without an id | Logout: a new anonymous session. The stored session and its contact aren't touched. |
| Identified | wrong or badly shaped hash | 403, as without a stored session. |

The login runs `_move_conversation_to_identified_session(org, anonymous, identified)` after the contact is linked, in a transaction that locks the anonymous session then its tickets, all filtered on `organization=org`. Each ticket gets `widget_session`, `external_user_id`, `contact` (the identified contact, or its own if the session has none: anonymized, or a database error while linking) and `context_metadata["pre_login_anonymous"] = True` with `context_metadata["pre_login_session_hash"]`, the SHA-256 hex digest of the anonymous session's id (a bearer token, which agents could otherwise read); `bulk_update` leaves `updated_at` alone. The session's `TicketMessage`s get `widget_session`, and the move is logged at info level with digests and counts only. A retry finds nothing left to move. A message being posted meanwhile goes through `_create_user_message`, which takes the ticket's current session under its row lock. The session's `PATCH` doesn't fill the requester of a moved ticket. A database error isn't caught there, unlike in `_link_session_contact`: the widget only stores the id of a successful response, so it keeps the anonymous id and its next init retries.

`get_or_create` settles the race between two first requests since Task 8's migration `tickets/0011` added the unique constraint: the loser's insert fails, and it reads the winner's row.

Every `Ticket.objects.create(...)` with `widget_session=session` (in `widget_message` and `widget_message_attachment`; `widget_upload_attachment` never creates a ticket) gets `contact_id=session.contact_id,`.

In `widget_submit`, after `serializer.save(...)`:

```python
        if ticket.requester_email:
            try:
                contact = resolve_contact_for_email(
                    organization, ticket.requester_email, name=ticket.requester_name
                )
                if contact is not None:
                    ticket.contact = contact
                    ticket.save(update_fields=["contact"])
            except DatabaseError:
                # The ticket exists: failing here would lose its notifications.
                logger.exception("Could not link ticket %s to a contact", ticket.pk)
```

**Step 4:** `python -m pytest tests/contacts tests/tickets -q` → PASS (existing widget tests stay green). **Step 5: Commit** — `feat(backend): resolve contacts from the widget`

---

### Task 8: Back-fill migration

**Files:**
- Create: `backend/apps/contacts/backfill.py`, `backend/apps/contacts/migrations/0004_backfill_contacts.py` (`0003_contact_declared_email` is the schema migration added by the identity review)
- Test: `backend/tests/contacts/test_backfill.py`

The function takes `(apps, schema_editor)` so it can be unit-tested with the real registry.

The back-fill follows `tickets/0011_one_widget_session_per_external_user`, which merges duplicate sessions (`apps/tickets/session_merge.py`: the oldest stays, the others' tickets and messages move to it, and it takes the name, email with its proof, contact and `last_seen_at` of the most recently seen session having them) and then adds the partial unique constraint on `(organization, external_user_id)`. It must depend on that migration, so it only sees merged sessions. That migration runs `SET CONSTRAINTS ALL IMMEDIATE` between the merge and the constraint: otherwise Postgres refuses to build the index on a table with pending deferred foreign key checks.

An email that normalizes to nothing is no email: `for_email` would otherwise match an arbitrary blank-email contact (typically an identified one), so such a row is skipped and stays without a contact.

Nothing in existing data is proven: emails of identified sessions and tickets go to `declared_email`, never to `email`, and nothing is marked verified. Otherwise the back-fill would hand out exactly the squatting the service now refuses.

A ticket's `external_user_id` isn't proof, since `widget_submit` takes any value: it only counts if a session of the same organization holds it (design section 4).

**Implementation:** this section doesn't keep a copy of the code. It's in `backend/apps/contacts/backfill.py`, whose docstring states the rules, with `backend/apps/contacts/migrations/0004_backfill_contacts.py` calling it (depending on `contacts/0003_contact_declared_email` and `tickets/0011_one_widget_session_per_external_user`), and `backend/tests/contacts/test_backfill.py` for the cases.

**Commit** — `feat(backend): back-fill contacts from existing tickets`

---

### Task 9: Contact serializers and viewset

**Files:**
- Create: `backend/apps/contacts/serializers.py`, `views.py`, `permissions.py`, `summary.py`
- Modify: `backend/config/api_urls.py`
- Test: `backend/tests/contacts/test_contacts_api.py`

Endpoints: `GET/POST /api/v1/contacts/`, `GET/PATCH/DELETE /api/v1/contacts/{id}/` (DELETE admin only), `GET /contacts/{id}/tickets/`, `GET/POST /contacts/{id}/notes/`. Query params: `search` (name, email, declared_email, external_id), `company`, `email_verified=true|false`, `last_seen_after`, `last_seen_before` (ISO datetimes; invalid values ignored), `attr.<key>=<value>`, `page`, `page_size` (≤ 100).

**Step 1: Failing tests**

```python
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.contacts.models import Contact
from apps.contacts.views import ContactViewSet
from apps.tickets.models import WidgetSession
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


def test_declared_email_is_read_only_and_searchable(authenticated_client, organization):
    contact = ContactFactory(organization=organization, email="", declared_email="d@x.io")
    res = authenticated_client.patch(
        f"{URL}{contact.id}/", {"declared_email": "other@x.io"}, format="json"
    )
    assert res.data["declared_email"] == "d@x.io"
    contact.refresh_from_db()
    assert contact.declared_email == "d@x.io"
    rows = authenticated_client.get(URL, {"search": "d@x.io"}).data["results"]
    assert [c["id"] for c in rows] == [str(contact.id)]


def test_ordering_keeps_never_seen_contacts_last(authenticated_client, organization):
    now = timezone.now()
    never = ContactFactory(organization=organization, last_seen_at=None)
    old = ContactFactory(organization=organization, last_seen_at=now - timedelta(days=1))
    new = ContactFactory(organization=organization, last_seen_at=now)
    for ordering, expected in (
        ("-last_seen_at", [new, old, never]),
        ("last_seen_at", [old, new, never]),
    ):
        rows = authenticated_client.get(URL, {"ordering": ordering}).data["results"]
        assert [c["id"] for c in rows] == [str(c.id) for c in expected]


def test_changing_email_clears_verification(authenticated_client, organization):
    contact = ContactFactory(organization=organization, email_verified_at=timezone.now())
    authenticated_client.patch(f"{URL}{contact.id}/", {"email": "other@x.io"}, format="json")
    contact.refresh_from_db()
    assert contact.email_verified_at is None


def test_agent_patch_on_an_anonymized_contact_is_409(authenticated_client, organization):
    contact = ContactFactory(organization=organization, name="Gone", is_anonymized=True)
    res = authenticated_client.patch(f"{URL}{contact.id}/", {"name": "Alice"}, format="json")
    assert res.status_code == 409
    contact.refresh_from_db()
    assert contact.name == "Gone"


def test_admin_patch_on_an_anonymized_contact_is_409(admin_client, organization):
    contact = ContactFactory(organization=organization, is_anonymized=True)
    res = admin_client.patch(f"{URL}{contact.id}/", {"name": "Alice"}, format="json")
    assert res.status_code == 409


def _stale(monkeypatch, contact):
    """Make the view work from ``contact`` as it was read before later changes."""
    monkeypatch.setattr(ContactViewSet, "get_object", lambda self: contact)


def test_patch_read_before_an_anonymization_cant_undo_it(
    authenticated_client, organization, monkeypatch
):
    contact = ContactFactory(organization=organization, name="Alice", phone="+33")
    _stale(monkeypatch, contact)
    Contact.objects.filter(pk=contact.pk).update(
        name="Anonymized contact", phone="", is_anonymized=True
    )
    res = authenticated_client.patch(f"{URL}{contact.id}/", {"job_title": "CTO"}, format="json")
    assert res.status_code == 409
    row = Contact.objects.get(pk=contact.pk)
    assert (row.name, row.phone, row.job_title) == ("Anonymized contact", "", "")


def test_patch_writes_only_its_fields_and_merges_on_the_current_row(
    authenticated_client, organization, monkeypatch
):
    ContactAttributeDefFactory(organization=organization, key="plan", type="string")
    ContactAttributeDefFactory(organization=organization, key="role", type="string")
    contact = ContactFactory(organization=organization, phone="+33", attributes={})
    _stale(monkeypatch, contact)
    Contact.objects.filter(pk=contact.pk).update(phone="+44", attributes={"plan": "pro"})
    res = authenticated_client.patch(
        f"{URL}{contact.id}/", {"attributes": {"role": "cto"}}, format="json"
    )
    assert res.status_code == 200
    row = Contact.objects.get(pk=contact.pk)
    assert row.phone == "+44"
    assert row.attributes == {"plan": "pro", "role": "cto"}


def test_patch_response_keeps_the_ticket_counts(authenticated_client, organization):
    contact = ContactFactory(organization=organization)
    TicketFactory(organization=organization, contact=contact, status="open")
    res = authenticated_client.patch(f"{URL}{contact.id}/", {"name": "A"}, format="json")
    assert (res.data["tickets_count"], res.data["open_tickets_count"]) == (1, 1)


def test_delete_locks_the_contact_before_touching_its_sessions(admin_client, organization):
    contact = ContactFactory(organization=organization)
    WidgetSession.objects.create(organization=organization, contact=contact)
    with CaptureQueriesContext(connection) as queries:
        assert admin_client.delete(f"{URL}{contact.id}/").status_code == 204
    sql = [query["sql"] for query in queries]
    lock = next(
        i for i, q in enumerate(sql)
        if q.startswith('SELECT') and '"contacts_contact"' in q and "FOR UPDATE" in q
    )
    first_write = next(
        i for i, q in enumerate(sql)
        if q.startswith(('UPDATE "tickets_widgetsession"', 'DELETE FROM "contacts_contact"'))
    )
    assert lock < first_write


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
            "id", "display_name", "name", "email", "email_verified", "declared_email",
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
            "email_verified_at", "declared_email", "external_id", "phone", "avatar_url", "job_title",
            "locale", "timezone", "company", "company_detail", "first_seen_at",
            "last_seen_at", "last_contacted_at", "is_unsubscribed", "is_anonymized",
            "attributes", "tickets_count", "open_tickets_count", "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "email_verified_at", "declared_email", "first_seen_at", "last_seen_at",
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
        return clean_attributes(defs, value or {})

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
        return attrs

    def update(self, instance, validated_data):
        """Apply a PATCH to ``instance``, the row ``perform_update`` locked.

        What depends on the stored values is decided here rather than during
        validation, which ran before the lock. Only the fields sent are written.
        """
        if "attributes" in validated_data:
            stored = instance.attributes if isinstance(instance.attributes, dict) else {}
            validated_data["attributes"] = {**stored, **validated_data["attributes"]}
        if "email" in validated_data and validated_data["email"] != instance.email:
            validated_data["email_verified_at"] = None
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*validated_data, "updated_at"])
        return instance


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
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import get_active_org
from apps.tickets.models import Ticket

from .models import Contact
from .permissions import require_org_admin
from .serializers import ContactNoteSerializer, ContactSerializer, ContactTicketSerializer

OPEN_STATUSES = [Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING]


class ContactAnonymized(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This contact has been anonymized."
    default_code = "contact_anonymized"


class DirectoryPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_dt(value):
    try:
        return parse_datetime(value or "")
    except ValueError:
        return None


class NullsLastOrderingFilter(OrderingFilter):
    """``?ordering=`` in either direction, with NULLs last (Postgres puts them
    first on DESC, which would list never-seen contacts on top of the list).
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        return queryset.order_by(
            *(
                F(field[1:]).desc(nulls_last=True)
                if field.startswith("-")
                else F(field).asc(nulls_last=True)
                for field in ordering
            ),
            "id",
        )


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
    filter_backends = [SearchFilter, NullsLastOrderingFilter]
    search_fields = ["name", "email", "declared_email", "external_id"]
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

    def perform_update(self, serializer):
        # Same row lock as the identity service and the anonymization, so a PATCH
        # read before an anonymization can't write personal data back over it.
        # Plain manager: the aggregates of get_queryset() can't be locked.
        with transaction.atomic():
            contact = (
                Contact.objects.select_for_update(no_key=True)
                .filter(pk=serializer.instance.pk)
                .first()
            )
            if contact is None:
                raise NotFound
            if contact.is_anonymized:
                raise ContactAnonymized
            serializer.instance = contact
            serializer.save()
        # The response needs the ticket counts.
        serializer.instance = self.get_queryset().get(pk=contact.pk)

    def perform_destroy(self, instance):
        require_org_admin(self.request.user)
        # Lock order everywhere: contact, then sessions. The delete nulls the
        # sessions' FK before removing the row, so taking the contact's lock only
        # then could deadlock with a session being resolved.
        with transaction.atomic():
            contact = Contact.objects.select_for_update().filter(pk=instance.pk).first()
            if contact is not None:
                contact.delete()

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

`perform_update` and `perform_destroy` are on `ContactViewSet` only: `OrgScopedMixin.perform_destroy` stays as is for companies. `update` isn't inherited from `ModelSerializer` because its full `save()` would restore every other field as read.

An invalid `company` UUID must not 500: validate with `uuid.UUID(...)` and ignore on `ValueError` (add a test). Register `router.register(r"contacts", ContactViewSet, basename="contact")`.

**As implemented** (`backend/apps/contacts/`, which supersedes the samples above where they differ):

- `external_id` is read-only, so the uniqueness check only covers `email`.
- The PATCH is `ContactViewSet.update`, not `perform_update`: it validates on the locked row, so an anonymized contact answers 409 before any 400, and the email check sees what was committed while it waited. PUT isn't offered.
- An `IntegrityError` on create or PATCH is a 400. `company`'s choices are scoped to the organization, instead of `validate_company`.
- `attribute_filters` became `filter_by_attributes(queryset, params)`: keys match `[A-Za-z_][A-Za-z0-9_]{0,63}` without a double underscore and go through `KeyTransform`, since `attributes__has_key` is a lookup and not a key. A value also matches its typed reading (`3`, `true`).
- `_parse_dt` converts to UTC: Postgres refuses offsets beyond ±15:59. Filters and search only apply to the list, through `filter_queryset`.
- The default order is on the viewset (`ordering`): the counts' GROUP BY makes Django drop `Meta.ordering`.
- `timeline_tickets()` loads what `ContactTicketSerializer` needs and annotates `message_count`, which is one COUNT per ticket in `TicketListSerializer`.
- `IsOrganizationStaff` refuses end users and users without an active organization. A note on an anonymized contact is a 409.

**Step 4:** PASS. **Step 5: Commit** — `feat(backend): contacts API`

---

### Task 10: Company viewset

**Files:**
- Modify: `backend/apps/contacts/serializers.py`, `views.py`, `backend/config/api_urls.py`
- Test: `backend/tests/contacts/test_companies_api.py`

**Step 1: Failing tests** (follow `test_contacts_api.py`): scoped list with `contacts_count` and `open_tickets_count`; search by name/domain; create lowercases domain, duplicate domain → 400, malformed domain (`"not a domain"`, `"https://x.io/"`) → 400; attributes validated against `CompanyAttributeDef` and merged on PATCH; `GET /companies/{id}/contacts/` lists its contacts; `GET /companies/{id}/tickets/` lists tickets of all its contacts; DELETE admin-only; other org → 404.

**Step 2:** FAIL.

**Step 3: Implement** `CompanySerializer` (all model fields + read-only `contacts_count`, `open_tickets_count`; `validate_domain` strips, lowercases and format-checks with `django.core.validators.DomainNameValidator` (blank stays allowed); `validate` enforces per-org uniqueness of `domain` and `external_id`; `validate_attributes` with `CompanyAttributeDef`) and:

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
        return filter_by_attributes(qs, self.request.query_params)

    @action(detail=True, methods=["get"])
    def contacts(self, request, pk=None):
        contacts = self.get_object().contacts.order_by("name")[:200]
        serializer = ContactSerializer(
            contacts, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        tickets = timeline_tickets(Ticket.objects.filter(contact__company=self.get_object()))
        return Response(ContactTicketSerializer(tickets, many=True).data)
```

Register `companies`.

**As built, where it differs from the above:** `external_id` is read-only, as on a contact, so `validate` only checks `domain`; PATCH is locked and writes only what changed; no PUT; explicit `filter_backends`; ordering by name then id; attribute filters on the list only; the `contacts` action reuses the contact counts; both actions and the counts leave out rows of another organization; a final dot on a domain is dropped.

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
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.contacts.gdpr import REMOVED_BODY, anonymize_contact
from apps.contacts.services import resolve_contact_for_widget_session
from apps.tickets.models import TicketMessage, WidgetSession
from tests.factories import (
    ContactFactory,
    ContactNoteFactory,
    TicketFactory,
    TicketMessageFactory,
)

pytestmark = pytest.mark.django_db


def test_anonymize_scrubs_contact_and_user_messages(organization, agent):
    contact = ContactFactory(
        organization=organization, name="Alice", email="alice@x.io",
        declared_email="other@x.io", external_id="u1", phone="+33",
        attributes={"plan": "pro"},
    )
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, email="alice@x.io",
        name="Alice", external_user_id="u1",
    )
    ticket = TicketFactory(
        organization=organization, contact=contact, requester=None, widget_session=session,
        requester_email="alice@x.io", requester_name="Alice", external_user_id="u1",
        context_url="https://app/x?token=1",
        context_metadata={"browser": "Chrome", "url_params": {"t": 1}},
    )
    user_msg = TicketMessageFactory(
        ticket=ticket, author=None, sender_type=TicketMessage.SenderType.USER, body="secret"
    )
    agent_msg = TicketMessageFactory(ticket=ticket, author=agent, body="reply")
    ContactNoteFactory(contact=contact, author=agent, body="Her husband is ill")

    anonymize_contact(contact)

    for obj in (contact, session, ticket, user_msg, agent_msg):
        obj.refresh_from_db()
    assert contact.is_anonymized
    assert contact.email.endswith("@example.invalid")
    assert (contact.name, contact.phone, contact.external_id) == ("Anonymized contact", "", "")
    assert contact.declared_email == ""
    assert contact.attributes == {}
    assert (session.email, session.name, session.external_user_id) == ("", "", "")
    assert session.contact is None
    assert ticket.widget_session is None
    assert ticket.requester_email == contact.email
    assert ticket.external_user_id == ""
    assert ticket.context_url == ""
    assert ticket.context_metadata == {"browser": "Chrome"}
    assert user_msg.body == REMOVED_BODY
    assert agent_msg.body == "reply"
    assert not contact.notes.exists()  # Free text: it can hold personal data.


def test_open_tab_cant_attach_new_data_to_the_anonymized_contact(api_client, organization):
    contact = ContactFactory(organization=organization, external_id="u1")
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, external_user_id="u1"
    )
    anonymize_contact(contact)
    session.refresh_from_db()
    assert resolve_contact_for_widget_session(session) is None
    api_client.post(
        "/api/v1/tickets/widget_message/", {"body": "Still here"}, format="json",
        HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        HTTP_X_WIDGET_SESSION=str(session.id),
    )
    assert session.tickets.count() == 1
    assert session.tickets.get().contact is None
    assert not contact.tickets.exists()


def test_open_tab_cant_add_messages_to_a_ticket_of_the_anonymized_contact(api_client, organization):
    # Both endpoints look the ticket up with ``widget_session=session``.
    contact = ContactFactory(organization=organization, external_id="u1")
    session = WidgetSession.objects.create(
        organization=organization, contact=contact, external_user_id="u1"
    )
    ticket = TicketFactory(organization=organization, contact=contact, widget_session=session)
    anonymize_contact(contact)
    headers = {
        "HTTP_X_WIDGET_TOKEN": str(organization.api_token),
        "HTTP_X_WIDGET_SESSION": str(session.id),
    }
    res = api_client.post(
        "/api/v1/tickets/widget_message/",
        {"body": "Still here", "ticket_id": str(ticket.id)}, format="json", **headers,
    )
    assert res.status_code == 404
    res = api_client.post(
        "/api/v1/tickets/widget_message_attachment/",
        {"ticket_id": str(ticket.id), "file": SimpleUploadedFile("a.txt", b"x")},
        format="multipart", **headers,
    )
    assert res.status_code == 404
    assert not ticket.messages.exists()


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

from .models import Contact

REMOVED_BODY = "[Content removed at the contact's request]"
KEPT_CONTEXT_KEYS = {"browser", "os", "language", "timezone", "screen_resolution"}


@transaction.atomic
def anonymize_contact(contact) -> None:
    """Irreversibly strip personal data while keeping ticket structure."""
    # Same row lock as the identity service, which checks ``is_anonymized`` under
    # it: without this, a widget session resolving at the same time could save
    # the personal data back over the anonymized row. Work on the row just read.
    contact = Contact.objects.select_for_update().get(pk=contact.pk)
    contact.email = f"anonymized-{uuid.uuid4().hex}@example.invalid"
    contact.declared_email = ""
    contact.name = "Anonymized contact"
    contact.phone = ""
    contact.external_id = ""
    contact.avatar_url = ""
    contact.job_title = ""
    contact.attributes = {}
    contact.email_verified_at = None
    contact.is_anonymized = True
    contact.save()

    # Free text written by agents, which can hold personal data about the contact.
    contact.notes.all().delete()
    # Unlinked as well, so an open tab can't attach new data to this contact.
    contact.sessions.update(
        email="", name="", external_user_id="", email_verified_at=None, contact=None
    )
    TicketMessage.objects.filter(
        ticket__contact=contact, sender_type=TicketMessage.SenderType.USER
    ).update(body=REMOVED_BODY)
    for ticket in contact.tickets.all():
        # Widget endpoints look a ticket up by session: this stops an open tab,
        # including one on a session since moved to another contact, adding to it.
        ticket.widget_session = None
        ticket.requester_email = contact.email
        ticket.requester_name = contact.name
        ticket.external_user_id = ""
        ticket.context_url = ""
        ticket.context_user_agent = ""
        ticket.context_metadata = {
            k: v for k, v in (ticket.context_metadata or {}).items() if k in KEPT_CONTEXT_KEYS
        }
        ticket.save(update_fields=[
            "widget_session", "requester_email", "requester_name", "external_user_id",
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

Add a `transaction=True` test next to `tests/contacts/test_services_concurrency.py`: while a second connection holds the contact's row, `anonymize_contact` blocks, and afterwards the row is anonymized.

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
- `build_contact_export(contact)` returns ZIP bytes with `contact.json` (profile including `declared_email`, attributes, notes), `tickets.json` (tickets + public replies + attachment metadata; an internal note's body must be absent), `tickets.csv` (header `reference,title,status,created_at,resolved_at`).
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

**Step 1: Failing tests** — `GET /api/v1/tickets/{id}/` returns `contact`, `contact_detail` (`id, display_name, email, email_verified, declared_email, company_detail`) and `sender_verified`; list rows include `contact_detail` and `sender_verified`; `PATCH {"contact": <other org contact id>}` → 400; `sender_verified`:
- is read-only;
- is true for a ticket of a session with `email_verified_at` set, and of a HMAC-identified session (`external_user_id` set), when the session's contact is the ticket's contact;
- is false for a ticket of an unverified anonymous session, for a session linked to another contact, for no contact, for a `widget_submit` ticket whose `requester_email` is a verified contact's address, and for a ticket with `context_metadata["pre_login_anonymous"]`: moved to an identified session at login, it was written before anyone proved who they are, and stays false for good, including on a session with a verified email;
- is null when there is no outside sender to verify: a ticket with source `agent` or `api`, even with a `requester_email`, and a ticket with no session and no `requester_email`.

`POST /api/v1/tickets/` by an agent stores source `agent` when the request names none (test it), and keeps a source it names.

`contact_detail.email_verified` only says the *contact* proved its email. A forged ticket can link to a verified contact (`widget_submit` and inbound email resolve from a declared address), so agents need `sender_verified` to know whether *this ticket's sender* proved anything.

**Step 3: Implement** — import `ContactSummarySerializer` from `apps.contacts.summary`; add `contact_detail = ContactSummarySerializer(source="contact", read_only=True)`, `sender_verified = serializers.SerializerMethodField()` and `"contact", "contact_detail", "sender_verified"` to both `fields`; `get_sender_verified` returns None if `ticket.source` is `agent` or `api` or the ticket has neither a session nor a `requester_email`, and otherwise `bool(session and ticket.contact_id and session.contact_id == ticket.contact_id and (session.email_verified_at or session.external_user_id) and not pre_login)` with `session = ticket.widget_session` and `metadata = ticket.context_metadata`, `pre_login = isinstance(metadata, dict) and metadata.get("pre_login_anonymous") is True` (the email channel adds the conversation link as a third way, and it doesn't override `pre_login`); the flag can also come from a widget's own `context`, which only marks that sender's own ticket as unverified; `KEPT_CONTEXT_KEYS` doesn't need it, since anonymizing clears the ticket's session and that alone reads as false; `sender_verified` is only meaningful for a ticket from a widget or email sender, so an agent's ticket is neither verified nor unverified. `Ticket.source` defaults to `widget` and `TicketViewSet.perform_create` doesn't set it, so agent-created tickets are currently stored as widget tickets: `perform_create` passes `source=serializer.validated_data.get("source", Ticket.Source.AGENT)`. Agent tickets created before this PR keep source `widget`, so one with a `requester_email` reads as an outside sender; `validate_contact` rejects contacts of another organization (compare with `self.instance.organization_id`, or the active org passed in context on create); add `"contact__company"` and `"widget_session"` to the queryset's `select_related`.

**Step 4:** full suite PASS. **Step 5: Commit** — `feat(backend): expose contact on tickets`

---

### Task 15: Widget forwards `email_hash`, `company_hash`, `traits`, `company`

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
  /** HMAC-SHA256(widget_secret, "email:" + lowercase email) — optional, proves the email. */
  emailHash?: string;
  /** Custom contact attributes (defined in Settings → Contact attributes). */
  traits?: Record<string, unknown>;
}

export interface ShowdeskCompany {
  id: string;
  name: string;
  domain?: string;
  traits?: Record<string, unknown>;
  /**
   * HMAC-SHA256(widget_secret, "company\n" + id + "\n" + name + "\n" + lowercase(domain)), with domain
   * empty if absent — optional, lets the payload update the company's name and domain. Doesn't cover traits.
   */
  hash?: string;
}
```

Add `company?: ShowdeskCompany;` to `ShowdeskConfig`; read `el.dataset["userEmailHash"]` in `buildUserFromDataAttrs`; in `createOrResumeSession` type `body` as `Record<string, unknown>` and add:

```ts
  if (config.user?.emailHash) body.email_hash = config.user.emailHash;
  if (config.user?.traits) body.traits = config.user.traits;
  if (config.company) {
    const { hash, ...company } = config.company;
    body.company = company;
    if (hash) body.company_hash = hash;
  }
```

Docs: `data-user-email-hash`, `init({ user: { emailHash, traits }, company: { …, hash } })`, a server-side snippet computing the three HMACs with their prefixes (`user_hash` over the id, `email_hash` over `"email:" + lowercase(email)`, `company.hash` over `"company\n" + id + "\n" + name + "\n" + lowercase(domain)`, with `domain` empty if absent, over the exact id and name sent to the widget, as UTF-8; an id, name or domain containing a newline never verifies). Docs also state:
- `user.traits` apply to HMAC-identified users and to proven anonymous sessions (design rule 5); `company` is honoured only for HMAC-identified users.
- `company.traits` aren't signed. They apply when the payload creates a company, signed or not, and never to an existing company: update those from the Companies API or the UI.
- What each signature unlocks: without `emailHash` an email stays declared; without `company.hash` a company can be created or linked once, never updated, and a contact is never moved. With it, the name and domain of an existing company are updated and the contact may be moved.
- External user ids starting with `email:` or `company\n` are refused, since those prefixes are reserved for the other two hashes.
- A numeric user or company id is accepted, and signed as its decimal string.

**`setUser()` must start a session again.** Today it only changes the local config, and identity reaches the backend on the next `init()`. So a single-page app that logs in without a reload gets no continuity until then: its conversation stays on the anonymous session, and its new tickets too. This task closes that gap: when `setUser()` receives an identity with a `hash`, it re-runs the session init with the stored id and that hash (the login of design rule 8), stores the session returned, and reloads the conversation list. Without a `hash` it starts no identified session. Document it, and test it by hand since the widget has no test runner: anonymous conversation, `setUser()` with a hash, then the same conversation continues without a reload.

**Commit** — `feat(widget): send signed email, signed company and traits`

---

### Task 16: Frontend types, API modules and hooks

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/contacts.ts`, `companies.ts`, `attributeDefs.ts`
- Create: `frontend/src/hooks/useContacts.ts`, `useCompanies.ts`, `useAttributeDefs.ts`
- Test: `frontend/src/api/__tests__/contacts.test.ts` (or next to existing hook tests in `frontend/src/hooks/__tests__/`)

Types: `Contact`, `ContactSummary`, `Company`, `CompanySummary`, `ContactNote`, `AttributeDef` (`type: "string" | "number" | "boolean" | "date" | "enum" | "url"`); `declared_email: string` on `Contact` and `ContactSummary`; add `contact: string | null; contact_detail: ContactSummary | null; sender_verified: boolean | null;` to both ticket types (null: no outside sender, see Task 14).

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
- Contacts table: avatar (initials fallback), name, email + `UnverifiedBadge` when the email is set and not verified, `declared_email` when set (always with `UnverifiedBadge`), company, last seen (relative), open tickets; row click → `/contacts/:id`.
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
- Left: avatar, inline-editable name, email + verified/unverified badge, read-only `declared_email` + unverified badge, phone, company link, external id (read-only, monospace), `AttributeEditor` (typed inputs per non-archived def: text, number, checkbox, date, select, url; saves `updateContact({ attributes: { [key]: value } })`); admin-only "Export data" (toast "Export queued — you will receive it by email") and "Anonymize" (confirm modal requiring the contact's email to be typed; hidden when `is_anonymized`).
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

When `ticket.contact_detail` exists: heading "Contact", name linking to `/contacts/:id`, email + `UnverifiedBadge`, `declared_email` + `UnverifiedBadge` when set, company line (logo, name, plan) linking to `/companies/:id`, "Other tickets: N" from `useContactTickets` excluding the current ticket. When `ticket.sender_verified === false`, show an "Unverified sender" hint on the card, even if the contact's email is verified: a forged ticket can link to a verified contact. Never show it when the value is null: an agent-created ticket (source `agent` or `api`, or no session and no inbound sender) has no sender to verify. When there's no `contact_detail`, keep the current requester rendering.

Test: the hint shows for `sender_verified: false` with a verified contact, and not for `sender_verified: true` or `null`.

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
7. Release notes, before deploying: count the rows the reserved prefixes now exclude, with `WidgetSession.objects.filter(external_user_id__startswith="email:").count()` and the same on `Ticket` (and `company\n` on both). Those sessions can't be resumed and get no contact, so check any non-zero count with the integrator concerned. Tell integrators that a `user_hash` is required on every init of an identified user: an init without one now counts as a logout and starts a new anonymous session.
8. Push `feat/contacts`; open a PR → `develop` titled `feat: contacts and companies` with summary, migration note (back-fill runs during the deploy migrate step), test instructions for the development environment, the `CONTRIBUTING.md` checklist, and the Claude Code attribution line.
9. Post-deploy, in the release notes: pods still running the old code keep writing rows without a contact after the back-fill migration. Once none is left, run `python manage.py backfill_contacts` once. It runs the same idempotent function, on the rows still unlinked and only there. Don't run it later: it would also link again a ticket whose contact an agent cleared.
10. `docker stop showdesk-test-pg showdesk-test-redis`.
