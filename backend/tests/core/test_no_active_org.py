"""A user with no organization reaches no rows, and gets clean errors."""

import pytest
from rest_framework.test import APIClient

from apps.tickets.models import Tag, Ticket
from tests.factories import (
    ArticleFactory,
    OrganizationFactory,
    TagFactory,
    TicketFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> APIClient:
    client = APIClient()
    client.force_authenticate(user=UserFactory(organization=None, role="admin"))
    return client


@pytest.fixture
def foreign_ticket():
    return TicketFactory(organization=OrganizationFactory(), requester=None)


@pytest.mark.parametrize(
    "path",
    [
        "tickets",
        "messages",
        "attachments",
        "videos",
        "tags",
        "priorities",
        "saved-views",
        "canned-responses",
        "teams",
        "users",
        "kb/categories",
        "kb/articles",
        "organization-domains",
        "join-requests",
        "organizations",
    ],
)
def test_lists_are_empty(client, foreign_ticket, path) -> None:
    res = client.get(f"/api/v1/{path}/")
    assert res.status_code == 200
    assert res.data["count"] == 0


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("tickets", {"title": "t"}),
        ("tags", {"name": "n"}),
        ("priorities", {"name": "n", "slug": "n"}),
        ("saved-views", {"name": "n", "filters": {}}),
        ("canned-responses", {"name": "n", "body": "b"}),
        ("teams", {"name": "n"}),
        ("users", {"email": "n@test.example"}),
        ("kb/categories", {"name": "n", "slug": "n"}),
        ("kb/articles", {"title": "n", "slug": "n", "body": "b"}),
        ("organization-domains", {"domain": "a.example", "is_branding": True}),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_creates_are_a_400(client, path, body) -> None:
    res = client.post(f"/api/v1/{path}/", body, format="json")
    assert res.status_code == 400, res.data


def test_foreign_ticket_is_refused(client, foreign_ticket) -> None:
    res = client.post(
        "/api/v1/messages/",
        {"ticket": str(foreign_ticket.id), "body": "hi"},
        format="json",
    )
    assert res.status_code == 400
    assert not foreign_ticket.messages.exists()


def test_rows_with_no_organization_are_not_created(client) -> None:
    client.post("/api/v1/tags/", {"name": "n"}, format="json")
    client.post("/api/v1/tickets/", {"title": "t"}, format="json")
    assert not Tag.objects.exists()
    assert not Ticket.objects.exists()


def test_other_org_tags_stay_out_of_reach(client) -> None:
    tag = TagFactory(organization=OrganizationFactory())
    assert client.get(f"/api/v1/tags/{tag.id}/").status_code == 404


@pytest.mark.parametrize("action", ["helpful", "not_helpful"])
def test_anonymous_article_feedback_reaches_no_article(api_client, action) -> None:
    article = ArticleFactory(organization=OrganizationFactory())
    res = api_client.post(f"/api/v1/kb/articles/{article.id}/{action}/")
    assert res.status_code == 404
    article.refresh_from_db()
    assert article.helpful_count == article.not_helpful_count == 0
