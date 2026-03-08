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
