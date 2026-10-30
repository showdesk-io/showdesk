"""Tests for the identity service wired into the widget endpoints."""

import hashlib
import hmac
import json
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
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
    return api_client.post(
        URL, body, format="json", HTTP_X_WIDGET_TOKEN=str(org.api_token)
    )


def _patch(api_client, org, session_id, **body):
    return api_client.patch(
        URL,
        body,
        format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
        HTTP_X_WIDGET_SESSION=str(session_id),
    )


def _session_updates(queries) -> list[str]:
    """Return the SET clause of every UPDATE on the session table."""
    return [
        query["sql"].split(" WHERE ")[0]
        for query in queries
        if query["sql"].startswith('UPDATE "tickets_widgetsession"')
    ]


def test_identified_session_creates_contact(api_client, org):
    res = _post(
        api_client,
        org,
        external_user_id="u1",
        user_hash=_sign("s3cret", "u1"),
        email="alice@startup.com",
        name="Alice",
    )
    assert res.status_code == 201
    session = WidgetSession.objects.get(id=res.data["session_id"])
    assert session.contact.external_id == "u1"
    assert session.contact.email == ""
    assert session.contact.declared_email == "alice@startup.com"
    assert session.contact.email_verified_at is None


def test_signed_email_verifies_contact(api_client, org):
    res = _post(
        api_client,
        org,
        external_user_id="u1",
        user_hash=_sign("s3cret", "u1"),
        email="alice@startup.com",
        email_hash=_sign("s3cret", "email:alice@startup.com"),
    )
    session = WidgetSession.objects.get(id=res.data["session_id"])
    assert session.email_verified_at is not None
    assert session.contact.email == "alice@startup.com"
    assert session.contact.email_verified_at is not None


def test_user_hash_of_the_email_does_not_prove_it(api_client, org):
    res = _post(
        api_client,
        org,
        email="alice@startup.com",
        email_hash=_sign("s3cret", "alice@startup.com"),
    )
    session = WidgetSession.objects.get(id=res.data["session_id"])
    assert session.email_verified_at is None


def test_forged_email_hash_is_ignored_not_rejected(api_client, org):
    res = _post(api_client, org, email="alice@startup.com", email_hash="forged")
    assert res.status_code == 201
    session = WidgetSession.objects.get(id=res.data["session_id"])
    assert session.email_verified_at is None


def test_company_is_stored_for_identified(api_client, org):
    res = _post(
        api_client,
        org,
        external_user_id="u2",
        user_hash=_sign("s3cret", "u2"),
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
        api_client,
        org,
        **identity,
        company=payload,
        company_hash=_sign("s3cret", "company\nc1\nNew\n"),
    )
    company.refresh_from_db()
    assert company.name == "New"


def test_numeric_company_id_can_be_signed(api_client, org):
    company = CompanyFactory(organization=org, external_id="42", name="Old")
    _post(
        api_client,
        org,
        external_user_id="u2",
        user_hash=_sign("s3cret", "u2"),
        company={"id": 42, "name": "New"},
        company_hash=_sign("s3cret", "company\n42\nNew\n"),
    )
    company.refresh_from_db()
    assert company.name == "New"


def test_company_with_a_newline_counts_as_unsigned(api_client, org):
    company = CompanyFactory(organization=org, external_id="c1", name="Old")
    res = _post(
        api_client,
        org,
        external_user_id="u2",
        user_hash=_sign("s3cret", "u2"),
        company={"id": "c1", "name": "New\n"},
        company_hash=_sign("s3cret", "company\nc1\nNew\n\n"),
    )
    assert res.status_code == 201
    company.refresh_from_db()
    assert company.name == "Old"


@pytest.mark.parametrize(
    "forged",
    [
        {"id": "c1", "name": "Forged", "domain": "real.io"},
        {"id": "c1", "name": "Real", "domain": "forged.io"},
        {"id": "c1", "name": "Real"},
    ],
)
def test_company_hash_cant_be_replayed_with_another_name_or_domain(
    api_client, org, forged
):
    company = CompanyFactory(organization=org, external_id="c1", name="Old", domain="")
    other = CompanyFactory(organization=org, external_id="other")
    contact = ContactFactory(organization=org, external_id="u2", company=other)
    res = _post(
        api_client,
        org,
        external_user_id="u2",
        user_hash=_sign("s3cret", "u2"),
        company=forged,
        company_hash=_sign("s3cret", "company\nc1\nReal\nreal.io"),
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
        api_client,
        org,
        **identity,
        company={"id": "c1", "name": "N", "traits": {"tier": "free"}},
        company_hash=_sign("s3cret", "company\nc1\nN\n"),
    )
    company.refresh_from_db()
    assert company.attributes == {"tier": "gold"}
    _post(
        api_client,
        org,
        **identity,
        company={"id": "c2", "name": "N", "traits": {"tier": "free"}},
        company_hash=_sign("s3cret", "company\nc2\nN\n"),
    )
    created = Company.objects.get(organization=org, external_id="c2")
    assert created.attributes == {"tier": "free"}


@pytest.mark.parametrize(
    "body",
    [
        {"email": ["a@x.io"]},
        {"email": 42},
        {"email": "x" * 250 + "@x.io"},
        {"email": "\ud800@x.io"},
        {"name": {"a": 1}},
        {"name": 42},
        {"name": "n" * 256},
        {"external_user_id": True, "user_hash": "x"},
        {"external_user_id": 1.5, "user_hash": "x"},
        {"external_user_id": 2**63, "user_hash": "x"},
        {"external_user_id": "x" * 256, "user_hash": "x"},
        {"external_user_id": "\ud800", "user_hash": "x"},
        {"name": "\ud800"},
        {"user_hash": ["x"]},
        {"email_hash": 1},
        {"email_hash": "é"},
        {"email_hash": "\ud800"},
        {"company_hash": {"a": 1}},
        {"company_hash": "x" * 129},
    ],
)
def test_malformed_identity_is_refused_before_touching_the_session(
    api_client, org, body
):
    # Raw JSON: DRF's test renderer can't encode the lone surrogates a real
    # request can carry as "\ud800" escapes.
    raw = {"data": json.dumps(body), "content_type": "application/json"}
    session = WidgetSession.objects.create(organization=org, email="a@x.io", name="A")
    res = api_client.patch(
        URL,
        **raw,
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
        HTTP_X_WIDGET_SESSION=str(session.id),
    )
    assert res.status_code == 400
    session.refresh_from_db()
    assert (session.email, session.name) == ("a@x.io", "A")
    res = api_client.post(URL, **raw, HTTP_X_WIDGET_TOKEN=str(org.api_token))
    assert res.status_code == 400
    assert WidgetSession.objects.filter(organization=org).count() == 1


@pytest.mark.parametrize("field", ["name", "email", "external_user_id", "user_hash"])
def test_deeply_nested_identity_field_is_a_400_not_a_crash(api_client, org, field):
    # CharField calls str() on its input, which overflows the stack on this.
    depth = 100_000
    raw = f'{{"{field}": {"[" * depth}1{"]" * depth}}}'
    res = api_client.post(
        URL,
        data=raw,
        content_type="application/json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
    )
    assert res.status_code == 400


@pytest.mark.parametrize("raw", ["[1, 2]", '"text"', "1"])
def test_body_that_isnt_an_object_is_a_400(api_client, org, raw):
    res = api_client.post(
        URL,
        data=raw,
        content_type="application/json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
    )
    assert res.status_code == 400


@pytest.mark.parametrize(
    "company",
    [
        {"id": "\ud800", "name": "C"},
        {"id": "c1", "name": "\ud800"},
        {"id": "c1", "name": "C", "domain": "\ud800"},
    ],
)
def test_lone_surrogate_in_a_signed_company_is_ignored_not_raised(
    api_client, org, company
):
    # ``company`` isn't an identity field: as with any invalid payload, the
    # widget goes on and the value counts as unsigned.
    body = {
        "external_user_id": "u2",
        "user_hash": _sign("s3cret", "u2"),
        "company": company,
        "company_hash": "a" * 64,
    }
    res = api_client.post(
        URL,
        json.dumps(body),
        content_type="application/json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
    )
    assert res.status_code == 201
    assert not Company.objects.filter(organization=org).exclude(name="C").exists()


@pytest.mark.parametrize("prefix", ["email:", "company\n"])
def test_external_id_that_could_double_as_another_hash_is_refused(
    api_client, org, prefix
):
    external_id = f"{prefix}alice@startup.com"
    res = _post(
        api_client,
        org,
        external_user_id=external_id,
        user_hash=_sign("s3cret", external_id),
    )
    assert res.status_code == 400
    assert not Contact.objects.filter(organization=org).exists()
    assert not WidgetSession.objects.filter(organization=org).exists()


def test_company_hash_cant_be_replayed_as_a_user_hash(api_client, org):
    message = "company\nc1\nAcme\n"
    res = _post(
        api_client, org, external_user_id=message, user_hash=_sign("s3cret", message)
    )
    assert res.status_code == 400


def test_a_colon_after_company_is_an_ordinary_external_id(api_client, org):
    # Nothing is signed with that prefix since company_hash moved to newlines.
    res = _post(
        api_client,
        org,
        external_user_id="company:7",
        user_hash=_sign("s3cret", "company:7"),
    )
    assert res.status_code == 201


def test_email_hash_cant_be_replayed_as_a_user_hash(api_client, org):
    email_hash = _sign("s3cret", "email:alice@startup.com")
    res = _post(
        api_client,
        org,
        external_user_id="email:alice@startup.com",
        user_hash=email_hash,
    )
    assert res.status_code == 400


@pytest.mark.parametrize("prefix", ["email:", "company\n"])
def test_ticket_history_refuses_reserved_external_ids(api_client, org, prefix):
    external_id = f"{prefix}alice@startup.com"
    res = api_client.get(
        "/api/v1/tickets/widget_tickets/",
        {"external_user_id": external_id, "user_hash": _sign("s3cret", external_id)},
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
    )
    assert res.status_code == 400


class TestRealClientPayloads:
    """What the widget and older integrations really send must keep working."""

    def test_empty_body(self, api_client, org):
        assert _post(api_client, org).status_code == 201

    def test_stored_session_id_only(self, api_client, org):
        session = WidgetSession.objects.create(organization=org)
        res = _post(api_client, org, session_id=str(session.id))
        assert res.status_code == 200
        assert res.data["session_id"] == str(session.id)

    @pytest.mark.parametrize(
        "field",
        [
            "session_id",
            "name",
            "email",
            "external_user_id",
            "user_hash",
            "email_hash",
            "company_hash",
            "company",
            "traits",
        ],
    )
    def test_null_field_on_post(self, api_client, org, field):
        assert _post(api_client, org, **{field: None}).status_code == 201

    def test_every_field_null_on_post(self, api_client, org):
        res = _post(
            api_client,
            org,
            session_id=None,
            name=None,
            email=None,
            external_user_id=None,
            user_hash=None,
            email_hash=None,
            company_hash=None,
            company=None,
            traits=None,
        )
        assert res.status_code == 201
        session = WidgetSession.objects.get(id=res.data["session_id"])
        assert (session.name, session.email, session.external_user_id) == ("", "", "")

    def test_null_fields_when_resuming(self, api_client, org):
        session = WidgetSession.objects.create(
            organization=org, external_user_id="u1", name="A", email="a@x.io"
        )
        res = _post(api_client, org, session_id=str(session.id), name=None, email=None)
        assert res.status_code == 200
        session.refresh_from_db()
        assert (session.name, session.email) == ("A", "a@x.io")

    def test_null_fields_on_an_hmac_user(self, api_client, org):
        res = _post(
            api_client,
            org,
            external_user_id="u1",
            user_hash=_sign("s3cret", "u1"),
            name=None,
            email=None,
            email_hash=None,
            company=None,
            company_hash=None,
        )
        assert res.status_code == 201
        assert WidgetSession.objects.get(id=res.data["session_id"]).name == ""

    def test_null_fields_on_patch_change_nothing(self, api_client, org):
        session = WidgetSession.objects.create(
            organization=org, name="A", email="a@x.io"
        )
        res = _patch(
            api_client, org, session.id, name=None, email=None, email_hash=None
        )
        assert res.status_code == 200
        session.refresh_from_db()
        assert (session.name, session.email) == ("A", "a@x.io")

    @pytest.mark.parametrize("email", ["a@b", "not-an-email", "a b@x.io"])
    def test_contact_nudge_with_an_email_the_widget_lets_through(
        self, api_client, org, email
    ):
        # The form only checks for an "@", and doesn't look at the response.
        session = WidgetSession.objects.create(organization=org)
        res = _patch(api_client, org, session.id, name="Bob", email=email)
        assert res.status_code == 200
        session.refresh_from_db()
        assert (session.name, session.email) == ("Bob", email)
        assert session.contact is None
        assert not Contact.objects.filter(organization=org).exists()

    def test_host_page_email_that_isnt_one_doesnt_break_init(self, api_client, org):
        res = _post(api_client, org, email="not-an-email", name="Bob")
        assert res.status_code == 201
        session = WidgetSession.objects.get(id=res.data["session_id"])
        assert session.name == "Bob"
        assert session.contact is None

    def test_invalid_email_on_an_hmac_user_creates_no_declared_email(
        self, api_client, org
    ):
        res = _post(
            api_client,
            org,
            external_user_id="u1",
            user_hash=_sign("s3cret", "u1"),
            email="not-an-email",
        )
        assert res.status_code == 201
        contact = WidgetSession.objects.get(id=res.data["session_id"]).contact
        assert contact.declared_email == ""

    def test_numeric_user_id_with_its_hash(self, api_client, org):
        # init({user: {id: 42}}) from plain JavaScript.
        res = _post(
            api_client, org, external_user_id=42, user_hash=_sign("s3cret", "42")
        )
        assert res.status_code == 201
        assert res.data["external_user_id"] == "42"
        contact = WidgetSession.objects.get(id=res.data["session_id"]).contact
        assert contact.external_id == "42"

    def test_numeric_user_id_resumes_its_own_session(self, api_client, org):
        session = WidgetSession.objects.create(organization=org, external_user_id="42")
        res = _post(
            api_client,
            org,
            session_id=str(session.id),
            external_user_id=42,
            user_hash=_sign("s3cret", "42"),
        )
        assert res.status_code == 200
        assert res.data["session_id"] == str(session.id)

    def test_numeric_user_id_without_hash_stays_anonymous(self, api_client, org):
        res = _post(api_client, org, external_user_id=42)
        assert res.status_code == 201
        assert res.data["external_user_id"] == ""

    def test_numeric_user_id_with_a_wrong_hash(self, api_client, org):
        res = _post(api_client, org, external_user_id=42, user_hash="forged")
        assert res.status_code == 403

    def test_whitespace_around_the_email_is_dropped(self, api_client, org):
        res = _post(api_client, org, email="  bob@x.io ")
        session = WidgetSession.objects.get(id=res.data["session_id"])
        assert session.email == "bob@x.io"
        assert session.contact.email == "bob@x.io"

    @pytest.mark.parametrize("session_id", ["not-a-uuid", 1.5, {"a": 1}, ["x"]])
    def test_stored_session_id_that_isnt_one_starts_a_new_session(
        self, api_client, org, session_id
    ):
        res = _post(api_client, org, session_id=session_id)
        assert res.status_code == 201

    def test_session_header_that_isnt_a_uuid_is_a_401(self, api_client, org):
        res = _patch(api_client, org, "not-a-uuid", name="Bob")
        assert res.status_code == 401


@pytest.mark.parametrize("resume_by", ["session_id", "external_user_id"])
def test_resume_writes_only_what_changed(api_client, org, resume_by):
    """A full save would restore personal data wiped by a concurrent anonymization."""
    session = WidgetSession.objects.create(
        organization=org, external_user_id="u1", name="", email=""
    )
    body = {"session_id": str(session.id)} if resume_by == "session_id" else {}
    with CaptureQueriesContext(connection) as queries:
        res = _post(
            api_client,
            org,
            external_user_id="u1",
            user_hash=_sign("s3cret", "u1"),
            name="Alice",
            **body,
        )
    assert res.status_code == 200
    updates = _session_updates(queries)
    assert updates
    assert any('"name"' in sql for sql in updates)
    for sql in updates:
        assert '"external_user_id"' not in sql
        assert '"email_verified_at"' not in sql
        assert '"email"' not in sql


def test_resume_still_records_the_visit(api_client, org):
    session = WidgetSession.objects.create(organization=org)
    before = session.last_seen_at
    _post(api_client, org, session_id=str(session.id))
    session.refresh_from_db()
    assert session.last_seen_at > before


def test_patch_writes_only_the_fields_it_was_given(api_client, org):
    session = WidgetSession.objects.create(organization=org, email="a@x.io")
    with CaptureQueriesContext(connection) as queries:
        _patch(api_client, org, session.id, name="Bob")
    updates = _session_updates(queries)
    assert any('"name"' in sql for sql in updates)
    assert not any('"email"' in sql for sql in updates)


def test_contact_nudge_links_the_tickets_already_opened(api_client, org):
    session_id = _post(api_client, org).data["session_id"]
    api_client.post(
        "/api/v1/tickets/widget_message/",
        {"body": "Help"},
        format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
        HTTP_X_WIDGET_SESSION=session_id,
    )
    ticket = Ticket.objects.get(widget_session_id=session_id)
    assert ticket.contact is None
    _patch(api_client, org, session_id, email="bob@x.io")
    ticket.refresh_from_db()
    assert ticket.contact.email == "bob@x.io"


def test_linking_leaves_a_ticket_with_a_contact_alone(api_client, org):
    other = ContactFactory(organization=org)
    session_id = _post(api_client, org).data["session_id"]
    ticket = TicketFactory(
        organization=org, widget_session_id=session_id, contact=other
    )
    _patch(api_client, org, session_id, email="bob@x.io")
    ticket.refresh_from_db()
    assert ticket.contact == other


def test_patch_changing_the_email_clears_its_verification(api_client, org):
    res = _post(
        api_client,
        org,
        email="alice@x.io",
        email_hash=_sign("s3cret", "email:alice@x.io"),
    )
    session_id = res.data["session_id"]
    _patch(api_client, org, session_id, email="ALICE@x.io")
    assert WidgetSession.objects.get(id=session_id).email_verified_at is not None
    _patch(api_client, org, session_id, email="other@x.io")
    assert WidgetSession.objects.get(id=session_id).email_verified_at is None


def test_patch_can_prove_the_email_it_sets(api_client, org):
    session_id = _post(api_client, org).data["session_id"]
    _patch(
        api_client,
        org,
        session_id,
        email="alice@x.io",
        email_hash=_sign("s3cret", "email:alice@x.io"),
    )
    session = WidgetSession.objects.get(id=session_id)
    assert session.email_verified_at is not None
    assert session.contact.email_verified_at is not None


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
    _patch(api_client, org, session_id, email="bob@x.io")
    assert WidgetSession.objects.get(id=session_id).contact.email == "bob@x.io"


def test_resume_links_contact(api_client, org):
    session = WidgetSession.objects.create(organization=org, email="bob@x.io")
    _post(api_client, org, session_id=str(session.id))
    session.refresh_from_db()
    assert session.contact.email == "bob@x.io"


def test_first_widget_message_links_ticket_to_contact(api_client, org):
    session_id = _post(
        api_client, org, external_user_id="u3", user_hash=_sign("s3cret", "u3")
    ).data["session_id"]
    api_client.post(
        "/api/v1/tickets/widget_message/",
        {"body": "Help"},
        format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
        HTTP_X_WIDGET_SESSION=session_id,
    )
    assert Ticket.objects.get(widget_session_id=session_id).contact.external_id == "u3"


def test_first_attachment_links_ticket_to_contact(api_client, org, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
    session_id = _post(
        api_client, org, external_user_id="u3", user_hash=_sign("s3cret", "u3")
    ).data["session_id"]
    res = api_client.post(
        "/api/v1/tickets/widget_message_attachment/",
        {"file": SimpleUploadedFile("a.txt", b"x"), "body_type": "file"},
        format="multipart",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
        HTTP_X_WIDGET_SESSION=session_id,
    )
    assert res.status_code == 201
    assert Ticket.objects.get(widget_session_id=session_id).contact.external_id == "u3"


def _submit(api_client, org, **overrides):
    payload = {
        "title": "Bug",
        "description": "Broken",
        "requester_name": "Carol",
        "requester_email": "carol@x.io",
        **overrides,
    }
    return api_client.post(
        "/api/v1/tickets/widget_submit/",
        payload,
        format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
    )


def test_widget_submit_links_contact_by_email(api_client, org):
    ContactFactory(organization=org, email="carol@x.io")
    res = _submit(api_client, org)
    assert res.status_code == 201
    assert Ticket.objects.get(id=res.data["id"]).contact.email == "carol@x.io"
    assert Contact.objects.filter(organization=org).count() == 1


def test_widget_submit_creates_the_contact(api_client, org):
    res = _submit(api_client, org)
    contact = Ticket.objects.get(id=res.data["id"]).contact
    assert (contact.email, contact.name) == ("carol@x.io", "Carol")


def test_widget_submit_doesnt_link_an_anonymized_contact(api_client, org):
    ContactFactory(organization=org, email="carol@x.io", is_anonymized=True)
    res = _submit(api_client, org)
    assert res.status_code == 201
    assert Ticket.objects.get(id=res.data["id"]).contact is None


def test_database_error_never_loses_a_submitted_ticket(api_client, org):
    with mock.patch(
        "apps.tickets.views.resolve_contact_for_email", side_effect=OperationalError
    ):
        res = _submit(api_client, org)
    assert res.status_code == 201
    assert Ticket.objects.get(id=res.data["id"]).contact is None
