"""No route returns, changes or deletes a row of another organization."""

from collections.abc import Callable

import pytest

from apps.organizations.models import OrganizationDomain, OrgJoinRequest
from tests.factories import (
    ArticleFactory,
    CannedResponseFactory,
    CategoryFactory,
    OrganizationFactory,
    PriorityLevelFactory,
    SavedViewFactory,
    SLAPolicyFactory,
    TagFactory,
    TeamFactory,
    TicketAttachmentFactory,
    TicketFactory,
    TicketMessageFactory,
    UserFactory,
    VideoRecordingFactory,
)

pytestmark = pytest.mark.django_db


def _shared(factory: Callable) -> Callable:
    """A row that the org's agents can all read."""

    def build(org, agent):
        return factory(organization=org, created_by=agent, is_shared=True)

    return build


def _of_ticket(factory: Callable, **extra) -> Callable:
    def build(org, agent):
        ticket = TicketFactory(organization=org, requester=None)
        return factory(ticket=ticket, **extra)

    return build


def _of_org(factory: Callable) -> Callable:
    def build(org, agent):
        return factory(organization=org)

    return build


ROUTES = {
    "tickets": lambda org, agent: TicketFactory(organization=org, requester=None),
    "messages": _of_ticket(TicketMessageFactory, author=None),
    "attachments": _of_ticket(TicketAttachmentFactory, uploaded_by=None),
    "videos": _of_ticket(VideoRecordingFactory),
    "tags": _of_org(TagFactory),
    "priorities": _of_org(PriorityLevelFactory),
    "sla-policies": _of_org(SLAPolicyFactory),
    "saved-views": _shared(SavedViewFactory),
    "canned-responses": _shared(CannedResponseFactory),
    "teams": _of_org(TeamFactory),
    "users": _of_org(UserFactory),
    "kb/categories": _of_org(CategoryFactory),
    "kb/articles": _of_org(ArticleFactory),
    "organization-domains": lambda org, agent: OrganizationDomain.objects.create(
        organization=org, domain=f"d{org.id.hex}.example", is_branding=True
    ),
    "join-requests": lambda org, agent: OrgJoinRequest.objects.create(
        organization=org, email=f"j{org.id.hex}@test.example", full_name="J"
    ),
}


@pytest.fixture
def foreign_agent():
    return UserFactory(organization=OrganizationFactory())


@pytest.mark.parametrize("path", ROUTES)
def test_list_and_retrieve_stay_in_the_organization(
    admin_client, organization, agent, foreign_agent, path
) -> None:
    own = ROUTES[path](organization, agent)
    foreign = ROUTES[path](foreign_agent.organization, foreign_agent)

    ids = {
        str(row["id"]) for row in admin_client.get(f"/api/v1/{path}/").data["results"]
    }
    assert str(own.id) in ids
    assert str(foreign.id) not in ids

    assert admin_client.get(f"/api/v1/{path}/{own.id}/").status_code == 200
    assert admin_client.get(f"/api/v1/{path}/{foreign.id}/").status_code == 404


@pytest.mark.parametrize("path", [p for p in ROUTES if p != "join-requests"])
def test_update_and_delete_stay_in_the_organization(
    admin_client, agent, foreign_agent, path
) -> None:
    foreign = ROUTES[path](foreign_agent.organization, foreign_agent)
    url = f"/api/v1/{path}/{foreign.id}/"

    assert admin_client.patch(url, {}, format="multipart").status_code == 404
    assert admin_client.delete(url).status_code == 404
    foreign.refresh_from_db()


def test_organizations_only_list_the_active_one(
    authenticated_client, organization, foreign_agent
) -> None:
    res = authenticated_client.get("/api/v1/organizations/")
    assert [row["id"] for row in res.data["results"]] == [str(organization.id)]
    foreign_url = f"/api/v1/organizations/{foreign_agent.organization.id}/"
    assert authenticated_client.get(foreign_url).status_code == 404
    assert authenticated_client.delete(foreign_url).status_code == 404


def test_platform_routes_refuse_tenants(authenticated_client) -> None:
    res = authenticated_client.get("/api/v1/platform/organizations/")
    assert res.status_code == 403


def test_ticket_stats_stay_in_the_organization(
    authenticated_client, organization, foreign_agent
) -> None:
    TicketFactory(organization=organization, requester=None)
    TicketFactory(organization=foreign_agent.organization, requester=None)
    res = authenticated_client.get("/api/v1/tickets/stats/")
    assert res.data["total"] == 1
