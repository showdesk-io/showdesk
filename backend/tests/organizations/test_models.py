"""Tests for organization models."""

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
