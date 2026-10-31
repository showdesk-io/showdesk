"""``audit_tenant_links`` reports links across organizations, and changes nothing."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.tickets.models import WidgetSession
from tests.factories import (
    AdminFactory,
    ArticleFactory,
    CategoryFactory,
    CompanyFactory,
    ContactFactory,
    EndUserFactory,
    OrganizationFactory,
    SLAPolicyFactory,
    TagFactory,
    TeamFactory,
    TicketAttachmentFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def _audit() -> str:
    out = StringIO()
    call_command("audit_tenant_links", stdout=out)
    return out.getvalue()


def _section(output: str, name: str) -> list[str]:
    """Return the count and the indented ids listed under ``name``."""
    lines = output.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith(f"{name}:"))
    ids = []
    for line in lines[index + 1 :]:
        if not line.startswith("  "):
            break
        ids.append(line.strip())
    assert int(lines[index].split(":")[1]) == len(ids)
    return ids


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def other():
    return OrganizationFactory()


def _ticket(org, **links):
    return TicketFactory(organization=org, **{"requester": None, **links})


@pytest.mark.parametrize(
    ("section", "link", "make"),
    [
        ("ticket.assigned_agent", "assigned_agent", UserFactory),
        ("ticket.requester", "requester", EndUserFactory),
        ("ticket.assigned_team", "assigned_team", TeamFactory),
        ("ticket.sla_policy", "sla_policy", SLAPolicyFactory),
    ],
    ids=["agent", "requester", "team", "sla"],
)
def test_ticket_foreign_keys(org, other, section, link, make) -> None:
    clean = _ticket(org, **{link: make(organization=org)})
    bad = _ticket(org, **{link: make(organization=other)})
    ids = _section(_audit(), section)
    assert ids == [str(bad.id)]
    assert str(clean.id) not in ids


def test_a_link_to_a_user_with_no_organization_is_reported(org) -> None:
    bad = _ticket(org, assigned_agent=UserFactory(organization=None))
    assert _section(_audit(), "ticket.assigned_agent") == [str(bad.id)]


def test_ticket_tags(org, other) -> None:
    clean = _ticket(org)
    clean.tags.add(TagFactory(organization=org))
    bad = _ticket(org)
    tag = TagFactory(organization=other)
    bad.tags.add(tag)
    assert _section(_audit(), "ticket.tags") == [f"{bad.id} {tag.id}"]


def test_team_lead_and_members(org, other) -> None:
    own = UserFactory(organization=org)
    foreign = UserFactory(organization=other)
    clean = TeamFactory(organization=org, lead=own)
    clean.members.add(own)
    bad = TeamFactory(organization=org, lead=foreign)
    bad.members.add(foreign)

    output = _audit()
    assert _section(output, "team.lead") == [str(bad.id)]
    assert _section(output, "team.members") == [f"{bad.id} {foreign.id}"]


def test_article_category_and_author(org, other) -> None:
    ArticleFactory(
        organization=org,
        category=CategoryFactory(organization=org),
        author=UserFactory(organization=org),
    )
    bad = ArticleFactory(
        organization=org,
        category=CategoryFactory(organization=other),
        author=UserFactory(organization=other),
    )
    output = _audit()
    assert _section(output, "article.category") == [str(bad.id)]
    assert _section(output, "article.author") == [str(bad.id)]


def test_contact_links(org, other) -> None:
    contact = ContactFactory(organization=other)
    ticket = _ticket(org, contact=contact)
    session = WidgetSession.objects.create(organization=org, contact=contact)
    linked = ContactFactory(
        organization=org, company=CompanyFactory(organization=other)
    )
    # The same links inside an organization aren't reported.
    own = ContactFactory(organization=org, company=CompanyFactory(organization=org))
    _ticket(org, contact=own)
    WidgetSession.objects.create(organization=org, contact=own)

    output = _audit()
    assert _section(output, "ticket.contact") == [str(ticket.id)]
    assert _section(output, "widget_session.contact") == [str(session.id)]
    assert _section(output, "contact.company") == [str(linked.id)]


def test_message_authors(org, other) -> None:
    ticket = _ticket(org)
    TicketMessageFactory(ticket=ticket, author=None)
    TicketMessageFactory(ticket=ticket, author=UserFactory(organization=org))
    # Only staff authors count: superusers impersonate, end users are widget users.
    TicketMessageFactory(
        ticket=ticket, author=UserFactory(organization=other, is_superuser=True)
    )
    TicketMessageFactory(ticket=ticket, author=EndUserFactory(organization=other))
    agent = TicketMessageFactory(ticket=ticket, author=UserFactory(organization=other))
    admin = TicketMessageFactory(ticket=ticket, author=AdminFactory(organization=other))
    assert _section(_audit(), "ticket_message.author") == sorted(
        [str(agent.id), str(admin.id)]
    )


def test_attachment_message(org) -> None:
    ticket = _ticket(org)
    TicketAttachmentFactory(ticket=ticket, uploaded_by=None)
    TicketAttachmentFactory(
        ticket=ticket,
        uploaded_by=None,
        message=TicketMessageFactory(ticket=ticket, author=None),
    )
    bad = TicketAttachmentFactory(
        ticket=ticket,
        uploaded_by=None,
        message=TicketMessageFactory(ticket=_ticket(org), author=None),
    )
    assert _section(_audit(), "ticket_attachment.message") == [str(bad.id)]


def test_superusers_with_an_organization_are_counted_without_ids(org) -> None:
    UserFactory(organization=None, is_superuser=True)
    user = UserFactory(organization=org, is_superuser=True)
    output = _audit()
    assert "superusers_with_organization: 1\n" in output
    assert str(user.id) not in output


def test_a_clean_database_reports_zero_everywhere(org) -> None:
    _ticket(org, assigned_agent=UserFactory(organization=org))
    output = _audit()
    assert "cross_org_links: 0\n" in output
    assert "superusers_with_organization: 0\n" in output


def test_it_exits_cleanly_and_totals_with_links(org, other) -> None:
    _ticket(org, assigned_agent=UserFactory(organization=other))
    _ticket(org, assigned_team=TeamFactory(organization=other))
    assert "cross_org_links: 2\n" in _audit()


def test_it_prints_no_personal_data(org, other) -> None:
    agent = UserFactory(
        organization=other,
        email="private@test.example",
        first_name="Privatefirst",
        last_name="Privatelast",
    )
    ticket = _ticket(org, assigned_agent=agent)
    ticket.title = "Private title"
    ticket.save()
    output = _audit()
    for private in ("private@", "Privatefirst", "Privatelast", "Private title"):
        assert private not in output


def test_it_only_reads(org, other) -> None:
    _ticket(org, assigned_agent=UserFactory(organization=other))
    with CaptureQueriesContext(connection) as queries:
        _audit()
    assert queries
    statements = [query["sql"].lstrip().upper() for query in queries]
    assert all(statement.startswith("SELECT") for statement in statements), statements
