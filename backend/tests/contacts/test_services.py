"""Tests for the contact identity service (design section 3)."""

from datetime import timedelta
from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

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


def _snapshot(contact: Contact) -> dict:
    """Every identity-bearing field, re-read from the database."""
    return Contact.objects.filter(pk=contact.pk).values(
        "email",
        "email_verified_at",
        "external_id",
        "name",
        "attributes",
        "company_id",
    )[0]


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

    @pytest.mark.parametrize(
        "email",
        [
            "",
            "   ",
            None,
            "not-an-email",
            "a\x00b@x.io",
            "\ud800@x.io",
            "x" * 250 + "@x.io",
            ["a@x.io"],
            {"email": "a@x.io"},
            42,
        ],
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

    @pytest.mark.parametrize(
        "name", [None, ["Alice"], {"a": 1}, "a\x00b", "\ud800", True]
    )
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
        session = _session(org, external_user_id="u1", email="d@x.io", name="D")
        contact = resolve_contact_for_widget_session(session)
        assert (contact.external_id, contact.email, contact.name) == (
            "u1",
            "d@x.io",
            "D",
        )

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


class TestDeclaredEmail:
    """A declared email never moves, never merges and never proves anything."""

    def test_identified_does_not_steal_email_of_other_contact(self, org):
        victim = ContactFactory(organization=org, email="victim@x.io")
        before = _snapshot(victim)
        session = _session(org, external_user_id="attacker", email="victim@x.io")
        contact = resolve_contact_for_widget_session(session)
        assert contact != victim
        assert contact.email == ""
        assert _snapshot(victim) == before

    def test_never_merges_two_existing_contacts(self, org):
        by_email = ContactFactory(organization=org, email="a@x.io", external_id="")
        by_id = ContactFactory(organization=org, email="", external_id="u1")
        session = _session(org, external_user_id="u1", email="a@x.io")
        assert resolve_contact_for_widget_session(session) == by_id
        by_email.refresh_from_db()
        by_id.refresh_from_db()
        assert (by_email.email, by_email.external_id) == ("a@x.io", "")
        assert (by_id.email, by_id.external_id) == ("", "u1")
        assert Contact.objects.filter(organization=org).count() == 2

    def test_does_not_replace_the_email_of_the_session_contact(self, org):
        ContactFactory(organization=org, email="old@x.io", external_id="u1")
        session = _session(org, external_user_id="u1", email="new@x.io")
        assert resolve_contact_for_widget_session(session).email == "old@x.io"

    def test_identified_declared_email_on_blank_contact_is_unverified(self, org):
        session = _session(org, external_user_id="u1", email="free@x.io")
        contact = resolve_contact_for_widget_session(session)
        session.refresh_from_db()
        assert contact.email == "free@x.io"
        assert contact.email_verified_at is None
        assert session.email_verified_at is None

    def test_anonymous_session_writes_nothing_identifying_on_the_owner(self, org):
        _plan_def(org)
        company = CompanyFactory(organization=org)
        victim = ContactFactory(
            organization=org,
            email="victim@x.io",
            name="",
            external_id="u1",
            attributes={"plan": "free"},
            company=company,
        )
        before = _snapshot(victim)
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
        before = _snapshot(contact)
        session = _session(org, external_user_id="u1", email="b@x.io")
        assert resolve_contact_for_widget_session(session, email_verified=True) == (
            contact
        )
        session.refresh_from_db()
        assert _snapshot(contact) == before
        assert session.email_verified_at is None
        assert session.contact == contact

    def test_contact_with_another_email_does_not_take_over_an_owned_one(self, org):
        """The session's contact has email A, the session proves C's email B."""
        contact = ContactFactory(organization=org, email="a@x.io", external_id="u1")
        owner = ContactFactory(organization=org, email="b@x.io", external_id="")
        before = (_snapshot(contact), _snapshot(owner))
        session = _session(org, external_user_id="u1", email="b@x.io")
        assert resolve_contact_for_widget_session(session, email_verified=True) == (
            contact
        )
        session.refresh_from_db()
        assert (_snapshot(contact), _snapshot(owner)) == before
        assert session.email_verified_at is None

    def test_blank_contact_does_not_take_over_an_owned_email(self, org):
        contact = ContactFactory(organization=org, email="", external_id="u1")
        owner = ContactFactory(organization=org, email="b@x.io", external_id="")
        before = (_snapshot(contact), _snapshot(owner))
        session = _session(org, external_user_id="u1", email="b@x.io")
        assert resolve_contact_for_widget_session(session, email_verified=True) == (
            contact
        )
        session.refresh_from_db()
        assert (_snapshot(contact), _snapshot(owner)) == before
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

    def test_blank_session_still_linked_to_it_is_detached(self, org, anonymized):
        session = _session(org, contact=anonymized)
        assert resolve_contact_for_widget_session(session) is None
        session.refresh_from_db()
        assert session.contact is None


class TestCompanyPayload:
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

    def test_verified_anonymous_session_creates_no_company(self, org):
        contact = resolve_contact_for_widget_session(
            _session(org, email="g@other.io"),
            email_verified=True,
            company={"id": "c43", "name": "Evil"},
        )
        assert contact.company is None
        assert not Company.objects.filter(external_id="c43").exists()

    def _resolve(self, org, company):
        return resolve_contact_for_widget_session(
            _session(org, external_user_id="u4"), company=company
        )

    def test_payload_updates_the_existing_company(self, org):
        existing = CompanyFactory(organization=org, external_id="c1", name="Old")
        contact = self._resolve(org, {"id": "c1", "name": "New"})
        existing.refresh_from_db()
        assert contact.company == existing
        assert existing.name == "New"

    def test_integer_id_is_accepted(self, org):
        contact = self._resolve(org, {"id": 42, "name": "Startup"})
        assert contact.company.external_id == "42"

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
            "",
            "   ",
            None,
            "not a domain",
            "https://startup.io/path",
            "a@startup.io",
            "nodot",
            "a\x00b.io",
            "\ud800.io",
            "x" * 250 + ".io",
            42,
            ["startup.io"],
            {"a": 1},
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

    @pytest.mark.parametrize(
        "payload",
        [
            "c1",
            ["c1"],
            7,
            {},
            {"id": "c1"},
            {"name": "S"},
            {"id": {"a": 1}, "name": "S"},
            {"id": ["c1"], "name": "S"},
            {"id": True, "name": "S"},
            {"id": 1.5, "name": "S"},
            {"id": 10**5000, "name": "S"},
            {"id": "c1", "name": ["S"]},
            {"id": "c1", "name": {"a": 1}},
            {"id": "c1", "name": True},
            {"id": "a\x00b", "name": "S"},
            {"id": "c1", "name": "\ud800"},
            {"id": "x" * 256, "name": "S"},
        ],
    )
    def test_malformed_payload_creates_no_company(self, org, payload):
        contact = self._resolve(org, payload)
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
        contact = self._resolve(org, {"id": "x" * 300, "name": "Evil"})
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

    @pytest.mark.parametrize("traits", ["tier", ["tier"], 3])
    def test_malformed_traits_are_ignored(self, org, traits):
        contact = self._resolve(org, {"id": "c1", "name": "S", "traits": traits})
        assert contact.company.attributes == {}

    def test_invalid_payload_falls_back_on_the_email_domain(self, org):
        company = CompanyFactory(organization=org, domain="startup.com")
        contact = resolve_contact_for_widget_session(
            _session(org, external_user_id="u4", email="bob@startup.com"),
            company={"id": ["x"], "name": "S"},
        )
        assert contact.company == company


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
    def test_email_claimed_between_check_and_save_is_not_taken(self, org):
        """The unique constraint catches a concurrent claim: retry, no error."""
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
