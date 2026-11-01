"""Tests for the contact identity service (design section 3)."""

from datetime import timedelta
from unittest import mock

import pytest
from django.db import IntegrityError, OperationalError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.contacts import services
from apps.contacts.models import (
    Company,
    CompanyAttributeDef,
    Contact,
    ContactAttributeDef,
)
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


def _deeply_nested(depth: int = 200_000) -> list:
    value: list = []
    for _ in range(depth):
        value = [value]
    return value


_IDENTITY_FIELDS = (
    "email",
    "email_verified_at",
    "declared_email",
    "external_id",
    "name",
    "attributes",
    "company_id",
)


def _identity(contact: Contact) -> dict:
    """Every identity-bearing field, re-read from the database."""
    return Contact.objects.filter(pk=contact.pk).values(*_IDENTITY_FIELDS)[0]


def _snapshot(contact: Contact) -> dict:
    """The whole footprint of a write: identity, seen dates and ``updated_at``."""
    return Contact.objects.filter(pk=contact.pk).values(
        *_IDENTITY_FIELDS, "first_seen_at", "last_seen_at", "updated_at"
    )[0]


def _updates(queries, table: str) -> list[str]:
    return [q["sql"] for q in queries if q["sql"].startswith(f'UPDATE "{table}"')]


def _plan_def(org):
    return ContactAttributeDef.objects.create(
        organization=org, key="plan", label="Plan", type="string"
    )


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

    def test_declared_name_is_not_written_on_an_existing_nameless_contact(self, org):
        existing = ContactFactory(organization=org, email="a@x.io", name="")
        resolve_contact_for_email(org, "a@x.io", name="Fake")
        existing.refresh_from_db()
        assert existing.name == ""

    def test_lookup_ignores_case_and_surrounding_spaces(self, org):
        existing = ContactFactory(organization=org, email="a@x.io")
        assert resolve_contact_for_email(org, "  A@X.IO ") == existing

    def test_does_not_cross_organizations(self, org):
        other = ContactFactory(email="a@x.io")
        contact = resolve_contact_for_email(org, "a@x.io")
        assert contact != other
        assert contact.organization == org

    def test_autolinks_company_by_domain(self, org):
        company = CompanyFactory(organization=org, domain="startup.com")
        assert resolve_contact_for_email(org, "bob@startup.com").company == company

    def test_never_autolinks_public_webmail(self, org):
        CompanyFactory(organization=org, domain="gmail.com")
        assert resolve_contact_for_email(org, "bob@gmail.com").company is None

    def test_does_not_autolink_a_company_of_another_organization(self, org):
        CompanyFactory(domain="startup.com")
        assert resolve_contact_for_email(org, "bob@startup.com").company is None

    def test_existing_email_only_contact_gets_its_missing_company(self, org):
        contact = ContactFactory(organization=org, email="bob@startup.com")
        company = CompanyFactory(organization=org, domain="startup.com")
        resolve_contact_for_email(org, "bob@startup.com")
        contact.refresh_from_db()
        assert contact.company == company

    def test_identified_contact_gets_no_company_until_its_email_is_proven(self, org):
        unproven = ContactFactory(
            organization=org, email="bob@startup.com", external_id="u1"
        )
        proven = ContactFactory(
            organization=org,
            email="eve@startup.com",
            external_id="u2",
            email_verified_at=timezone.now(),
        )
        company = CompanyFactory(organization=org, domain="startup.com")
        resolve_contact_for_email(org, unproven.email)
        resolve_contact_for_email(org, proven.email)
        unproven.refresh_from_db()
        proven.refresh_from_db()
        assert (unproven.company, proven.company) == (None, company)

    def test_nothing_to_change_writes_nothing(self, org):
        contact = ContactFactory(organization=org, email="a@x.io")
        before = _snapshot(contact)
        with CaptureQueriesContext(connection) as queries:
            assert resolve_contact_for_email(org, "a@x.io", name="Other") == contact
        assert not _updates(queries, "contacts_contact")
        assert _snapshot(contact) == before

    @pytest.mark.parametrize(
        "email",
        ["", "not-an-email", "a\x00b@x.io", "x" * 250 + "@x.io", ["a@x.io"]],
    )
    def test_unusable_email_gives_no_contact(self, org, email):
        ContactFactory(organization=org, email="", external_id="someone")
        ContactFactory(organization=org, email="", external_id="someone-else")
        assert resolve_contact_for_email(org, email, name="X") is None
        assert Contact.objects.filter(organization=org).count() == 2

    def test_deeply_nested_email_gives_no_contact(self, org):
        assert resolve_contact_for_email(org, _deeply_nested()) is None

    def test_long_name_is_truncated(self, org):
        contact = resolve_contact_for_email(org, "a@x.io", name="n" * 300)
        contact.refresh_from_db()
        assert contact.name == "n" * 255

    @pytest.mark.parametrize("name", [["Alice"], "a\x00b", True])
    def test_unusable_name_is_dropped(self, org, name):
        contact = resolve_contact_for_email(org, "a@x.io", name=name)
        contact.refresh_from_db()
        assert contact.name == ""


class TestWidgetSession:
    def test_anonymous_without_email_has_no_contact(self, org):
        assert resolve_contact_for_widget_session(_session(org)) is None
        assert not Contact.objects.filter(organization=org).exists()

    def test_anonymous_with_email_uses_email_contact(self, org):
        session = _session(org, email="c@x.io")
        contact = resolve_contact_for_widget_session(session)
        assert contact.email == "c@x.io"
        session.refresh_from_db()
        assert session.contact == contact

    def test_identified_creates_contact_by_external_id(self, org):
        session = _session(org, external_user_id="u1", name="D")
        contact = resolve_contact_for_widget_session(session)
        assert (contact.external_id, contact.name) == ("u1", "D")

    def test_traits_are_validated(self, org):
        _plan_def(org)
        session = _session(org, external_user_id="u3")
        contact = resolve_contact_for_widget_session(
            session, traits={"plan": "pro", "junk": 1}
        )
        assert contact.attributes == {"plan": "pro"}

    def test_traits_merge_with_stored_attributes(self, org):
        _plan_def(org)
        ContactFactory(organization=org, external_id="u3", attributes={"keep": 1})
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u3"), traits={"plan": "pro"}
        )
        assert contact.attributes == {"keep": 1, "plan": "pro"}

    @pytest.mark.parametrize("traits", ["plan", ["plan"], 3, {"plan": {"a": 1}}])
    def test_malformed_traits_are_ignored(self, org, traits):
        _plan_def(org)
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u3"), traits=traits
        )
        assert contact.attributes == {}

    @pytest.mark.parametrize("stored", [[], "junk", 3])
    def test_stored_attributes_of_the_wrong_shape_are_replaced(self, org, stored):
        _plan_def(org)
        ContactFactory(organization=org, external_id="u3", attributes=stored)
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u3"), traits={"plan": "pro"}
        )
        assert contact.attributes == {"plan": "pro"}

    def test_updates_seen_timestamps(self, org):
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u5")
        )
        assert contact.first_seen_at is not None
        assert contact.last_seen_at is not None

    def test_seen_timestamps_keep_the_first_visit(self, org):
        first = timezone.now() - timedelta(days=3)
        ContactFactory(organization=org, external_id="u5", first_seen_at=first)
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u5")
        )
        assert contact.first_seen_at == first
        assert contact.last_seen_at > first

    def test_existing_external_id_is_reused(self, org):
        ContactFactory(organization=org, external_id="u6")
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u6")
        )
        assert Contact.objects.filter(organization=org, external_id="u6").count() == 1
        assert contact.external_id == "u6"

    def test_external_id_does_not_cross_organizations(self, org):
        other = ContactFactory(external_id="u6")
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u6")
        )
        assert contact != other
        assert contact.organization == org

    def test_session_name_fills_only_a_blank_name_of_an_identified_contact(self, org):
        ContactFactory(organization=org, external_id="u7", name="Real")
        ContactFactory(organization=org, external_id="u8", name="")
        keeps = resolve_contact_for_widget_session(
            _session(org, external_user_id="u7", name="Other")
        )
        fills = resolve_contact_for_widget_session(
            _session(org, external_user_id="u8", name="New")
        )
        assert (keeps.name, fills.name) == ("Real", "New")


class TestNoWrites:
    """What isn't changing isn't written."""

    def test_returning_identified_visit_only_writes_the_seen_date(self, org):
        _plan_def(org)
        company = CompanyFactory(organization=org, external_id="c1", name="Same")
        contact = ContactFactory(
            organization=org,
            external_id="u1",
            name="Same",
            email="same@x.io",
            attributes={"plan": "pro"},
            company=company,
            first_seen_at=timezone.now() - timedelta(days=1),
        )
        before = _snapshot(contact)
        company_before = company.updated_at
        session = _session(
            org, external_user_id="u1", name="Same", email="same@x.io", contact=contact
        )
        with CaptureQueriesContext(connection) as queries:
            resolve_contact_for_widget_session(
                session,
                traits={"plan": "pro"},
                company={"id": "c1", "name": "Same"},
                company_verified=True,
            )
        updates = _updates(queries, "contacts_contact")
        assert len(updates) == 1
        assert '"last_seen_at"' in updates[0]
        for column in ('"first_seen_at"', '"updated_at"', '"name"', '"attributes"'):
            assert column not in updates[0]
        assert not _updates(queries, "contacts_company")
        assert not _updates(queries, "tickets_widgetsession")
        company.refresh_from_db()
        after = _snapshot(contact)
        assert after["last_seen_at"] is not None
        assert after["updated_at"] == before["updated_at"]
        assert _identity(contact) == {k: before[k] for k in _IDENTITY_FIELDS}
        assert company.updated_at == company_before

    def test_an_edit_bumps_updated_at_and_writes_only_that_field(self, org):
        contact = ContactFactory(organization=org, external_id="u1", name="")
        before = _snapshot(contact)
        with CaptureQueriesContext(connection) as queries:
            resolve_contact_for_widget_session(
                _session(org, external_user_id="u1", name="New")
            )
        update = _updates(queries, "contacts_contact")[0]
        assert '"name"' in update
        assert '"attributes"' not in update
        assert '"email"' not in update
        assert _snapshot(contact)["updated_at"] > before["updated_at"]

    def test_malformed_stored_attributes_are_left_alone_without_traits(self, org):
        contact = ContactFactory(organization=org, external_id="u1", attributes=[1])
        resolve_contact_for_widget_session(_session(org, external_user_id="u1"))
        contact.refresh_from_db()
        assert contact.attributes == [1]


class TestDeclaredEmail:
    """A declared email never moves, never merges and never proves anything."""

    def test_identified_does_not_steal_email_of_other_contact(self, org):
        victim = ContactFactory(organization=org, email="victim@x.io")
        before = _snapshot(victim)
        session = _session(org, external_user_id="attacker", email="victim@x.io")
        contact = resolve_contact_for_widget_session(session)
        assert contact != victim
        assert (contact.email, contact.declared_email) == ("", "victim@x.io")
        assert _snapshot(victim) == before

    def test_attacker_squatting_a_free_email_does_not_keep_the_victim_out(self, org):
        attacker = resolve_contact_for_widget_session(
            _session(org, external_user_id="attacker", email="Victim@X.io")
        )
        assert (attacker.email, attacker.declared_email) == ("", "victim@x.io")

        victim_session = _session(org, external_user_id="victim", email="victim@x.io")
        victim = resolve_contact_for_widget_session(victim_session, email_verified=True)

        victim_session.refresh_from_db()
        attacker.refresh_from_db()
        assert victim != attacker
        assert (victim.email, victim.declared_email) == ("victim@x.io", "")
        assert victim.email_verified_at is not None
        assert victim_session.email_verified_at is not None
        assert (attacker.email, attacker.declared_email) == ("", "victim@x.io")
        assert attacker.email_verified_at is None

    def test_inbound_mail_never_reaches_the_contact_declaring_the_address(self, org):
        attacker = resolve_contact_for_widget_session(
            _session(org, external_user_id="attacker", email="victim@x.io")
        )
        before = _snapshot(attacker)
        inbound = resolve_contact_for_email(org, "victim@x.io", name="Victim")
        assert inbound != attacker
        assert (inbound.email, inbound.external_id) == ("victim@x.io", "")
        assert _snapshot(attacker) == before

    def test_anonymous_session_never_reaches_the_contact_declaring_the_address(
        self, org
    ):
        attacker = resolve_contact_for_widget_session(
            _session(org, external_user_id="attacker", email="victim@x.io")
        )
        anon = resolve_contact_for_widget_session(_session(org, email="victim@x.io"))
        assert anon != attacker

    def test_declared_email_stays_on_the_session_contact_and_latest_wins(self, org):
        other = ContactFactory(organization=org, external_id="other", email="")
        before = _snapshot(other)
        contact = ContactFactory(organization=org, external_id="u1", email="")
        session = _session(org, external_user_id="u1")
        for email in ("first@x.io", "Second@X.io"):
            session.email = email
            resolve_contact_for_widget_session(session)
        contact.refresh_from_db()
        assert (contact.email, contact.declared_email) == ("", "second@x.io")
        assert contact.email_verified_at is None
        assert _snapshot(other) == before

    def test_identified_session_without_email_keeps_the_declared_one(self, org):
        contact = ContactFactory(
            organization=org, external_id="u1", email="", declared_email="d@x.io"
        )
        resolve_contact_for_widget_session(_session(org, external_user_id="u1"))
        contact.refresh_from_db()
        assert contact.declared_email == "d@x.io"

    def test_declaring_the_email_it_already_holds_is_not_a_separate_claim(self, org):
        contact = ContactFactory(
            organization=org,
            external_id="u1",
            email="a@x.io",
            declared_email="old@x.io",
        )
        resolve_contact_for_widget_session(
            _session(org, external_user_id="u1", email="A@x.io")
        )
        contact.refresh_from_db()
        assert (contact.email, contact.declared_email) == ("a@x.io", "")

    def test_never_merges_two_existing_contacts(self, org):
        by_email = ContactFactory(organization=org, email="a@x.io", external_id="")
        by_id = ContactFactory(organization=org, email="", external_id="u1")
        session = _session(org, external_user_id="u1", email="a@x.io")
        assert resolve_contact_for_widget_session(session) == by_id
        by_email.refresh_from_db()
        by_id.refresh_from_db()
        assert (by_email.email, by_email.external_id) == ("a@x.io", "")
        assert (by_id.email, by_id.declared_email) == ("", "a@x.io")
        assert by_id.external_id == "u1"
        assert Contact.objects.filter(organization=org).count() == 2

    def test_does_not_replace_the_email_of_the_session_contact(self, org):
        ContactFactory(organization=org, email="old@x.io", external_id="u1")
        session = _session(org, external_user_id="u1", email="new@x.io")
        contact = resolve_contact_for_widget_session(session)
        assert (contact.email, contact.declared_email) == ("old@x.io", "new@x.io")

    def test_identified_declared_email_on_blank_contact_is_unverified(self, org):
        session = _session(org, external_user_id="u1", email="free@x.io")
        contact = resolve_contact_for_widget_session(session)
        session.refresh_from_db()
        assert (contact.email, contact.declared_email) == ("", "free@x.io")
        assert contact.email_verified_at is None
        assert session.email_verified_at is None
        assert session.contact == contact

    @pytest.mark.parametrize("linked_company", [True, False])
    def test_anonymous_session_writes_nothing_on_the_owner(self, org, linked_company):
        _plan_def(org)
        company = CompanyFactory(organization=org, domain="x.io")
        victim = ContactFactory(
            organization=org,
            email="victim@x.io",
            name="",
            external_id="u1",
            attributes={"plan": "free"},
            company=company if linked_company else None,
        )
        before = _snapshot(victim)
        assert before["first_seen_at"] is None
        session = _session(org, email="victim@x.io", name="Attacker")
        contact = resolve_contact_for_widget_session(
            session,
            traits={"plan": "enterprise"},
            company={"id": "evil", "name": "Evil"},
        )
        assert contact == victim
        assert _snapshot(victim) == before
        assert not Company.objects.filter(external_id="evil").exists()

    def test_anonymous_declared_email_keeps_a_verified_owner_verified(self, org):
        at = timezone.now()
        victim = ContactFactory(
            organization=org, email="victim@x.io", email_verified_at=at
        )
        session = _session(org, email="victim@x.io")
        resolve_contact_for_widget_session(session)
        session.refresh_from_db()
        victim.refresh_from_db()
        assert victim.email_verified_at == at
        assert session.email_verified_at is None

    def test_inbound_email_never_verifies(self, org):
        victim = ContactFactory(organization=org, email="victim@x.io")
        resolve_contact_for_email(org, "victim@x.io", name="Attacker")
        victim.refresh_from_db()
        assert victim.email_verified_at is None

    def test_traits_on_a_new_declared_contact_are_dropped(self, org):
        _plan_def(org)
        contact = resolve_contact_for_widget_session(
            _session(org, email="new@x.io"), traits={"plan": "pro"}
        )
        assert contact.attributes == {}

    def test_new_anonymous_contact_is_seen_and_autolinked(self, org):
        company = CompanyFactory(organization=org, domain="x.io")
        contact = resolve_contact_for_widget_session(_session(org, email="new@x.io"))
        contact.refresh_from_db()
        assert contact.company == company
        assert contact.first_seen_at is not None
        assert contact.email_verified_at is None

    def test_unproven_identified_contact_is_not_autolinked(self, org):
        CompanyFactory(organization=org, domain="x.io")
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u1", email="me@x.io")
        )
        assert contact.company is None

    def test_identified_contact_holding_an_unproven_email_is_not_autolinked(self, org):
        CompanyFactory(organization=org, domain="x.io")
        contact = ContactFactory(organization=org, external_id="u1", email="me@x.io")
        resolve_contact_for_widget_session(
            _session(org, external_user_id="u1", email="me@x.io")
        )
        contact.refresh_from_db()
        assert contact.company is None


class TestVerifiedEmail:
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

    def test_verified_email_fills_a_blank_contact(self, org):
        ContactFactory(organization=org, email="", external_id="u1")
        session = _session(org, external_user_id="u1", email="f@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        session.refresh_from_db()
        assert contact.email == "f@x.io"
        assert contact.email_verified_at is not None
        assert session.email_verified_at is not None

    def test_proven_email_clears_the_same_declared_one(self, org):
        ContactFactory(
            organization=org, email="", external_id="u1", declared_email="f@x.io"
        )
        session = _session(org, external_user_id="u1", email="f@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        assert (contact.email, contact.declared_email) == ("f@x.io", "")

    def test_proven_email_keeps_a_different_declared_one(self, org):
        ContactFactory(
            organization=org, email="", external_id="u1", declared_email="d@x.io"
        )
        session = _session(org, external_user_id="u1", email="f@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        assert (contact.email, contact.declared_email) == ("f@x.io", "d@x.io")

    def test_declared_email_not_held_by_the_contact_stays_declared(self, org):
        """A proof that doesn't stick is no proof: the contact keeps the claim."""
        ContactFactory(organization=org, email="b@x.io", external_id="")
        contact = ContactFactory(
            organization=org, email="", external_id="u1", declared_email="b@x.io"
        )
        session = _session(org, external_user_id="u1", email="b@x.io")
        resolve_contact_for_widget_session(session, email_verified=True)
        contact.refresh_from_db()
        assert (contact.email, contact.declared_email) == ("", "b@x.io")

    def test_filling_the_email_replaces_a_stale_verification_date(self, org):
        stale = timezone.now() - timedelta(days=30)
        ContactFactory(
            organization=org, email="", external_id="u1", email_verified_at=stale
        )
        session = _session(org, external_user_id="u1", email="f@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        assert contact.email == "f@x.io"
        assert contact.email_verified_at > stale

    def test_attaching_keeps_the_existing_verification_date(self, org):
        at = timezone.now() - timedelta(days=3)
        ContactFactory(organization=org, email="e@x.io", email_verified_at=at)
        session = _session(org, external_user_id="u2", email="e@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        assert contact.external_id == "u2"
        assert contact.email_verified_at == at

    @pytest.mark.parametrize("identified", [True, False])
    def test_proven_contact_seen_dates_are_updated(self, org, identified):
        ContactFactory(organization=org, email="f@x.io")
        kwargs = {"external_user_id": "u1"} if identified else {}
        contact = resolve_contact_for_widget_session(
            _session(org, email="f@x.io", **kwargs), email_verified=True
        )
        contact.refresh_from_db()
        assert contact.first_seen_at is not None
        assert contact.last_seen_at is not None

    def test_proven_identified_contact_is_autolinked(self, org):
        company = CompanyFactory(organization=org, domain="x.io")
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u1", email="me@x.io"), email_verified=True
        )
        assert contact.company == company

    def test_identified_contact_with_a_proven_email_is_autolinked_later(self, org):
        contact = ContactFactory(
            organization=org,
            external_id="u1",
            email="me@x.io",
            email_verified_at=timezone.now(),
        )
        company = CompanyFactory(organization=org, domain="x.io")
        resolve_contact_for_widget_session(_session(org, external_user_id="u1"))
        contact.refresh_from_db()
        assert contact.company == company

    def test_anonymous_proof_on_an_existing_contact_does_not_autolink(self, org):
        contact = ContactFactory(organization=org, email="me@x.io")
        CompanyFactory(organization=org, domain="x.io")
        resolve_contact_for_widget_session(
            _session(org, email="me@x.io"), email_verified=True
        )
        contact.refresh_from_db()
        assert contact.company is None

    def test_first_verification_date_is_kept(self, org):
        at = timezone.now() - timedelta(days=3)
        ContactFactory(organization=org, email="f@x.io", email_verified_at=at)
        contact = resolve_contact_for_widget_session(
            _session(org, email="f@x.io"), email_verified=True
        )
        assert contact.email_verified_at == at

    def test_verified_anonymous_owner_can_set_traits(self, org):
        _plan_def(org)
        owner = ContactFactory(organization=org, email="f@x.io")
        resolve_contact_for_widget_session(
            _session(org, email="f@x.io"),
            email_verified=True,
            traits={"plan": "pro"},
        )
        owner.refresh_from_db()
        assert owner.attributes == {"plan": "pro"}

    def test_verified_without_email_marks_nothing(self, org):
        session = _session(org, external_user_id="u1")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        session.refresh_from_db()
        assert contact.email_verified_at is None
        assert session.email_verified_at is None

    def test_contact_with_another_email_is_left_alone(self, org):
        """The session's contact has email A, the session proves a free email B."""
        contact = ContactFactory(organization=org, email="a@x.io", external_id="u1")
        before = _identity(contact)
        session = _session(org, external_user_id="u1", email="b@x.io")
        assert resolve_contact_for_widget_session(session, email_verified=True) == (
            contact
        )
        session.refresh_from_db()
        assert _identity(contact) == before
        assert session.email_verified_at is None
        assert session.contact == contact

    def test_contact_with_another_email_does_not_take_over_an_owned_one(self, org):
        """The session's contact has email A, the session proves C's email B."""
        contact = ContactFactory(organization=org, email="a@x.io", external_id="u1")
        owner = ContactFactory(organization=org, email="b@x.io", external_id="")
        before = (_identity(contact), _snapshot(owner))
        session = _session(org, external_user_id="u1", email="b@x.io")
        assert resolve_contact_for_widget_session(session, email_verified=True) == (
            contact
        )
        session.refresh_from_db()
        assert (_identity(contact), _snapshot(owner)) == before
        assert session.email_verified_at is None

    def test_blank_contact_does_not_take_over_an_owned_email(self, org):
        contact = ContactFactory(organization=org, email="", external_id="u1")
        owner = ContactFactory(organization=org, email="b@x.io", external_id="")
        before = (_identity(contact), _snapshot(owner))
        session = _session(org, external_user_id="u1", email="b@x.io")
        assert resolve_contact_for_widget_session(session, email_verified=True) == (
            contact
        )
        session.refresh_from_db()
        assert (_identity(contact), _snapshot(owner)) == before
        assert session.email_verified_at is None

    def test_does_not_attach_to_an_email_contact_with_another_identity(self, org):
        owner = ContactFactory(organization=org, email="b@x.io", external_id="u1")
        before = _snapshot(owner)
        session = _session(org, external_user_id="u2", email="b@x.io")
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        session.refresh_from_db()
        assert contact != owner
        assert (contact.external_id, contact.email) == ("u2", "")
        assert contact.email_verified_at is None
        assert session.email_verified_at is None
        assert _snapshot(owner) == before


class TestAnonymizedContact:
    """An anonymized contact is never written to again."""

    @pytest.fixture
    def anonymized(self, org):
        return ContactFactory(
            organization=org,
            email="anonymized-abc@example.invalid",
            name="Anonymized contact",
            external_id="",
            is_anonymized=True,
            attributes={},
        )

    def test_inbound_mail_matching_it_writes_nothing(self, org, anonymized):
        before = _snapshot(anonymized)
        assert resolve_contact_for_email(org, anonymized.email, name="Alice") is None
        assert _snapshot(anonymized) == before

    @pytest.mark.parametrize("verified", [False, True])
    def test_anonymous_session_matching_it_writes_nothing(
        self, org, anonymized, verified
    ):
        _plan_def(org)
        before = _snapshot(anonymized)
        session = _session(org, email=anonymized.email, name="Alice")
        assert (
            resolve_contact_for_widget_session(
                session, email_verified=verified, traits={"plan": "pro"}
            )
            is None
        )
        session.refresh_from_db()
        assert _snapshot(anonymized) == before
        assert session.contact is None
        assert session.email_verified_at is None

    def test_verified_identified_session_does_not_attach_to_it(self, org, anonymized):
        before = _snapshot(anonymized)
        session = _session(org, external_user_id="u1", email=anonymized.email)
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        session.refresh_from_db()
        assert contact != anonymized
        assert contact.email == ""
        assert session.email_verified_at is None
        assert _snapshot(anonymized) == before

    def test_external_id_left_on_it_matches_nothing_and_writes_nothing(self, org):
        _plan_def(org)
        anonymized = ContactFactory(
            organization=org, external_id="u1", name="", is_anonymized=True
        )
        before = _snapshot(anonymized)
        session = _session(org, external_user_id="u1", name="Alice", email="a@x.io")
        assert (
            resolve_contact_for_widget_session(
                session,
                traits={"plan": "pro"},
                company={"id": "c1", "name": "C"},
            )
            is None
        )
        session.refresh_from_db()
        assert _snapshot(anonymized) == before
        assert session.contact is None
        assert not Company.objects.filter(external_id="c1").exists()

    def test_returning_user_gets_a_fresh_contact(self, org, anonymized):
        session = _session(org, external_user_id="u1", email="alice@x.io", name="A")
        session.contact = anonymized
        session.save(update_fields=["contact"])
        before = _snapshot(anonymized)
        contact = resolve_contact_for_widget_session(session)
        session.refresh_from_db()
        assert contact != anonymized
        assert session.contact == contact
        assert _snapshot(anonymized) == before


class TestNoContactUnlinksTheSession:
    """Whenever the service returns None, the session isn't linked to anything."""

    @pytest.mark.parametrize("is_anonymized", [True, False])
    def test_blank_session(self, org, is_anonymized):
        linked = ContactFactory(organization=org, is_anonymized=is_anonymized)
        session = _session(org, contact=linked)
        assert resolve_contact_for_widget_session(session) is None
        session.refresh_from_db()
        assert session.contact is None

    def test_unusable_email(self, org):
        session = _session(org, contact=ContactFactory(organization=org))
        session.email = "not-an-email"
        assert resolve_contact_for_widget_session(session) is None
        session.refresh_from_db()
        assert session.contact is None

    def test_unusable_external_id(self, org):
        session = _session(org, contact=ContactFactory(organization=org))
        session.external_user_id = "x" * 300
        assert resolve_contact_for_widget_session(session) is None
        session.refresh_from_db()
        assert session.contact is None

    @pytest.mark.parametrize("external_id", ["email:a@x.io", "company\nc"])
    def test_reserved_external_id_of_an_older_session(self, org, external_id):
        session = _session(
            org, external_user_id=external_id, email="a@x.io", name="Ann"
        )
        assert resolve_contact_for_widget_session(session) is None
        assert not Contact.objects.filter(organization=org).exists()

    def test_identified_session_whose_contact_was_anonymized(self, org):
        anonymized = ContactFactory(
            organization=org, external_id="u1", is_anonymized=True
        )
        session = _session(org, external_user_id="u1", contact=anonymized)
        assert resolve_contact_for_widget_session(session) is None
        session.refresh_from_db()
        assert session.contact is None


class TestCompanyPayload:
    """What applies whether or not the payload is signed."""

    def _resolve(self, org, company, **kwargs):
        return resolve_contact_for_widget_session(
            _session(org, external_user_id="u4"), company=company, **kwargs
        )

    def test_company_payload_only_for_identified(self, org):
        contact = self._resolve(org, {"id": "c42", "name": "Startup"})
        assert contact.company.external_id == "c42"
        anon = _session(org, email="g@other.io")
        contact = resolve_contact_for_widget_session(
            anon, company={"id": "c43", "name": "Evil"}, company_verified=True
        )
        assert contact.company is None
        assert not Company.objects.filter(external_id="c43").exists()

    def test_verified_anonymous_session_creates_no_company(self, org):
        contact = resolve_contact_for_widget_session(
            _session(org, email="g@other.io"),
            email_verified=True,
            company={"id": "c43", "name": "Evil"},
            company_verified=True,
        )
        assert contact.company is None
        assert not Company.objects.filter(external_id="c43").exists()

    def test_integer_id_is_accepted(self, org):
        contact = self._resolve(org, {"id": 42, "name": "Startup"})
        assert contact.company.external_id == "42"

    @pytest.mark.parametrize(
        ("payload", "company_verified"),
        [
            ("c1", True),  # Not a dict.
            ({"name": "S"}, False),  # No id.
            ({"id": "c1"}, True),  # No name.
            ({"id": True, "name": "S"}, False),  # An integer to Python only.
            ({"id": 10**5000, "name": "S"}, True),  # Beyond the int-to-str digit limit.
            ({"id": "a\x00b", "name": "S"}, False),  # Not storable.
            ({"id": "x" * 256, "name": "S"}, True),  # Too long to be an identifier.
        ],
    )
    def test_malformed_payload_creates_no_company(self, org, payload, company_verified):
        contact = self._resolve(org, payload, company_verified=company_verified)
        assert contact.company is None
        assert not Company.objects.filter(organization=org).exists()

    @pytest.mark.parametrize("field", ["id", "name", "domain"])
    def test_deeply_nested_value_does_not_overflow_the_stack(self, org, field):
        payload = {"id": "c1", "name": "S", field: _deeply_nested()}
        contact = self._resolve(org, payload)
        assert contact.external_id == "u4"

    def test_long_name_is_truncated(self, org):
        contact = self._resolve(org, {"id": "c1", "name": "n" * 300})
        contact.company.refresh_from_db()
        assert contact.company.name == "n" * 255

    def test_two_long_ids_sharing_a_prefix_never_collide(self, org):
        existing = CompanyFactory(organization=org, external_id="x" * 255, name="Old")
        contact = self._resolve(
            org, {"id": "x" * 300, "name": "Evil"}, company_verified=True
        )
        existing.refresh_from_db()
        assert contact.company is None
        assert existing.name == "Old"

    def test_traits_are_validated(self, org):
        CompanyAttributeDef.objects.create(
            organization=org, key="tier", label="Tier", type="string"
        )
        contact = self._resolve(
            org, {"id": "c1", "name": "S", "traits": {"tier": "a", "junk": 1}}
        )
        assert contact.company.attributes == {"tier": "a"}

    def test_malformed_traits_are_ignored(self, org):
        contact = self._resolve(org, {"id": "c1", "name": "S", "traits": ["tier"]})
        assert contact.company.attributes == {}

    def test_invalid_payload_falls_back_on_a_proven_email_domain(self, org):
        company = CompanyFactory(organization=org, domain="startup.com")
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u4", email="bob@startup.com"),
            email_verified=True,
            company={"id": ["x"], "name": "S"},
        )
        assert contact.company == company


class TestUnsignedCompany:
    """Without a valid ``company_hash``, the payload is the user's word."""

    def _resolve(self, org, company, **kwargs):
        kwargs.setdefault("external_user_id", "u4")
        email_verified = kwargs.pop("email_verified", False)
        return resolve_contact_for_widget_session(
            _session(org, **kwargs), company=company, email_verified=email_verified
        )

    def test_existing_company_is_linked_but_never_modified(self, org):
        CompanyAttributeDef.objects.create(
            organization=org, key="tier", label="Tier", type="string"
        )
        existing = CompanyFactory(
            organization=org,
            external_id="c1",
            name="Real",
            domain="real.io",
            attributes={"tier": "gold"},
        )
        updated_at = existing.updated_at
        contact = self._resolve(
            org,
            {
                "id": "c1",
                "name": "Renamed",
                "domain": "evil.io",
                "traits": {"tier": None},
            },
        )
        existing.refresh_from_db()
        assert contact.company == existing
        assert (existing.name, existing.domain) == ("Real", "real.io")
        assert existing.attributes == {"tier": "gold"}
        assert existing.updated_at == updated_at

    def test_existing_company_gets_no_domain_even_from_a_proven_email(self, org):
        existing = CompanyFactory(organization=org, external_id="c1", domain="")
        self._resolve(
            org,
            {"id": "c1", "name": "S", "domain": "x.io"},
            email="me@x.io",
            email_verified=True,
        )
        existing.refresh_from_db()
        assert existing.domain == ""

    def test_contact_with_a_company_is_not_moved_and_creates_nothing(self, org):
        current = CompanyFactory(organization=org, external_id="current")
        other = CompanyFactory(organization=org, external_id="other")
        contact = ContactFactory(organization=org, external_id="u4", company=current)
        for payload in ({"id": "other", "name": "O"}, {"id": "new", "name": "N"}):
            self._resolve(org, payload)
            contact.refresh_from_db()
            assert contact.company == current
            WidgetSession.objects.filter(organization=org).delete()
        assert not Company.objects.filter(external_id="new").exists()
        assert other.contacts.count() == 0

    def test_new_company_takes_the_name_and_traits(self, org):
        CompanyAttributeDef.objects.create(
            organization=org, key="tier", label="Tier", type="string"
        )
        contact = self._resolve(
            org, {"id": "c1", "name": "New", "traits": {"tier": "a"}}
        )
        contact.company.refresh_from_db()
        assert (contact.company.name, contact.company.domain) == ("New", "")
        assert contact.company.attributes == {"tier": "a"}

    def test_domain_of_the_proven_email_is_accepted(self, org):
        contact = self._resolve(
            org,
            {"id": "c1", "name": "S", "domain": " X.io. "},
            email="me@x.io",
            email_verified=True,
        )
        contact.company.refresh_from_db()
        assert contact.company.domain == "x.io"

    @pytest.mark.parametrize(
        ("email", "email_verified", "domain"),
        [
            ("", False, "x.io"),  # No email at all.
            ("me@x.io", False, "x.io"),  # The same domain, but merely declared.
            ("me@x.io", True, "other.io"),  # Proven, but another domain.
            ("me@x.io", True, "sub.x.io"),  # A subdomain is another domain.
            ("me@gmail.com", True, "gmail.com"),  # Nobody's company domain.
        ],
    )
    def test_domain_without_matching_proof_is_dropped(
        self, org, email, email_verified, domain
    ):
        contact = self._resolve(
            org,
            {"id": "c1", "name": "S", "domain": domain},
            email=email,
            email_verified=email_verified,
        )
        contact.company.refresh_from_db()
        assert contact.company.external_id == "c1"
        assert contact.company.domain == ""

    def test_proof_that_did_not_stick_does_not_prove_the_domain(self, org):
        ContactFactory(organization=org, email="me@x.io", external_id="other")
        contact = self._resolve(
            org,
            {"id": "c1", "name": "S", "domain": "x.io"},
            email="me@x.io",
            email_verified=True,
        )
        contact.company.refresh_from_db()
        assert contact.company.domain == ""

    @pytest.mark.parametrize("email_verified", [True, False])
    def test_new_company_cannot_hijack_a_domain(self, org, email_verified):
        victim = CompanyFactory(organization=org, domain="victim.io", external_id="v")
        contact = self._resolve(
            org,
            {"id": "c1", "name": "S", "domain": "VICTIM.io"},
            email="me@victim.io",
            email_verified=email_verified,
        )
        victim.refresh_from_db()
        contact.company.refresh_from_db()
        assert victim.domain == "victim.io"
        assert contact.company != victim
        assert contact.company.domain == ""


class TestSignedCompany:
    """With ``company_verified=True``, the host app vouches for the payload."""

    def _resolve(self, org, company, **kwargs):
        return resolve_contact_for_widget_session(
            _session(org, external_user_id="u4"),
            company=company,
            company_verified=True,
            **kwargs,
        )

    def test_name_and_domain_of_an_existing_company_are_updated_but_not_traits(
        self, org
    ):
        CompanyAttributeDef.objects.create(
            organization=org, key="tier", label="Tier", type="string"
        )
        existing = CompanyFactory(
            organization=org,
            external_id="c1",
            name="Old",
            domain="old.io",
            attributes={"tier": "gold", "keep": 1},
        )
        contact = self._resolve(
            org,
            {
                "id": "c1",
                "name": "New",
                "domain": "new.io",
                "traits": {"tier": "silver"},
            },
        )
        existing.refresh_from_db()
        assert contact.company == existing
        assert (existing.name, existing.domain) == ("New", "new.io")
        # The hash covers the id, name and domain: traits aren't signed.
        assert existing.attributes == {"tier": "gold", "keep": 1}

    def test_traits_apply_to_a_new_company(self, org):
        CompanyAttributeDef.objects.create(
            organization=org, key="tier", label="Tier", type="string"
        )
        contact = self._resolve(
            org,
            {"id": "c1", "name": "New", "traits": {"tier": "silver", "junk": 1}},
        )
        contact.company.refresh_from_db()
        assert contact.company.attributes == {"tier": "silver"}

    def test_traits_alone_write_nothing_on_an_existing_company(self, org):
        CompanyAttributeDef.objects.create(
            organization=org, key="tier", label="Tier", type="string"
        )
        existing = CompanyFactory(organization=org, external_id="c1", name="S")
        updated_at = existing.updated_at
        self._resolve(org, {"id": "c1", "name": "S", "traits": {"tier": "a"}})
        existing.refresh_from_db()
        assert existing.updated_at == updated_at
        assert existing.attributes == {}

    def test_the_contact_is_moved(self, org):
        current = CompanyFactory(organization=org, external_id="current")
        contact = ContactFactory(organization=org, external_id="u4", company=current)
        self._resolve(org, {"id": "new", "name": "N"})
        contact.refresh_from_db()
        assert contact.company.external_id == "new"

    def test_stored_attributes_of_the_wrong_shape_are_left_alone(self, org):
        CompanyAttributeDef.objects.create(
            organization=org, key="tier", label="Tier", type="string"
        )
        existing = CompanyFactory(organization=org, external_id="c1", attributes=[1])
        self._resolve(org, {"id": "c1", "name": "S", "traits": {"tier": "a"}})
        existing.refresh_from_db()
        assert existing.attributes == [1]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  Startup.IO ", "startup.io"),
            ("startup.io.", "startup.io"),
        ],
    )
    def test_domain_is_normalized(self, org, raw, expected):
        contact = self._resolve(org, {"id": "c1", "name": "S", "domain": raw})
        contact.company.refresh_from_db()
        assert contact.company.domain == expected

    @pytest.mark.parametrize(
        "domain",
        [
            "not a domain",  # Rejected by the validator.
            "x" * 250 + ".io",  # Rejected by the validator's length limits.
            "a\x00b.io",  # Not storable.
            ["startup.io"],  # Not text at all.
        ],
    )
    def test_unusable_domain_is_dropped_and_the_company_still_linked(self, org, domain):
        contact = self._resolve(org, {"id": "c1", "name": "S", "domain": domain})
        contact.company.refresh_from_db()
        assert contact.company.external_id == "c1"
        assert contact.company.domain == ""

    def test_unusable_domain_keeps_the_stored_one(self, org):
        existing = CompanyFactory(organization=org, external_id="c1", domain="s.io")
        self._resolve(org, {"id": "c1", "name": "S", "domain": "not a domain"})
        existing.refresh_from_db()
        assert existing.domain == "s.io"

    def test_domain_of_another_company_is_not_stolen(self, org):
        victim = CompanyFactory(organization=org, domain="victim.io", external_id="v")
        contact = self._resolve(org, {"id": "c1", "name": "S", "domain": "VICTIM.io"})
        victim.refresh_from_db()
        contact.company.refresh_from_db()
        assert victim.domain == "victim.io"
        assert contact.company.domain == ""
        assert contact.company != victim

    def test_domain_of_another_organization_is_free(self, org):
        CompanyFactory(domain="startup.io")
        contact = self._resolve(org, {"id": "c1", "name": "S", "domain": "startup.io"})
        assert contact.company.domain == "startup.io"

    def test_resending_its_own_domain_keeps_it(self, org):
        existing = CompanyFactory(organization=org, external_id="c1", domain="s.io")
        self._resolve(org, {"id": "c1", "name": "S", "domain": "s.io"})
        existing.refresh_from_db()
        assert existing.domain == "s.io"

    def test_blank_domain_runs_no_lookup_and_matches_no_blank_row(self, org):
        blank = CompanyFactory(organization=org, external_id="other", domain="")
        existing = CompanyFactory(organization=org, external_id="c1", domain="s.io")
        with CaptureQueriesContext(connection) as queries:
            self._resolve(org, {"id": "c1", "name": "S", "domain": ""})
        assert not [
            query["sql"]
            for query in queries
            if query["sql"].startswith("SELECT") and '"domain" = ' in query["sql"]
        ]
        existing.refresh_from_db()
        blank.refresh_from_db()
        assert (existing.domain, blank.domain) == ("s.io", "")
        assert blank.contacts.count() == 0

    def test_identical_payload_writes_no_company(self, org):
        existing = CompanyFactory(
            organization=org, external_id="c1", name="S", domain="s.io"
        )
        contact = ContactFactory(organization=org, external_id="u4", company=existing)
        updated_at = existing.updated_at
        self._resolve(org, {"id": "c1", "name": "S", "domain": "s.io"})
        existing.refresh_from_db()
        contact.refresh_from_db()
        assert existing.updated_at == updated_at
        assert contact.company == existing


class TestOversizedSessionValues:
    def test_long_session_name_is_truncated(self, org):
        session = _session(org, external_user_id="u1")
        session.name = "n" * 300
        contact = resolve_contact_for_widget_session(session)
        contact.refresh_from_db()
        assert contact.name == "n" * 255

    def test_long_session_name_is_truncated_on_an_existing_contact(self, org):
        ContactFactory(organization=org, external_id="u1", name="")
        session = _session(org, external_user_id="u1")
        session.name = "n" * 300
        contact = resolve_contact_for_widget_session(session)
        contact.refresh_from_db()
        assert contact.name == "n" * 255

    def test_long_external_id_never_matches_a_truncated_one(self, org):
        victim = ContactFactory(organization=org, external_id="x" * 255)
        before = _snapshot(victim)
        session = _session(org)
        session.external_user_id = "x" * 300
        session.email = "attacker@x.io"
        assert resolve_contact_for_widget_session(session) is None
        assert _snapshot(victim) == before
        assert Contact.objects.filter(organization=org).count() == 1

    def test_long_email_is_ignored(self, org):
        session = _session(org, external_user_id="u1")
        session.email = "x" * 250 + "@x.io"
        contact = resolve_contact_for_widget_session(session, email_verified=True)
        session.refresh_from_db()
        assert contact.email == ""
        assert session.email_verified_at is None

    def test_padded_external_id_with_a_valid_hmac_is_not_an_identity(self, org):
        """The host app signed " u1 ": it isn't "u1", and we wouldn't store it."""
        other = ContactFactory(organization=org, external_id="u1")
        before = _snapshot(other)
        session = _session(org, external_user_id=" u1 ", email="a@x.io", contact=other)
        assert resolve_contact_for_widget_session(session, email_verified=True) is None
        session.refresh_from_db()
        assert session.contact is None
        assert session.email_verified_at is None
        assert _snapshot(other) == before
        assert Contact.objects.filter(organization=org).count() == 1

    @pytest.mark.parametrize("value", ["a\x00b", "\ud800", ["u1"], {"a": 1}])
    def test_unusable_external_id_is_not_an_identity(self, org, value):
        session = _session(org)
        session.external_user_id = value
        assert resolve_contact_for_widget_session(session) is None
        assert not Contact.objects.filter(organization=org).exists()

    def test_unusable_session_name_is_dropped(self, org):
        session = _session(org, external_user_id="u1")
        session.name = "a\x00b"
        contact = resolve_contact_for_widget_session(session)
        contact.refresh_from_db()
        assert contact.name == ""


class TestRaces:
    """A rival commits between our check and our save: the constraint catches it."""

    def test_email_claimed_between_check_and_save_is_not_taken(self, org):
        rival = ContactFactory(organization=org, email="race@x.io", external_id="other")
        before = _snapshot(rival)
        session = _session(org, external_user_id="u1", email="race@x.io")
        with mock.patch(
            "apps.contacts.services._email_taken", side_effect=[False, True]
        ):
            contact = resolve_contact_for_widget_session(session, email_verified=True)
        session.refresh_from_db()
        contact.refresh_from_db()
        assert contact != rival
        assert (contact.external_id, contact.email) == ("u1", "")
        assert contact.email_verified_at is None
        assert session.email_verified_at is None
        assert session.contact == contact
        assert _snapshot(rival) == before

    def test_external_id_claimed_while_attaching_goes_to_its_owner(self, org):
        """First pass misses the rival and attaches, the unique constraint refuses."""
        rival = ContactFactory(organization=org, email="", external_id="u1")
        email_only = ContactFactory(organization=org, email="e@x.io", external_id="")
        real_locked = services._locked
        missed = []

        def miss_the_rival_once(model, **lookup):
            if lookup.get("external_id") == "u1" and not missed:
                missed.append(True)
                return None
            return real_locked(model, **lookup)

        session = _session(org, external_user_id="u1", email="e@x.io")
        with mock.patch.object(services, "_locked", miss_the_rival_once):
            contact = resolve_contact_for_widget_session(session, email_verified=True)
        email_only.refresh_from_db()
        contact.refresh_from_db()
        session.refresh_from_db()
        assert missed
        assert contact == rival
        assert email_only.external_id == ""
        assert contact.email == ""
        assert session.email_verified_at is None

    def test_external_id_created_by_a_rival_is_reused_under_the_lock(self, org):
        """``get_or_create`` finds the rival's row, which still has to be locked."""
        rival = ContactFactory(organization=org, email="", external_id="u1", name="")
        real_locked = services._locked
        missed = []

        def miss_the_rival_once(model, **lookup):
            if lookup.get("external_id") == "u1" and not missed:
                missed.append(True)
                return None
            return real_locked(model, **lookup)

        session = _session(org, external_user_id="u1", name="New")
        with mock.patch.object(services, "_locked", miss_the_rival_once):
            contact = resolve_contact_for_widget_session(session)
        rival.refresh_from_db()
        assert contact == rival
        assert rival.name == "New"

    def test_rival_row_deleted_before_the_lock_gives_no_contact(self, org):
        ContactFactory(organization=org, email="a@x.io")
        session = _session(org, email="a@x.io")
        with mock.patch.object(services, "_locked", return_value=None):
            assert resolve_contact_for_widget_session(session) is None

    def test_domain_claimed_while_creating_an_unsigned_company_is_dropped(self, org):
        rival = CompanyFactory(organization=org, external_id="v", domain="x.io")
        session = _session(org, external_user_id="u1", email="me@x.io")
        with mock.patch(
            "apps.contacts.services._domain_taken", side_effect=[False, True]
        ):
            contact = resolve_contact_for_widget_session(
                session,
                email_verified=True,
                company={"id": "c1", "name": "S", "domain": "x.io"},
            )
        rival.refresh_from_db()
        contact.company.refresh_from_db()
        assert rival.domain == "x.io"
        assert contact.company != rival
        assert (contact.company.external_id, contact.company.domain) == ("c1", "")

    def test_domain_claimed_while_updating_a_signed_company_is_dropped(self, org):
        rival = CompanyFactory(organization=org, external_id="v", domain="x.io")
        existing = CompanyFactory(
            organization=org, external_id="c1", name="Old", domain=""
        )
        session = _session(org, external_user_id="u1")
        with mock.patch(
            "apps.contacts.services._domain_taken", side_effect=[False, True]
        ):
            contact = resolve_contact_for_widget_session(
                session,
                company={"id": "c1", "name": "New", "domain": "x.io"},
                company_verified=True,
            )
        rival.refresh_from_db()
        existing.refresh_from_db()
        assert contact.company == existing
        assert rival.domain == "x.io"
        assert (existing.name, existing.domain) == ("New", "")

    def test_a_second_conflict_reaches_the_caller(self, org):
        """The view decides what to do about it: the service retries only once."""
        session = _session(org, external_user_id="u1")
        with (
            mock.patch.object(
                services, "_resolve_session_once", side_effect=IntegrityError
            ) as resolve,
            pytest.raises(IntegrityError),
        ):
            resolve_contact_for_widget_session(session)
        assert resolve.call_count == 2

    @staticmethod
    def _failing_session_writes(error=IntegrityError, times=1):
        """Fail the session's first writes, as a commit-time conflict would."""
        real = services._save_changes
        failures = [error] * times

        def save_changes(instance, changed):
            if isinstance(instance, WidgetSession) and failures:
                raise failures.pop()
            real(instance, changed)

        return mock.patch.object(services, "_save_changes", save_changes)

    def test_retry_writes_the_link_of_the_failed_pass(self, org):
        session = _session(org, external_user_id="u1", email="a@x.io")
        with self._failing_session_writes():
            contact = resolve_contact_for_widget_session(session, email_verified=True)
        stored = WidgetSession.objects.get(pk=session.pk)
        assert stored.contact == contact
        assert stored.email_verified_at is not None
        assert session.email_verified_at == stored.email_verified_at

    def test_retry_writes_the_unlink_of_the_failed_pass(self, org):
        anonymized = ContactFactory(
            organization=org, external_id="u1", is_anonymized=True
        )
        session = _session(org, external_user_id="u1", contact=anonymized)
        real_save = session.save
        failures = [IntegrityError]

        def save(*args, **kwargs):
            if failures:
                raise failures.pop()
            real_save(*args, **kwargs)

        with mock.patch.object(session, "save", save):
            assert resolve_contact_for_widget_session(session) is None
        assert WidgetSession.objects.get(pk=session.pk).contact is None

    def test_a_retry_that_fails_too_leaves_the_session_as_stored(self, org):
        session = _session(org, external_user_id="u1", email="a@x.io")
        with self._failing_session_writes(times=2), pytest.raises(IntegrityError):
            resolve_contact_for_widget_session(session, email_verified=True)
        assert session.contact_id is None
        assert session.contact is None
        assert session.email_verified_at is None

    def test_other_database_errors_arent_retried_but_leave_the_session_as_stored(
        self, org
    ):
        session = _session(org, external_user_id="u1")
        with (
            self._failing_session_writes(OperationalError),
            pytest.raises(OperationalError),
        ):
            resolve_contact_for_widget_session(session)
        assert session.contact_id is None
