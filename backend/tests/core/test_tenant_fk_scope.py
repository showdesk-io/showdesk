"""Ids in request bodies only reach rows of the active organization.

Each route of ``CASES`` is called three ways with the same payload shape: with
ids of the caller's organization (accepted), of another organization, and
unknown ids (refused with the same response, so that ids can't be told apart).

``test_every_writable_relation_is_org_scoped`` extends this to the relations of
all serializers. It can't see ids that a view reads from the body itself, such
as in ``bulk_update``: those need their own tests.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import get_resolver
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.core.serializers import OrgScopedPrimaryKeyRelatedField
from apps.knowledge_base.models import Article, Category
from apps.organizations.models import Team, User
from apps.organizations.serializers import TeamSerializer
from apps.tickets.models import Ticket, TicketAttachment, TicketMessage
from apps.tickets.serializers import TicketAssignSerializer, TicketSerializer
from apps.videos.models import VideoRecording
from tests.factories import (
    ArticleFactory,
    CategoryFactory,
    OrganizationFactory,
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
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _refs(org) -> SimpleNamespace:
    """One row of each kind a request body can point at, in ``org``."""
    ticket = TicketFactory(organization=org, requester=None)
    return SimpleNamespace(
        org=org,
        ticket=ticket,
        message=TicketMessageFactory(ticket=ticket, author=None),
        attachment=TicketAttachmentFactory(ticket=ticket, uploaded_by=None),
        video=VideoRecordingFactory(ticket=ticket),
        user=UserFactory(organization=org),
        team=TeamFactory(organization=org),
        tag=TagFactory(organization=org),
        sla=SLAPolicyFactory(organization=org),
        category=CategoryFactory(organization=org),
        article=ArticleFactory(organization=org),
    )


def _unknown_refs() -> SimpleNamespace:
    names = ["ticket", "message", "user", "team", "tag", "sla", "category"]
    return SimpleNamespace(
        **{name: SimpleNamespace(id=uuid.uuid4()) for name in names},
    )


@pytest.fixture
def own(organization) -> SimpleNamespace:
    return _refs(organization)


@pytest.fixture
def foreign() -> SimpleNamespace:
    return _refs(OrganizationFactory())


def _file() -> SimpleUploadedFile:
    return SimpleUploadedFile("a.webm", b"x", content_type="video/webm")


def _attachment(ticket_id, message_id=None) -> dict:
    body = {
        "ticket": str(ticket_id),
        "file": _file(),
        "filename": "a.webm",
        "content_type": "video/webm",
        "file_size": 1,
    }
    return {**body, "message": str(message_id)} if message_id else body


def _new_ticket(org, **extra) -> dict:
    # `organization` is what the API required before it became server-set.
    return {"title": "t", "organization": str(org.id), **extra}


@dataclass
class Case:
    """A route taking ids: ``path(own)`` and ``body(own, target)``."""

    name: str
    method: str
    path: Callable
    body: Callable
    multipart: bool = False


TICKET_FKS = {
    "assigned_agent": lambda t: str(t.user.id),
    "assigned_team": lambda t: str(t.team.id),
    "requester": lambda t: str(t.user.id),
    "sla_policy": lambda t: str(t.sla.id),
    "tag_ids": lambda t: [str(t.tag.id)],
}

CASES = [
    Case(
        "message-create",
        "post",
        lambda o: "messages/",
        lambda o, t: {"ticket": str(t.ticket.id), "body": "hi"},
    ),
    Case(
        "message-update",
        "patch",
        lambda o: f"messages/{o.message.id}/",
        lambda o, t: {"ticket": str(t.ticket.id)},
    ),
    Case(
        "attachment-create-ticket",
        "post",
        lambda o: "attachments/",
        lambda o, t: _attachment(t.ticket.id),
        multipart=True,
    ),
    Case(
        "attachment-create-message",
        "post",
        lambda o: "attachments/",
        lambda o, t: _attachment(o.ticket.id, t.message.id),
        multipart=True,
    ),
    Case(
        "attachment-update-ticket",
        "patch",
        lambda o: f"attachments/{o.attachment.id}/",
        lambda o, t: {"ticket": str(t.ticket.id)},
    ),
    Case(
        "attachment-update-message",
        "patch",
        lambda o: f"attachments/{o.attachment.id}/",
        lambda o, t: {"message": str(t.message.id)},
    ),
    Case(
        "video-create",
        "post",
        lambda o: "videos/",
        lambda o, t: {"ticket": str(t.ticket.id), "original_file": _file()},
        multipart=True,
    ),
    Case(
        "video-update",
        "patch",
        lambda o: f"videos/{o.video.id}/",
        lambda o, t: {"ticket": str(t.ticket.id)},
        multipart=True,
    ),
    Case(
        "ticket-create",
        "post",
        lambda o: "tickets/",
        lambda o, t: _new_ticket(o.org, assigned_agent=str(t.user.id)),
    ),
    *[
        Case(
            f"ticket-update-{field}",
            "patch",
            lambda o: f"tickets/{o.ticket.id}/",
            lambda o, t, field=field, value=value: {field: value(t)},
        )
        for field, value in TICKET_FKS.items()
    ],
    Case(
        "ticket-assign-agent",
        "post",
        lambda o: f"tickets/{o.ticket.id}/assign/",
        lambda o, t: {"agent_id": str(t.user.id)},
    ),
    Case(
        "ticket-assign-team",
        "post",
        lambda o: f"tickets/{o.ticket.id}/assign/",
        lambda o, t: {"team_id": str(t.team.id)},
    ),
    Case(
        "ticket-set-tags",
        "post",
        lambda o: f"tickets/{o.ticket.id}/set_tags/",
        lambda o, t: {"tag_ids": [str(t.tag.id)]},
    ),
    Case(
        "team-create-lead",
        "post",
        lambda o: "teams/",
        lambda o, t: {
            "name": "n",
            "organization": str(o.org.id),
            "lead": str(t.user.id),
        },
    ),
    Case(
        "team-create-members",
        "post",
        lambda o: "teams/",
        lambda o, t: {
            "name": "n",
            "organization": str(o.org.id),
            "member_ids": [str(t.user.id)],
        },
    ),
    Case(
        "team-update-lead",
        "patch",
        lambda o: f"teams/{o.team.id}/",
        lambda o, t: {"lead": str(t.user.id)},
    ),
    Case(
        "team-update-members",
        "patch",
        lambda o: f"teams/{o.team.id}/",
        lambda o, t: {"member_ids": [str(t.user.id)]},
    ),
    Case(
        "article-create-category",
        "post",
        lambda o: "kb/articles/",
        lambda o, t: {
            "organization": str(o.org.id),
            "category": str(t.category.id),
            "title": "a",
            "slug": "a",
            "body": "b",
        },
    ),
    Case(
        "article-update-category",
        "patch",
        lambda o: f"kb/articles/{o.article.id}/",
        lambda o, t: {"category": str(t.category.id)},
    ),
]
CASE_IDS = [case.name for case in CASES]


def _call(client, case: Case, own, target):
    return getattr(client, case.method)(
        f"/api/v1/{case.path(own)}",
        case.body(own, target),
        format="multipart" if case.multipart else "json",
    )


def _without_ids(response) -> str:
    return UUID_RE.sub("<id>", str(response.data))


@pytest.mark.usefixtures("local_media")
class TestRoutesTakingIds:
    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_same_org_id_is_accepted(self, admin_client, own, case) -> None:
        res = _call(admin_client, case, own, own)
        assert res.status_code in (200, 201), res.data

    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_other_org_id_is_refused_like_an_unknown_id(
        self, admin_client, own, foreign, case
    ) -> None:
        res = _call(admin_client, case, own, foreign)
        assert res.status_code == 400, f"cross-org write got {res.status_code}"

        unknown = _call(admin_client, case, own, _unknown_refs())
        assert unknown.status_code == 400
        assert _without_ids(res) == _without_ids(unknown)


class TestBulkUpdate:
    URL = "/api/v1/tickets/bulk_update/"

    def test_other_org_tickets_are_left_alone(
        self, authenticated_client, own, foreign
    ) -> None:
        res = authenticated_client.post(
            self.URL,
            {"ids": [str(own.ticket.id), str(foreign.ticket.id)], "priority": "high"},
            format="json",
        )
        assert res.status_code == 200
        assert res.data["ids"] == [str(own.ticket.id)]
        foreign.ticket.refresh_from_db()
        assert foreign.ticket.priority != "high"

    def test_other_org_agent_is_refused_like_an_unknown_one(
        self, authenticated_client, own, foreign
    ) -> None:
        foreign.user.role = User.Role.AGENT
        foreign.user.save()
        responses = [
            authenticated_client.post(
                self.URL,
                {"ids": [str(own.ticket.id)], "assigned_agent_id": str(agent_id)},
                format="json",
            )
            for agent_id in (foreign.user.id, uuid.uuid4())
        ]
        assert [res.status_code for res in responses] == [400, 400]
        assert responses[0].data == responses[1].data

    def test_same_org_agent_is_accepted(self, authenticated_client, own) -> None:
        own.user.role = User.Role.AGENT
        own.user.save()
        res = authenticated_client.post(
            self.URL,
            {"ids": [str(own.ticket.id)], "assigned_agent_id": str(own.user.id)},
            format="json",
        )
        assert res.status_code == 200
        own.ticket.refresh_from_db()
        assert own.ticket.assigned_agent == own.user

    @pytest.mark.parametrize(
        "body",
        [
            {"ids": ["nope"], "priority": "high"},
            {"ids": ["00000000-0000-0000-0000-000000000000"], "assigned_agent_id": "x"},
        ],
    )
    def test_malformed_ids_are_a_400(self, authenticated_client, body) -> None:
        res = authenticated_client.post(self.URL, body, format="json")
        assert res.status_code == 400


class TestMalformedIdsInActions:
    def test_assign(self, authenticated_client, own) -> None:
        res = authenticated_client.post(
            f"/api/v1/tickets/{own.ticket.id}/assign/",
            {"agent_id": "nope"},
            format="json",
        )
        assert res.status_code == 400

    @pytest.mark.parametrize("tag_ids", [["nope"], "nope"])
    def test_set_tags(self, authenticated_client, own, tag_ids) -> None:
        res = authenticated_client.post(
            f"/api/v1/tickets/{own.ticket.id}/set_tags/",
            {"tag_ids": tag_ids},
            format="json",
        )
        assert res.status_code == 400


class TestActionsFrontendShapes:
    def test_assign_keeps_blank_values_as_omitted(
        self, authenticated_client, own
    ) -> None:
        res = authenticated_client.post(
            f"/api/v1/tickets/{own.ticket.id}/assign/",
            {"agent_id": "", "team_id": str(own.team.id)},
            format="json",
        )
        assert res.status_code == 200
        own.ticket.refresh_from_db()
        assert own.ticket.assigned_team == own.team
        assert own.ticket.assigned_agent is None

    def test_set_tags_with_an_empty_list_clears_them(
        self, authenticated_client, own
    ) -> None:
        own.ticket.tags.add(own.tag)
        res = authenticated_client.post(
            f"/api/v1/tickets/{own.ticket.id}/set_tags/",
            {"tag_ids": []},
            format="json",
        )
        assert res.status_code == 200
        assert not own.ticket.tags.exists()


@pytest.mark.parametrize(
    ("path", "factory_row", "model"),
    [
        ("tickets", lambda o: o.ticket, Ticket),
        ("teams", lambda o: o.team, Team),
        ("kb/categories", lambda o: o.category, Category),
        ("kb/articles", lambda o: o.article, Article),
        ("users", lambda o: o.user, User),
    ],
    ids=["tickets", "teams", "kb-categories", "kb-articles", "users"],
)
def test_organization_in_an_update_is_ignored(
    admin_client, own, foreign, path, factory_row, model
) -> None:
    row = factory_row(own)
    res = admin_client.patch(
        f"/api/v1/{path}/{row.id}/",
        {"organization": str(foreign.org.id)},
        format="json",
    )
    assert res.status_code == 200
    assert model.objects.get(pk=row.pk).organization == own.org


CREATES = {
    "tickets": {"title": "t"},
    "teams": {"name": "n"},
    "kb/categories": {"name": "n", "slug": "n"},
    "kb/articles": {"title": "t", "slug": "t", "body": "b"},
    "users": {"email": "new@test.example"},
}


@pytest.mark.parametrize("path", CREATES)
def test_organization_in_a_create_is_ignored(admin_client, own, foreign, path) -> None:
    res = admin_client.post(
        f"/api/v1/{path}/",
        {**CREATES[path], "organization": str(foreign.org.id)},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data.get("organization") == own.org.id


@pytest.mark.parametrize(
    ("path", "row", "payload"),
    [
        ("teams", lambda o: o.team, lambda r: {"name": r.name}),
        (
            "kb/categories",
            lambda o: o.category,
            lambda r: {"name": "x", "slug": r.slug},
        ),
        (
            "kb/articles",
            lambda o: o.article,
            lambda r: {"title": "x", "slug": r.slug, "body": "b"},
        ),
        ("tags", lambda o: o.tag, lambda r: {"name": r.name}),
    ],
    ids=["teams", "kb-categories", "kb-articles", "tags"],
)
def test_duplicate_in_the_organization_is_a_400(
    admin_client, own, foreign, path, row, payload
) -> None:
    res = admin_client.post(f"/api/v1/{path}/", payload(row(own)), format="json")
    assert res.status_code == 400
    # The same value in another organization isn't a duplicate.
    res = admin_client.post(f"/api/v1/{path}/", payload(row(foreign)), format="json")
    assert res.status_code == 201, res.data


class TestAuthorsAreSetByTheServer:
    """A body can't attribute a row to somebody else."""

    @pytest.mark.parametrize(
        ("path", "row", "field", "model"),
        [
            ("messages", lambda o: o.message, "author", TicketMessage),
            ("attachments", lambda o: o.attachment, "uploaded_by", TicketAttachment),
            ("kb/articles", lambda o: o.article, "author", Article),
        ],
        ids=["messages", "attachments", "kb-articles"],
    )
    def test_update_ignores_it(
        self, authenticated_client, own, foreign, path, row, field, model
    ) -> None:
        target = row(own)
        before = getattr(target, f"{field}_id")
        res = authenticated_client.patch(
            f"/api/v1/{path}/{target.id}/",
            {field: str(foreign.user.id)},
            format="json",
        )
        assert res.status_code == 200
        assert getattr(model.objects.get(pk=target.pk), f"{field}_id") == before

    @pytest.mark.usefixtures("local_media")
    def test_video_upload_records_the_caller(
        self, authenticated_client, agent, own, foreign
    ) -> None:
        res = authenticated_client.post(
            "/api/v1/videos/",
            {
                "ticket": str(own.ticket.id),
                "original_file": _file(),
                "recorded_by": str(foreign.user.id),
            },
            format="multipart",
        )
        assert res.status_code == 201
        assert VideoRecording.objects.get(pk=res.data["id"]).recorded_by == agent

    def test_video_update_ignores_it(self, authenticated_client, own, foreign) -> None:
        res = authenticated_client.patch(
            f"/api/v1/videos/{own.video.id}/",
            {"recorded_by": str(foreign.user.id)},
            format="multipart",
        )
        assert res.status_code == 200
        own.video.refresh_from_db()
        assert own.video.recorded_by is None

    def test_article_create_records_the_caller(
        self, authenticated_client, agent, own, foreign
    ) -> None:
        res = authenticated_client.post(
            "/api/v1/kb/articles/",
            {
                "title": "t",
                "slug": "t",
                "body": "b",
                "organization": str(own.org.id),
                "author": str(foreign.user.id),
            },
            format="json",
        )
        assert res.status_code == 201
        assert Article.objects.get(pk=res.data["id"]).author == agent


class TestPlatformAdminImpersonation:
    """The active organization is the impersonated one, not the admin's own."""

    @pytest.fixture
    def client(self) -> APIClient:
        superuser = UserFactory(organization=None, is_superuser=True, is_staff=True)
        client = APIClient()
        client.force_authenticate(user=superuser)
        return client

    def test_scopes_to_the_impersonated_org(self, client, own, foreign) -> None:
        client.credentials(HTTP_X_SHOWDESK_ORG=str(own.org.id))
        body = {"ticket": str(own.ticket.id), "body": "hi"}
        assert client.post("/api/v1/messages/", body).status_code == 201
        body = {"ticket": str(foreign.ticket.id), "body": "hi"}
        assert client.post("/api/v1/messages/", body).status_code == 400

    def test_malformed_header_falls_back_to_the_admins_org(self, client) -> None:
        client.credentials(HTTP_X_SHOWDESK_ORG="nope")
        res = client.get("/api/v1/tickets/")
        assert res.status_code == 200
        assert res.data["count"] == 0


def _all_subclasses(cls: type) -> set[type]:
    direct = set(cls.__subclasses__())
    return direct.union(*(_all_subclasses(sub) for sub in direct))


def _app_serializers() -> set[type]:
    """Every serializer of the project that a URL can reach, wherever it lives."""
    assert get_resolver().url_patterns  # Importing the URLconfs imports the views.
    return {
        cls
        for cls in _all_subclasses(serializers.Serializer)
        if cls.__module__.startswith("apps.")
    }


def _unscoped_relations(cls: type) -> list[str]:
    return [
        f"{cls.__module__}.{cls.__name__}.{name}"
        for name, field in cls().fields.items()
        if not field.read_only
        and isinstance(
            relation := getattr(field, "child_relation", field),
            serializers.RelatedField,
        )
        and not isinstance(relation, OrgScopedPrimaryKeyRelatedField)
    ]


def test_every_writable_relation_is_org_scoped() -> None:
    """A new foreign key in a serializer can't be left out by mistake."""
    found = _app_serializers()
    assert found >= {TicketSerializer, TicketAssignSerializer, TeamSerializer}
    assert [name for cls in found for name in _unscoped_relations(cls)] == []


def test_the_guard_sees_an_unscoped_relation() -> None:
    class Unscoped(serializers.Serializer):
        one = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
        many = serializers.PrimaryKeyRelatedField(
            queryset=User.objects.all(), many=True
        )
        scoped = OrgScopedPrimaryKeyRelatedField(queryset=User.objects.all())
        shown = serializers.PrimaryKeyRelatedField(read_only=True)

    assert sorted(_unscoped_relations(Unscoped)) == [
        f"{__name__}.Unscoped.many",
        f"{__name__}.Unscoped.one",
    ]
