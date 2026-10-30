"""What agents, admins, end users and superusers may do inside an organization."""

import uuid

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient

from apps.notifications.consumers import TicketConsumer
from apps.organizations.models import Organization, OrgJoinRequest, User
from tests.factories import (
    AdminFactory,
    ArticleFactory,
    EndUserFactory,
    OrganizationFactory,
    PriorityLevelFactory,
    TagFactory,
    TeamFactory,
    TicketFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def client_for(user, org=None) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    if org is not None:
        client.credentials(HTTP_X_SHOWDESK_ORG=str(org.id))
    return client


@pytest.fixture
def colleague(organization):
    return UserFactory(organization=organization)


@pytest.fixture
def end_user(organization):
    return EndUserFactory(organization=organization)


@pytest.fixture
def superuser():
    return UserFactory(organization=None, is_superuser=True, is_staff=True)


@pytest.fixture
def superuser_client(superuser, organization) -> APIClient:
    return client_for(superuser, organization)


def users_url(user) -> str:
    return f"/api/v1/users/{user.id}/"


class TestWritingAnotherUser:
    @pytest.mark.parametrize(
        "body",
        [
            {"role": "admin"},
            {"email": "new@test.example"},
            {"is_active": False},
            {"is_available": False},
            {"first_name": "New"},
        ],
        ids=lambda body: next(iter(body)),
    )
    def test_agents_are_refused(self, authenticated_client, colleague, body) -> None:
        res = authenticated_client.patch(users_url(colleague), body, format="json")
        assert res.status_code == 403
        refreshed = User.objects.get(pk=colleague.pk)
        for field in body:
            assert getattr(refreshed, field) == getattr(colleague, field)

    @pytest.mark.parametrize(
        "body",
        [
            {"role": "admin"},
            {"email": "new@test.example"},
            {"is_active": False},
            {"is_available": False},
        ],
        ids=lambda body: next(iter(body)),
    )
    def test_admins_can(self, admin_client, colleague, body) -> None:
        res = admin_client.patch(users_url(colleague), body, format="json")
        assert res.status_code == 200, res.data
        refreshed = User.objects.get(pk=colleague.pk)
        for field, value in body.items():
            assert getattr(refreshed, field) == value

    def test_agents_cannot_create_or_delete(
        self, authenticated_client, colleague
    ) -> None:
        res = authenticated_client.post(
            "/api/v1/users/", {"email": "x@test.example"}, format="json"
        )
        assert res.status_code == 403
        assert authenticated_client.delete(users_url(colleague)).status_code == 403
        assert User.objects.filter(pk=colleague.pk).exists()

    def test_admins_can_create_and_delete(self, admin_client, colleague) -> None:
        res = admin_client.post(
            "/api/v1/users/",
            {"email": "x@test.example", "role": "agent"},
            format="json",
        )
        assert res.status_code == 201
        assert admin_client.delete(users_url(colleague)).status_code == 204

    def test_another_organizations_admin_gets_a_404(self, colleague) -> None:
        other_admin = AdminFactory(organization=OrganizationFactory())
        res = client_for(other_admin).patch(
            users_url(colleague), {"role": "admin"}, format="json"
        )
        assert res.status_code == 404

    def test_agents_keep_reading_colleagues(
        self, authenticated_client, colleague
    ) -> None:
        res = authenticated_client.get("/api/v1/users/", {"role": "agent"})
        assert res.status_code == 200
        assert str(colleague.id) in {row["id"] for row in res.data["results"]}


class TestEditingOneself:
    def test_safe_fields(self, authenticated_client, agent) -> None:
        body = {
            "first_name": "A",
            "last_name": "B",
            "phone": "123",
            "timezone": "Europe/Paris",
            "is_available": False,
        }
        res = authenticated_client.patch(users_url(agent), body, format="json")
        assert res.status_code == 200, res.data
        agent.refresh_from_db()
        for field, value in body.items():
            assert getattr(agent, field) == value

    @pytest.mark.parametrize(
        "body",
        [{"role": "admin"}, {"email": "me@test.example"}, {"is_active": False}],
        ids=lambda body: next(iter(body)),
    )
    def test_agent_managed_fields_are_refused(
        self, authenticated_client, agent, body
    ) -> None:
        res = authenticated_client.patch(users_url(agent), body, format="json")
        assert res.status_code == 403
        refreshed = User.objects.get(pk=agent.pk)
        assert refreshed.role == agent.role
        assert refreshed.email == agent.email
        assert refreshed.is_active is True

    def test_sending_an_unchanged_value_is_fine(
        self, authenticated_client, agent
    ) -> None:
        res = authenticated_client.patch(
            users_url(agent),
            {"role": agent.role, "email": agent.email, "first_name": "New"},
            format="json",
        )
        assert res.status_code == 200, res.data

    @pytest.mark.parametrize(
        "body",
        [{"role": "agent"}, {"is_active": False}],
        ids=lambda body: next(iter(body)),
    )
    def test_admins_cannot_change_their_role_or_status(
        self, admin_client, admin_user, colleague, body
    ) -> None:
        colleague.role = User.Role.ADMIN
        colleague.save()
        res = admin_client.patch(users_url(admin_user), body, format="json")
        assert res.status_code == 403
        admin_user.refresh_from_db()
        assert admin_user.role == User.Role.ADMIN
        assert admin_user.is_active is True

    def test_admins_can_change_their_email(self, admin_client, admin_user) -> None:
        res = admin_client.patch(
            users_url(admin_user), {"email": "me@test.example"}, format="json"
        )
        assert res.status_code == 200
        admin_user.refresh_from_db()
        assert admin_user.email == "me@test.example"

    def test_superusers_cannot_change_their_own_role(self, organization) -> None:
        superuser = UserFactory(
            organization=organization,
            role=User.Role.AGENT,
            is_superuser=True,
            is_staff=True,
        )
        res = client_for(superuser).patch(
            users_url(superuser), {"role": "admin"}, format="json"
        )
        assert res.status_code == 403

    @pytest.mark.parametrize(
        "field",
        ["is_staff", "is_superuser", "organization"],
    )
    def test_privileged_fields_are_ignored(self, organization, field) -> None:
        other = OrganizationFactory()
        value = str(other.id) if field == "organization" else True
        for user in (
            UserFactory(organization=organization),
            AdminFactory(organization=organization, is_staff=False),
        ):
            res = client_for(user).patch(users_url(user), {field: value}, format="json")
            assert res.status_code == 200
            refreshed = User.objects.get(pk=user.pk)
            assert refreshed.is_staff is False
            assert refreshed.is_superuser is False
            assert refreshed.organization == organization

    def test_an_admin_cannot_grant_staff_or_superuser(
        self, admin_client, colleague
    ) -> None:
        res = admin_client.patch(
            users_url(colleague),
            {"is_staff": True, "is_superuser": True},
            format="json",
        )
        assert res.status_code == 200
        colleague.refresh_from_db()
        assert colleague.is_staff is False
        assert colleague.is_superuser is False

    def test_an_admin_cannot_create_a_superuser(self, admin_client) -> None:
        res = admin_client.post(
            "/api/v1/users/",
            {"email": "x@test.example", "is_staff": True, "is_superuser": True},
            format="json",
        )
        assert res.status_code == 201
        created = User.objects.get(email="x@test.example")
        assert created.is_staff is False
        assert created.is_superuser is False


class TestEmailIsTheLoginIdentity:
    def test_it_is_stored_in_lowercase(self, admin_client, colleague) -> None:
        res = admin_client.patch(
            users_url(colleague), {"email": "New@Test.Example"}, format="json"
        )
        assert res.status_code == 200
        colleague.refresh_from_db()
        assert colleague.email == "new@test.example"

    def test_a_variant_of_a_taken_address_is_refused(
        self, admin_client, colleague
    ) -> None:
        UserFactory(organization=OrganizationFactory(), email="taken@test.example")
        res = admin_client.patch(
            users_url(colleague), {"email": "TAKEN@test.example"}, format="json"
        )
        assert res.status_code == 400


class TestSuperuserRows:
    @pytest.fixture
    def target(self, organization):
        return UserFactory(
            organization=organization,
            role=User.Role.ADMIN,
            is_superuser=True,
            is_staff=True,
        )

    @pytest.mark.parametrize(
        "body",
        [{"first_name": "X"}, {"email": "x@test.example"}, {"is_active": False}],
        ids=lambda body: next(iter(body)),
    )
    def test_admins_cannot_edit_them(self, admin_client, target, body) -> None:
        res = admin_client.patch(users_url(target), body, format="json")
        assert res.status_code == 403

    def test_admins_cannot_deactivate_them(self, admin_client, target) -> None:
        res = admin_client.post(f"{users_url(target)}toggle_active/")
        assert res.status_code == 403
        target.refresh_from_db()
        assert target.is_active is True

    def test_admins_cannot_delete_them(self, admin_client, target) -> None:
        assert admin_client.delete(users_url(target)).status_code == 403
        assert User.objects.filter(pk=target.pk).exists()

    def test_superusers_can(self, superuser_client, target) -> None:
        res = superuser_client.patch(
            users_url(target), {"email": "x@test.example"}, format="json"
        )
        assert res.status_code == 200
        res = superuser_client.post(f"{users_url(target)}toggle_active/")
        assert res.status_code == 200
        assert superuser_client.delete(users_url(target)).status_code == 204

    def test_a_join_request_cannot_move_them(
        self, admin_client, organization, superuser
    ) -> None:
        request = OrgJoinRequest.objects.create(
            organization=organization, email=superuser.email
        )
        res = admin_client.post(f"/api/v1/join-requests/{request.id}/approve/")
        assert res.status_code == 409
        superuser.refresh_from_db()
        assert superuser.organization is None


class TestLastActiveAdmin:
    def test_it_cannot_delete_itself(self, admin_client, admin_user) -> None:
        assert admin_client.delete(users_url(admin_user)).status_code == 400
        assert User.objects.filter(pk=admin_user.pk).exists()

    def test_it_can_leave_when_there_is_another_one(
        self, admin_client, admin_user, organization
    ) -> None:
        AdminFactory(organization=organization)
        assert admin_client.delete(users_url(admin_user)).status_code == 204

    def test_an_inactive_admin_does_not_count(
        self, admin_client, admin_user, organization
    ) -> None:
        AdminFactory(organization=organization, is_active=False)
        assert admin_client.delete(users_url(admin_user)).status_code == 400

    def test_a_superuser_does_not_count(
        self, admin_client, admin_user, organization
    ) -> None:
        UserFactory(organization=organization, role="admin", is_superuser=True)
        assert admin_client.delete(users_url(admin_user)).status_code == 400

    @pytest.mark.parametrize(
        "body",
        [{"role": "agent"}, {"is_active": False}],
        ids=lambda body: next(iter(body)),
    )
    def test_it_cannot_be_removed_by_an_update(
        self, superuser_client, admin_user, body
    ) -> None:
        res = superuser_client.patch(users_url(admin_user), body, format="json")
        assert res.status_code == 400
        admin_user.refresh_from_db()
        assert admin_user.role == User.Role.ADMIN
        assert admin_user.is_active is True

    def test_it_cannot_be_deactivated_by_the_toggle(
        self, superuser_client, admin_user
    ) -> None:
        res = superuser_client.post(f"{users_url(admin_user)}toggle_active/")
        assert res.status_code == 400
        admin_user.refresh_from_db()
        assert admin_user.is_active is True

    def test_it_cannot_be_deleted_by_a_superuser(
        self, superuser_client, admin_user
    ) -> None:
        assert superuser_client.delete(users_url(admin_user)).status_code == 400

    def test_another_admin_can_be_demoted(
        self, admin_client, organization, admin_user
    ) -> None:
        other = AdminFactory(organization=organization)
        res = admin_client.patch(users_url(other), {"role": "agent"}, format="json")
        assert res.status_code == 200

    def test_an_inactive_admin_can_be_removed(self, admin_client, organization) -> None:
        other = AdminFactory(organization=organization, is_active=False)
        assert admin_client.delete(users_url(other)).status_code == 204


class TestOrganizationCreateAndDestroy:
    @pytest.mark.parametrize("role", ["admin", "agent"])
    def test_members_get_a_405(self, organization, role) -> None:
        client = client_for(UserFactory(organization=organization, role=role))
        before = Organization.objects.count()
        res = client.post(
            "/api/v1/organizations/", {"name": "n", "slug": "n"}, format="json"
        )
        assert res.status_code == 405
        res = client.delete(f"/api/v1/organizations/{organization.id}/")
        assert res.status_code == 405
        assert Organization.objects.count() == before

    def test_the_platform_routes_keep_theirs(self, superuser) -> None:
        client = client_for(superuser)
        res = client.post(
            "/api/v1/platform/organizations/",
            {"name": "n", "slug": "n"},
            format="json",
        )
        assert res.status_code == 201
        org = Organization.objects.get(slug="n")
        res = client.delete(f"/api/v1/platform/organizations/{org.id}/")
        assert res.status_code == 204


class TestOrganizationCredentials:
    def test_agents_see_the_token_but_not_the_secret(
        self, authenticated_client, organization
    ) -> None:
        url = f"/api/v1/organizations/{organization.id}/"
        for row in (
            authenticated_client.get(url).data,
            authenticated_client.get("/api/v1/organizations/").data["results"][0],
        ):
            assert row["api_token"] == str(organization.api_token)
            assert "widget_secret" not in row

    def test_admins_see_both(self, admin_client, organization) -> None:
        row = admin_client.get(f"/api/v1/organizations/{organization.id}/").data
        assert row["widget_secret"] == organization.widget_secret
        assert row["api_token"] == str(organization.api_token)

    def test_impersonating_superusers_see_both(
        self, superuser_client, organization
    ) -> None:
        row = superuser_client.get(f"/api/v1/organizations/{organization.id}/").data
        assert row["widget_secret"] == organization.widget_secret

    @pytest.mark.parametrize("action", ["regenerate_token", "revoke_credentials"])
    def test_rotating_returns_them_to_the_admin(
        self, admin_client, organization, action
    ) -> None:
        res = admin_client.post(f"/api/v1/organizations/{organization.id}/{action}/")
        assert res.status_code == 200
        organization.refresh_from_db()
        assert res.data["widget_secret"] == organization.widget_secret
        assert res.data["api_token"] == str(organization.api_token)


class TestOrganizationWrites:
    @pytest.mark.parametrize(
        "body",
        [
            {"name": "New"},
            {"widget_color": "#000000"},
            {"widget_greeting": "Hi"},
            {"onboarding_step": 1, "widget_color": "#000000"},
            {},
        ],
        ids=["name", "widget-color", "greeting", "onboarding-with-widget", "empty"],
    )
    def test_agents_are_refused(self, authenticated_client, organization, body) -> None:
        res = authenticated_client.patch(
            f"/api/v1/organizations/{organization.id}/", body, format="json"
        )
        assert res.status_code == 403
        refreshed = Organization.objects.get(pk=organization.pk)
        assert refreshed.name == organization.name
        assert refreshed.widget_color == organization.widget_color
        assert refreshed.onboarding_step == organization.onboarding_step

    def test_agents_cannot_replace_it(self, authenticated_client, organization) -> None:
        res = authenticated_client.put(
            f"/api/v1/organizations/{organization.id}/",
            {"name": "New", "slug": "new"},
            format="json",
        )
        assert res.status_code == 403

    def test_onboarding_progress_is_refused_to_agents(
        self, authenticated_client, organization
    ) -> None:
        """They could otherwise hide the wizard from the organization's admin."""
        res = authenticated_client.patch(
            f"/api/v1/organizations/{organization.id}/",
            {"onboarding_completed_at": "2026-01-01T00:00:00Z"},
            format="json",
        )
        assert res.status_code == 403
        organization.refresh_from_db()
        assert organization.onboarding_completed_at is None

    @pytest.mark.parametrize("body", [123, "text", [1, 2], [{"name": "New"}], []])
    def test_a_body_that_is_not_an_object_is_refused(
        self, authenticated_client, admin_client, organization, body
    ) -> None:
        for client in (authenticated_client, admin_client):
            res = client.patch(
                f"/api/v1/organizations/{organization.id}/", body, format="json"
            )
            assert res.status_code == 400

    def test_admins_can_run_the_onboarding_widget_step(
        self, admin_client, organization
    ) -> None:
        res = admin_client.patch(
            f"/api/v1/organizations/{organization.id}/",
            {
                "name": "New",
                "widget_color": "#000000",
                "widget_position": "bottom-left",
                "widget_greeting": "Hi",
                "onboarding_step": 1,
            },
            format="json",
        )
        assert res.status_code == 200, res.data
        organization.refresh_from_db()
        assert organization.name == "New"
        assert organization.widget_color == "#000000"
        assert organization.onboarding_step == 1

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("plan", "enterprise"),
            ("feature_flag_overrides", {"sso": True}),
            ("is_active", False),
            ("slug", "new-slug"),
            ("video_expiration_days", 9999),
            ("video_max_duration_seconds", 99999),
            ("ticket_counter", 100),
            ("widget_first_seen_at", "2026-01-01T00:00:00Z"),
            ("api_token", "00000000-0000-0000-0000-000000000000"),
            ("widget_secret", "x"),
        ],
        ids=lambda value: value if isinstance(value, str) else "",
    )
    def test_platform_managed_fields_stay_out_of_reach_of_admins(
        self, admin_client, organization, field, value
    ) -> None:
        before = getattr(Organization.objects.get(pk=organization.pk), field)
        res = admin_client.patch(
            f"/api/v1/organizations/{organization.id}/", {field: value}, format="json"
        )
        assert res.status_code == 200
        assert getattr(Organization.objects.get(pk=organization.pk), field) == before


STAFF_ROUTES = [
    "organizations",
    "users",
    "teams",
    "tags",
    "priorities",
    "sla-policies",
    "saved-views",
    "canned-responses",
    "kb/categories",
    "kb/articles",
    "join-requests",
    "organization-domains",
]


class TestEndUsers:
    @pytest.mark.parametrize("path", STAFF_ROUTES)
    def test_lists_are_forbidden(self, end_user, path) -> None:
        assert client_for(end_user).get(f"/api/v1/{path}/").status_code == 403

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            ("users", {"email": "x@test.example"}),
            ("teams", {"name": "n"}),
            ("tags", {"name": "n"}),
            ("priorities", {"name": "n", "slug": "n"}),
            ("saved-views", {"name": "n", "filters": {}}),
            ("canned-responses", {"name": "n", "body": "b"}),
            ("kb/categories", {"name": "n", "slug": "n"}),
            ("kb/articles", {"title": "n", "slug": "n", "body": "b"}),
            ("organization-domains", {"domain": "a.example", "is_branding": True}),
        ],
        ids=lambda value: value if isinstance(value, str) else "",
    )
    def test_creates_are_forbidden(self, end_user, path, body) -> None:
        res = client_for(end_user).post(f"/api/v1/{path}/", body, format="json")
        assert res.status_code == 403

    def test_they_cannot_edit_their_row_through_the_agents_route(
        self, end_user
    ) -> None:
        res = client_for(end_user).patch(
            users_url(end_user), {"first_name": "X"}, format="json"
        )
        assert res.status_code == 403

    def test_they_cannot_read_drafts(self, end_user, organization) -> None:
        article = ArticleFactory(organization=organization)
        res = client_for(end_user).get(f"/api/v1/kb/articles/{article.id}/")
        assert res.status_code == 403

    def test_article_feedback_stays_open(self, end_user, organization) -> None:
        article = ArticleFactory(organization=organization)
        res = client_for(end_user).post(f"/api/v1/kb/articles/{article.id}/helpful/")
        assert res.status_code == 200


class TestAgentsVersusAdmins:
    @pytest.mark.parametrize(
        "path",
        [p for p in STAFF_ROUTES if p != "join-requests"],
    )
    def test_agents_can_read(self, authenticated_client, path) -> None:
        assert authenticated_client.get(f"/api/v1/{path}/").status_code == 200

    def test_agents_cannot_read_join_requests(
        self, authenticated_client, organization
    ) -> None:
        request = OrgJoinRequest.objects.create(
            organization=organization, email="j@test.example"
        )
        assert authenticated_client.get("/api/v1/join-requests/").status_code == 403
        res = authenticated_client.get(f"/api/v1/join-requests/{request.id}/")
        assert res.status_code == 403

    @pytest.mark.parametrize(
        ("path", "factory", "create"),
        [
            ("teams", TeamFactory, {"name": "n"}),
            ("priorities", PriorityLevelFactory, {"name": "n", "slug": "n"}),
        ],
        ids=["teams", "priorities"],
    )
    def test_admin_only_routes(
        self, authenticated_client, admin_client, organization, path, factory, create
    ) -> None:
        row = factory(organization=organization)
        url = f"/api/v1/{path}/{row.id}/"
        assert (
            authenticated_client.post(
                f"/api/v1/{path}/", create, format="json"
            ).status_code
            == 403
        )
        assert (
            authenticated_client.patch(url, {"name": "x"}, format="json").status_code
            == 403
        )
        assert authenticated_client.delete(url).status_code == 403

        res = admin_client.post(f"/api/v1/{path}/", create, format="json")
        assert res.status_code == 201
        assert admin_client.patch(url, {"name": "x"}, format="json").status_code == 200
        assert admin_client.delete(url).status_code == 204

    def test_agents_create_tags_but_only_admins_change_them(
        self, authenticated_client, admin_client, organization
    ) -> None:
        res = authenticated_client.post(
            "/api/v1/tags/", {"name": "n", "color": "#000000"}, format="json"
        )
        assert res.status_code == 201

        tag = TagFactory(organization=organization)
        url = f"/api/v1/tags/{tag.id}/"
        assert (
            authenticated_client.patch(url, {"name": "x"}, format="json").status_code
            == 403
        )
        assert authenticated_client.delete(url).status_code == 403
        assert admin_client.patch(url, {"name": "x"}, format="json").status_code == 200
        assert admin_client.delete(url).status_code == 204

    def test_agents_keep_writing_the_knowledge_base(self, authenticated_client) -> None:
        res = authenticated_client.post(
            "/api/v1/kb/articles/",
            {"title": "t", "slug": "t", "body": "b"},
            format="json",
        )
        assert res.status_code == 201


class TestAssignment:
    @pytest.fixture
    def ticket(self, organization):
        return TicketFactory(organization=organization, requester=None)

    @pytest.fixture
    def refused_targets(self, organization):
        return {
            "inactive": UserFactory(organization=organization, is_active=False),
            "end-user": EndUserFactory(organization=organization),
            "other-org": UserFactory(organization=OrganizationFactory()),
            "unknown": UserFactory.build(id=uuid.uuid4()),
        }

    @pytest.mark.parametrize("target", ["inactive", "end-user", "other-org", "unknown"])
    def test_assign_refuses(
        self, authenticated_client, ticket, refused_targets, target
    ) -> None:
        res = authenticated_client.post(
            f"/api/v1/tickets/{ticket.id}/assign/",
            {"agent_id": str(refused_targets[target].id)},
            format="json",
        )
        assert res.status_code == 400
        ticket.refresh_from_db()
        assert ticket.assigned_agent is None

    @pytest.mark.parametrize("target", ["inactive", "end-user", "other-org", "unknown"])
    def test_patch_refuses(
        self, authenticated_client, ticket, refused_targets, target
    ) -> None:
        res = authenticated_client.patch(
            f"/api/v1/tickets/{ticket.id}/",
            {"assigned_agent": str(refused_targets[target].id)},
            format="json",
        )
        assert res.status_code == 400
        ticket.refresh_from_db()
        assert ticket.assigned_agent is None

    @pytest.mark.parametrize("role", ["agent", "admin"])
    def test_active_agents_and_admins_are_accepted(
        self, authenticated_client, organization, ticket, role
    ) -> None:
        target = UserFactory(organization=organization, role=role)
        res = authenticated_client.post(
            f"/api/v1/tickets/{ticket.id}/assign/",
            {"agent_id": str(target.id)},
            format="json",
        )
        assert res.status_code == 200
        res = authenticated_client.patch(
            f"/api/v1/tickets/{ticket.id}/",
            {"assigned_agent": str(target.id)},
            format="json",
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        assert ticket.assigned_agent == target

    def test_patch_can_unassign_a_deactivated_agent(
        self, authenticated_client, organization
    ) -> None:
        gone = UserFactory(organization=organization, is_active=False)
        ticket = TicketFactory(
            organization=organization, requester=None, assigned_agent=gone
        )
        res = authenticated_client.patch(
            f"/api/v1/tickets/{ticket.id}/", {"assigned_agent": None}, format="json"
        )
        assert res.status_code == 200
        ticket.refresh_from_db()
        assert ticket.assigned_agent is None

    def test_other_fields_can_change_while_assigned_to_a_deactivated_agent(
        self, authenticated_client, organization
    ) -> None:
        gone = UserFactory(organization=organization, is_active=False)
        ticket = TicketFactory(
            organization=organization, requester=None, assigned_agent=gone
        )
        res = authenticated_client.patch(
            f"/api/v1/tickets/{ticket.id}/", {"title": "New"}, format="json"
        )
        assert res.status_code == 200

    def test_impersonating_superuser_follows_the_impersonated_org(
        self, superuser, superuser_client, organization, ticket, agent
    ) -> None:
        """As in bulk_update, the superuser's own row isn't an agent of the org."""
        foreign = UserFactory(organization=OrganizationFactory())
        url = f"/api/v1/tickets/{ticket.id}/"
        for agent_id, expected in (
            (agent.id, 200),
            (foreign.id, 400),
            (superuser.id, 400),
        ):
            res = superuser_client.post(
                f"{url}assign/", {"agent_id": str(agent_id)}, format="json"
            )
            assert res.status_code == expected
            res = superuser_client.patch(
                url, {"assigned_agent": str(agent_id)}, format="json"
            )
            assert res.status_code == expected


@pytest.fixture
def memory_channel_layer(settings):
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }


def _socket(user, query: str, group: str | None = None) -> bool:
    """Return whether ``user`` connects, and hears ``group`` if there is one."""

    async def connect() -> bool:
        communicator = WebsocketCommunicator(
            TicketConsumer.as_asgi(), f"/ws/tickets/?{query}"
        )
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        if connected and group:
            await get_channel_layer().group_send(
                group, {"type": "ticket.update", "data": {"heard": True}}
            )
            assert await communicator.receive_json_from() == {"heard": True}
        await communicator.disconnect()
        return connected

    return async_to_sync(connect)()


@pytest.mark.usefixtures("memory_channel_layer")
@pytest.mark.django_db(transaction=True)
class TestSocketOrgParameter:
    @pytest.mark.parametrize(
        "query", ["org=nope", "org=a%20b", f"org={uuid.uuid4()}", ""]
    )
    def test_a_bad_value_falls_back_to_the_superusers_org(self, query) -> None:
        org = OrganizationFactory()
        superuser = UserFactory(organization=org, is_superuser=True, is_staff=True)
        assert _socket(superuser, query, group=f"org_{org.id}") is True

    @pytest.mark.parametrize("query", ["org=nope", f"org={uuid.uuid4()}"])
    def test_a_bad_value_is_refused_without_an_org_to_fall_back_on(self, query) -> None:
        superuser = UserFactory(organization=None, is_superuser=True, is_staff=True)
        assert _socket(superuser, query) is False

    def test_a_known_org_is_joined(self) -> None:
        superuser = UserFactory(organization=None, is_superuser=True, is_staff=True)
        org = OrganizationFactory()
        assert _socket(superuser, f"org={org.id}", group=f"org_{org.id}") is True

    def test_a_non_superuser_cannot_use_it(self) -> None:
        agent = UserFactory(organization=None)
        org = OrganizationFactory()
        assert _socket(agent, f"org={org.id}") is False
