"""Tests for widget submit with issue_type and external_user_id fields."""

import pytest
from rest_framework.test import APIClient

from tests.factories import OrganizationFactory


@pytest.mark.django_db
class TestWidgetSubmitNewFields:
    """Tests for issue_type and external_user_id on widget submissions."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.organization = OrganizationFactory()
        self.client = APIClient()

    def test_widget_submit_with_issue_type(self):
        """Widget can submit a ticket with an issue_type."""
        response = self.client.post(
            "/api/v1/tickets/widget_submit/",
            data={
                "title": "Button broken",
                "description": "Cannot click submit",
                "requester_name": "Jean",
                "requester_email": "jean@acme.com",
                "issue_type": "bug",
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=self.organization.api_token,
        )
        assert response.status_code == 201
        assert response.data["issue_type"] == "bug"

    def test_widget_submit_issue_type_defaults_to_other(self):
        """issue_type defaults to 'other' when not provided."""
        response = self.client.post(
            "/api/v1/tickets/widget_submit/",
            data={
                "title": "Hello",
                "description": "World",
                "requester_name": "Jean",
                "requester_email": "jean@acme.com",
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=self.organization.api_token,
        )
        assert response.status_code == 201
        assert response.data["issue_type"] == "other"

    def test_widget_submit_with_external_user_id(self):
        """Widget can submit a ticket with external_user_id."""
        response = self.client.post(
            "/api/v1/tickets/widget_submit/",
            data={
                "title": "Bug report",
                "description": "Details",
                "requester_name": "Jean",
                "requester_email": "jean@acme.com",
                "external_user_id": "usr_12345",
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=self.organization.api_token,
        )
        assert response.status_code == 201
        assert response.data["external_user_id"] == "usr_12345"

    def test_widget_submit_external_user_id_defaults_to_empty(self):
        """external_user_id defaults to empty string."""
        response = self.client.post(
            "/api/v1/tickets/widget_submit/",
            data={
                "title": "Bug",
                "description": "Details",
                "requester_name": "Jean",
                "requester_email": "jean@acme.com",
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=self.organization.api_token,
        )
        assert response.status_code == 201
        assert response.data["external_user_id"] == ""

    def test_widget_submit_with_console_and_network_errors(self):
        """Widget can submit enriched context_metadata with console and network errors."""
        context_metadata = {
            "language": "fr-FR",
            "timezone": "Europe/Paris",
            "referrer": "https://app.acme.com/dashboard",
            "console_errors": [
                {
                    "level": "error",
                    "message": "TypeError: Cannot read property 'id' of undefined",
                    "source": "Settings.tsx:142",
                    "timestamp": "2026-03-08T10:32:15.123Z",
                }
            ],
            "network_errors": [
                {
                    "method": "POST",
                    "url": "/api/v1/settings/",
                    "status": 500,
                    "duration_ms": 234,
                    "timestamp": "2026-03-08T10:32:14.456Z",
                }
            ],
        }
        response = self.client.post(
            "/api/v1/tickets/widget_submit/",
            data={
                "title": "Settings crash",
                "description": "Page broke",
                "requester_name": "Jean",
                "requester_email": "jean@acme.com",
                "context_metadata": context_metadata,
            },
            format="json",
            HTTP_X_WIDGET_TOKEN=self.organization.api_token,
        )
        assert response.status_code == 201
        metadata = response.data["context_metadata"]
        assert len(metadata["console_errors"]) == 1
        assert metadata["console_errors"][0]["level"] == "error"
        assert len(metadata["network_errors"]) == 1
        assert metadata["network_errors"][0]["status"] == 500
