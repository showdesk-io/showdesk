"""Updates work on the locked row: a concurrent change or delete isn't undone."""

import threading
import time
import uuid

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.organizations.models import Organization, OrgJoinRequest, User
from tests.factories import AdminFactory, OrganizationFactory, UserFactory


def _client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _wait_until_a_session_waits_for_a_lock(timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    with connection.cursor() as cursor:
        while time.monotonic() < deadline:
            # The activity view is cached for the length of a transaction.
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                "AND pid <> pg_backend_pid()"
            )
            if cursor.fetchone()[0]:
                return
            time.sleep(0.02)
    pytest.fail("The request never waited for the row lock.")


class _Request(threading.Thread):
    """Run a request on its own connection and keep the response."""

    def __init__(self, send) -> None:
        super().__init__()
        self.send = send
        self.response = None

    def run(self) -> None:
        try:
            self.response = self.send()
        finally:
            connection.close()


def _after(barrier: threading.Barrier, remove, actor: User, target: User):
    def send():
        barrier.wait(timeout=10)
        return remove(_client_for(actor), target)

    return send


def _while_the_row_is_locked(model, pk, send, change) -> _Request:
    """Have ``send`` read the row, wait for its lock, then see ``change`` commit."""
    request = _Request(send)
    with transaction.atomic():
        model.objects.select_for_update().get(pk=pk)
        request.start()
        _wait_until_a_session_waits_for_a_lock()
        change()
    request.join(timeout=15)
    assert not request.is_alive()
    return request


@pytest.mark.django_db(transaction=True)
class TestConcurrentChanges:
    @pytest.fixture
    def org(self):
        return OrganizationFactory()

    @pytest.fixture
    def admin(self, org):
        return AdminFactory(organization=org, first_name="Old")

    @pytest.fixture
    def other_admin(self, org):
        return AdminFactory(organization=org)

    def _self_edit(self, user: User, body: dict | None = None):
        return lambda: _client_for(user).patch(
            f"/api/v1/users/{user.id}/", body or {"first_name": "New"}, format="json"
        )

    @pytest.mark.usefixtures("other_admin")
    def test_a_self_edit_does_not_undo_a_demotion(self, admin) -> None:
        request = _while_the_row_is_locked(
            User,
            admin.pk,
            self._self_edit(admin),
            lambda: User.objects.filter(pk=admin.pk).update(
                role=User.Role.AGENT, is_staff=False
            ),
        )
        assert request.response.status_code == 200
        assert request.response.data["role"] == "agent"
        admin.refresh_from_db()
        assert admin.role == "agent"
        assert admin.is_staff is False
        assert admin.first_name == "New"

    @pytest.mark.usefixtures("other_admin")
    def test_a_self_edit_does_not_undo_a_delete(self, admin) -> None:
        request = _while_the_row_is_locked(
            User,
            admin.pk,
            self._self_edit(admin),
            lambda: User.objects.filter(pk=admin.pk).delete(),
        )
        assert request.response.status_code == 404
        assert not User.objects.filter(pk=admin.pk).exists()

    @pytest.mark.usefixtures("other_admin")
    def test_a_demoted_admin_loses_the_rights_at_once(self, admin) -> None:
        request = _while_the_row_is_locked(
            User,
            admin.pk,
            self._self_edit(admin, {"phone": "123", "email": "new@example.com"}),
            lambda: User.objects.filter(pk=admin.pk).update(role=User.Role.AGENT),
        )
        assert request.response.status_code == 403
        admin.refresh_from_db()
        assert admin.email != "new@example.com"

    def test_toggle_active_on_a_deleted_user(self, admin, other_admin) -> None:
        request = _while_the_row_is_locked(
            User,
            other_admin.pk,
            lambda: _client_for(admin).post(
                f"/api/v1/users/{other_admin.id}/toggle_active/"
            ),
            lambda: User.objects.filter(pk=other_admin.pk).delete(),
        )
        assert request.response.status_code == 404
        assert not User.objects.filter(pk=other_admin.pk).exists()

    def test_delete_of_a_deleted_user(self, admin, other_admin) -> None:
        request = _while_the_row_is_locked(
            User,
            other_admin.pk,
            lambda: _client_for(admin).delete(f"/api/v1/users/{other_admin.id}/"),
            lambda: User.objects.filter(pk=other_admin.pk).delete(),
        )
        assert request.response.status_code == 404

    def test_an_organization_patch_keeps_a_rotated_token(self, admin, org) -> None:
        rotated = uuid.uuid4()
        request = _while_the_row_is_locked(
            Organization,
            org.pk,
            lambda: _client_for(admin).patch(
                f"/api/v1/organizations/{org.id}/", {"name": "New"}, format="json"
            ),
            lambda: Organization.objects.filter(pk=org.pk).update(api_token=rotated),
        )
        assert request.response.status_code == 200
        org.refresh_from_db()
        assert org.api_token == rotated
        assert org.name == "New"

    @pytest.mark.parametrize(
        "remove",
        [
            lambda client, target: client.patch(
                f"/api/v1/users/{target.id}/", {"role": "agent"}, format="json"
            ),
            lambda client, target: client.patch(
                f"/api/v1/users/{target.id}/", {"is_active": False}, format="json"
            ),
            lambda client, target: client.post(
                f"/api/v1/users/{target.id}/toggle_active/"
            ),
            lambda client, target: client.delete(f"/api/v1/users/{target.id}/"),
        ],
        ids=["demote", "deactivate", "toggle", "delete"],
    )
    def test_two_admins_removing_each_other_leave_one(self, remove) -> None:
        for _ in range(5):
            org = OrganizationFactory()
            first = AdminFactory(organization=org)
            second = AdminFactory(organization=org)
            barrier = threading.Barrier(2)

            requests = [
                _Request(_after(barrier, remove, first, second)),
                _Request(_after(barrier, remove, second, first)),
            ]
            for request in requests:
                request.start()
            for request in requests:
                request.join(timeout=20)

            statuses = sorted(request.response.status_code for request in requests)
            assert statuses[1] == 400, statuses
            assert statuses[0] in (200, 204), statuses
            assert (
                User.objects.filter(
                    organization=org, role=User.Role.ADMIN, is_active=True
                ).count()
                == 1
            )


@pytest.mark.django_db
class TestOnlyChangedFieldsAreWritten:
    def _updates(self, queries) -> list[str]:
        return [q["sql"] for q in queries if q["sql"].startswith("UPDATE")]

    def test_a_user_update(self, admin_client, agent) -> None:
        with CaptureQueriesContext(connection) as queries:
            res = admin_client.patch(
                f"/api/v1/users/{agent.id}/", {"first_name": "New"}, format="json"
            )
        assert res.status_code == 200
        [update] = self._updates(queries)
        assert '"first_name"' in update
        assert '"role"' not in update

    def test_nothing_is_written_when_nothing_changes(self, admin_client, agent) -> None:
        with CaptureQueriesContext(connection) as queries:
            res = admin_client.patch(
                f"/api/v1/users/{agent.id}/",
                {"first_name": agent.first_name},
                format="json",
            )
        assert res.status_code == 200
        assert not self._updates(queries)

    def test_an_organization_update(self, admin_client, organization) -> None:
        with CaptureQueriesContext(connection) as queries:
            res = admin_client.patch(
                f"/api/v1/organizations/{organization.id}/",
                {"name": "New"},
                format="json",
            )
        assert res.status_code == 200
        [update] = self._updates(queries)
        assert '"api_token"' not in update


@pytest.mark.django_db
class TestJoinApprovalKeepsAnAdmin:
    def _approve(self, client, org, email):
        join_request = OrgJoinRequest.objects.create(
            organization=org, email=email, full_name="A"
        )
        return join_request, client.post(
            f"/api/v1/join-requests/{join_request.id}/approve/"
        )

    def test_the_last_admin_is_not_demoted(self, organization) -> None:
        admin = AdminFactory(organization=organization)
        client = _client_for(admin)
        join_request, res = self._approve(client, organization, admin.email)
        assert res.status_code == 400
        admin.refresh_from_db()
        join_request.refresh_from_db()
        assert admin.role == "admin"
        assert join_request.status == "pending"

    def test_another_admin_can_be(self, organization) -> None:
        admin = AdminFactory(organization=organization)
        other = AdminFactory(organization=organization)
        _, res = self._approve(_client_for(admin), organization, other.email)
        assert res.status_code == 200
        other.refresh_from_db()
        assert other.role == "agent"

    def test_a_member_row_is_approved_without_a_full_write(self, organization) -> None:
        admin = AdminFactory(organization=organization)
        member = UserFactory(
            organization=organization, role="end_user", first_name="", last_name=""
        )
        _, res = self._approve(_client_for(admin), organization, member.email)
        assert res.status_code == 200
        member.refresh_from_db()
        assert member.role == "agent"
        assert member.is_staff is True
        assert member.first_name == "A"
