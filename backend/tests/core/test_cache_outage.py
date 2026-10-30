"""A Redis outage lifts the rate limits instead of failing the request."""

import logging

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client
from rest_framework.test import APIClient

from apps.organizations.models import OTPCode
from config.settings import base as base_settings
from tests.factories import OrganizationFactory, UserFactory

pytestmark = pytest.mark.django_db

EMAIL = "someone@example.com"
LOGIN_REQUEST = "/api/v1/auth/request-otp/"
LOGIN_VERIFY = "/api/v1/auth/verify-otp/"
SIGNUP_REQUEST = "/api/v1/auth/signup/request-otp/"
SIGNUP_VERIFY = "/api/v1/auth/signup/verify-otp/"
WIDGET_SESSION = "/api/v1/tickets/widget_session/"


@pytest.fixture
def redis_down(settings):
    """Use the production cache settings, on a port nothing listens to."""
    settings.CACHES = {
        "default": {
            **base_settings.CACHES["default"],
            "LOCATION": "redis://127.0.0.1:1/0",
        },
    }


@pytest.fixture
def agent_email():
    UserFactory(email=EMAIL)
    return EMAIL


def _wrong(otp: OTPCode) -> str:
    return "000000" if otp.code != "000000" else "111111"


def test_the_outage_is_real_and_logged(redis_down, caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="apps.core.cache"):
        assert cache.get("key", "fallback") == "fallback"
        cache.set("key", "value")
        assert cache.delete("key") is False
    assert [record.levelname for record in caplog.records] == ["ERROR"] * 3
    assert "127.0.0.1:1" in caplog.text


def test_other_cache_errors_still_raise(redis_down, monkeypatch) -> None:
    monkeypatch.setattr(
        "django.core.cache.backends.redis.RedisCache.get",
        lambda *args: 1 / 0,
    )
    with pytest.raises(ZeroDivisionError):
        cache.get("key")


def test_login_works_past_every_limit(redis_down, agent_email, caplog) -> None:
    for _ in range(7):
        response = APIClient().post(LOGIN_REQUEST, {"email": agent_email})
        assert response.status_code == 200
    assert len(mail.outbox) == 7
    assert "limits are not enforced" in caplog.text

    otp = OTPCode.objects.get(email=agent_email, used_at__isnull=True)
    response = APIClient().post(LOGIN_VERIFY, {"email": agent_email, "code": otp.code})
    assert response.status_code == 200
    assert "access" in response.data


def test_the_attempt_limit_still_holds(redis_down, agent_email, settings) -> None:
    otp = OTPCode.generate(agent_email)
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        response = APIClient().post(
            LOGIN_VERIFY, {"email": agent_email, "code": _wrong(otp)}
        )
        assert response.status_code == 401
    response = APIClient().post(LOGIN_VERIFY, {"email": agent_email, "code": otp.code})
    assert response.status_code == 401


def test_the_admin_form_works(redis_down) -> None:
    UserFactory(email=EMAIL, is_staff=True)
    otp = OTPCode.generate(EMAIL)
    response = Client().post(
        "/admin/login/", {"step": "code", "email": EMAIL, "code": otp.code}
    )
    assert response.status_code == 302


def test_signup_works(redis_down) -> None:
    client = APIClient()
    body = {"email": EMAIL, "full_name": "Jane Doe"}
    assert client.post(SIGNUP_REQUEST, body).status_code == 200

    otp = OTPCode.objects.get(email=EMAIL, used_at__isnull=True)
    response = client.post(SIGNUP_VERIFY, {"email": EMAIL, "code": otp.code})
    assert response.status_code == 200

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    response = client.post(
        "/api/v1/auth/signup/create-org/", {"org_name": "X", "org_slug": "x-org"}
    )
    assert response.status_code == 201


def test_the_widget_session_works_past_the_limit(redis_down) -> None:
    organization = OrganizationFactory()
    for _ in range(11):
        response = APIClient().post(
            WIDGET_SESSION,
            {"external_user_id": "visitor"},
            format="json",
            HTTP_X_WIDGET_TOKEN=str(organization.api_token),
        )
        assert response.status_code in (200, 201)
