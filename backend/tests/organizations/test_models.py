"""Tests for organization models."""

import hashlib
import hmac

import pytest

from tests.factories import OrganizationFactory, TeamFactory, UserFactory


@pytest.mark.django_db
class TestOrganization:
    """Tests for the Organization model."""

    def test_create_organization(self) -> None:
        """Test basic organization creation."""
        org = OrganizationFactory(name="Acme Corp", slug="acme-corp")
        assert org.name == "Acme Corp"
        assert org.slug == "acme-corp"
        assert org.is_active is True
        assert org.api_token is not None

    def test_organization_str(self) -> None:
        """Test string representation."""
        org = OrganizationFactory(name="Test Co")
        assert str(org) == "Test Co"

    def test_next_ticket_reference_increments(self) -> None:
        """Test that ticket references increment atomically."""
        org = OrganizationFactory()
        ref1 = org.next_ticket_reference()
        ref2 = org.next_ticket_reference()
        ref3 = org.next_ticket_reference()
        assert ref1 == "SD-0001"
        assert ref2 == "SD-0002"
        assert ref3 == "SD-0003"

    def test_next_ticket_reference_unique_across_calls(self) -> None:
        """Test that references are always unique."""
        org = OrganizationFactory()
        refs = {org.next_ticket_reference() for _ in range(20)}
        assert len(refs) == 20


@pytest.mark.django_db
class TestUser:
    """Tests for the custom User model."""

    def test_create_user(self) -> None:
        """Test user creation with email as username."""
        user = UserFactory(email="test@example.com")
        assert user.email == "test@example.com"
        assert user.check_password("testpass123")

    def test_is_agent_property(self) -> None:
        """Test the is_agent property for different roles."""
        agent = UserFactory(role="agent")
        admin = UserFactory(role="admin")
        end_user = UserFactory(role="end_user")
        assert agent.is_agent is True
        assert admin.is_agent is True
        assert end_user.is_agent is False

    def test_user_str(self) -> None:
        """Test string representation."""
        user = UserFactory(email="hello@test.com")
        assert str(user) == "hello@test.com"


@pytest.mark.django_db
class TestTeam:
    """Tests for the Team model."""

    def test_create_team(self) -> None:
        """Test team creation."""
        team = TeamFactory(name="Support")
        assert team.name == "Support"
        assert team.organization is not None

    def test_team_members(self) -> None:
        """Test adding members to a team."""
        org = OrganizationFactory()
        team = TeamFactory(organization=org)
        agents = UserFactory.create_batch(3, organization=org)
        team.members.set(agents)
        assert team.members.count() == 3


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


@pytest.mark.django_db
@pytest.mark.parametrize("message", ["email:a@b.io", "company\nc1\nA\n"])
def test_verify_user_hash_refuses_a_message_of_another_hash(message):
    org = OrganizationFactory(widget_secret="s3cret")
    assert not org.verify_user_hash(message, _sign(message.encode()))
