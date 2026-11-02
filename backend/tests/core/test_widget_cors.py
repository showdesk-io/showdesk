"""The widget runs on customers' sites: only its routes answer any origin."""

import pytest
from rest_framework.test import APIClient

SITE = "https://shop.customer.example"


def _preflight(path: str):
    return APIClient().options(
        path,
        HTTP_ORIGIN=SITE,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="x-widget-token",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/tickets/widget_session/",
        "/api/v1/tickets/widget_upload_attachment/",
        "/api/v1/videos/widget_upload/",
    ],
)
def test_widget_routes_answer_any_origin(path):
    response = _preflight(path)

    assert response.headers["Access-Control-Allow-Origin"] == SITE
    assert "x-widget-token" in response.headers["Access-Control-Allow-Headers"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/tickets/",
        "/api/v1/contacts/",
        "/api/v1/auth/request-otp/",
        "/api/v1/widget/identity-hash/",
    ],
)
def test_other_routes_keep_the_allow_list(path):
    assert "Access-Control-Allow-Origin" not in _preflight(path).headers


@pytest.mark.django_db
def test_widget_answer_carries_the_header():
    response = APIClient().post(
        "/api/v1/tickets/widget_session/", {}, format="json", HTTP_ORIGIN=SITE
    )

    assert response.headers["Access-Control-Allow-Origin"] == SITE
