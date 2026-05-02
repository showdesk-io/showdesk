"""Tests for the widget_session POST endpoint (create/resume)."""

import hashlib
import hmac

import pytest
from rest_framework.test import APIClient

from apps.tickets.models import WidgetSession
from tests.factories import OrganizationFactory


URL = "/api/v1/tickets/widget_session/"


def _hash(secret: str, external_user_id: str) -> str:
    return hmac.new(
        secret.encode(),
        external_user_id.encode(),
        hashlib.sha256,
    ).hexdigest()


@pytest.mark.django_db
class TestWidgetSessionResume:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.org = OrganizationFactory()
        self.client = APIClient()

    def _post(self, **body):
        return self.client.post(
            URL,
            data=body,
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
        )

    def test_resume_with_matching_external_user_id(self):
        """Same user resuming their own session — works as before."""
        session = WidgetSession.objects.create(
            organization=self.org, external_user_id="user-A"
        )
        response = self._post(
            session_id=str(session.id),
            external_user_id="user-A",
            user_hash=_hash(self.org.widget_secret, "user-A"),
        )
        assert response.status_code == 200
        assert response.data["session_id"] == str(session.id)

    def test_resume_falls_through_when_external_user_id_mismatches(self):
        """A different user reusing a stale session_id from localStorage
        must NOT inherit the previous user's conversation. Instead, the
        backend creates (or finds) a session for the new user."""
        owned_by_a = WidgetSession.objects.create(
            organization=self.org, external_user_id="user-A"
        )
        response = self._post(
            session_id=str(owned_by_a.id),
            external_user_id="user-B",
            user_hash=_hash(self.org.widget_secret, "user-B"),
        )
        assert response.status_code == 201
        assert response.data["session_id"] != str(owned_by_a.id)
        assert response.data["external_user_id"] == "user-B"

    def test_resume_finds_existing_session_for_user_b(self):
        """If user-B already has their own session, the mismatched stale
        session_id is dropped and user-B's real session is returned."""
        WidgetSession.objects.create(
            organization=self.org, external_user_id="user-A"
        )
        owned_by_b = WidgetSession.objects.create(
            organization=self.org, external_user_id="user-B"
        )
        response = self._post(
            session_id=str(
                WidgetSession.objects.get(external_user_id="user-A").id
            ),
            external_user_id="user-B",
            user_hash=_hash(self.org.widget_secret, "user-B"),
        )
        assert response.status_code == 200
        assert response.data["session_id"] == str(owned_by_b.id)

    def test_anonymous_session_can_still_be_resumed_by_identified_user(self):
        """Anonymous sessions (no external_user_id) remain claimable —
        the mismatch check only fires when the session has an owner."""
        anon = WidgetSession.objects.create(organization=self.org)
        response = self._post(
            session_id=str(anon.id),
            external_user_id="user-A",
            user_hash=_hash(self.org.widget_secret, "user-A"),
        )
        assert response.status_code == 200
        assert response.data["session_id"] == str(anon.id)
