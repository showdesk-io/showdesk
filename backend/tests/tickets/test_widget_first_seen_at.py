"""Tests for the widget install-detection field on Organization.

Any widget request authenticated by X-Widget-Token must stamp the org's
``widget_first_seen_at`` on its first occurrence (and only the first), so
the onboarding wizard can flip from "Waiting" to "Detected".
"""

import pytest
from rest_framework.test import APIClient

from apps.organizations.models import Organization
from tests.factories import OrganizationFactory


@pytest.mark.django_db
class TestWidgetFirstSeenAt:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.org = OrganizationFactory()
        self.client = APIClient()

    def _post_session(self):
        return self.client.post(
            "/api/v1/tickets/widget_session/",
            data={},
            format="json",
            HTTP_X_WIDGET_TOKEN=self.org.api_token,
        )

    def test_widget_first_seen_at_is_null_initially(self):
        assert self.org.widget_first_seen_at is None

    def test_first_widget_call_stamps_widget_first_seen_at(self):
        response = self._post_session()
        assert response.status_code in (200, 201)

        self.org.refresh_from_db()
        assert self.org.widget_first_seen_at is not None

    def test_subsequent_widget_calls_do_not_overwrite_widget_first_seen_at(self):
        self._post_session()
        self.org.refresh_from_db()
        first_stamp = self.org.widget_first_seen_at
        assert first_stamp is not None

        # A few more calls; the timestamp must stay frozen.
        for _ in range(3):
            self._post_session()

        self.org.refresh_from_db()
        assert self.org.widget_first_seen_at == first_stamp

    def test_invalid_token_does_not_stamp_widget_first_seen_at(self):
        # A valid-format UUID that does not match any org.
        response = self.client.post(
            "/api/v1/tickets/widget_session/",
            data={},
            format="json",
            HTTP_X_WIDGET_TOKEN="00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == 401

        # No org should have been touched.
        assert (
            Organization.objects.filter(widget_first_seen_at__isnull=False).count() == 0
        )
