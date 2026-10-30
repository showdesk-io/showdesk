"""OTP codes can't be guessed: attempts are counted, requests are limited."""

import threading

import pytest
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.db import connection
from django.test import Client
from rest_framework.test import APIClient

from apps.organizations.models import OTPCode
from config.settings import base as base_settings
from tests.factories import AdminFactory, EndUserFactory, UserFactory

pytestmark = pytest.mark.django_db

LOGIN_VERIFY = "/api/v1/auth/verify-otp/"
SIGNUP_VERIFY = "/api/v1/auth/signup/verify-otp/"
LOGIN_REQUEST = "/api/v1/auth/request-otp/"
SIGNUP_REQUEST = "/api/v1/auth/signup/request-otp/"
ADMIN_LOGIN = "/admin/login/"
EMAIL = "someone@example.com"
INVALID = "Invalid or expired code."
ALL_PATHS = [LOGIN_VERIFY, SIGNUP_VERIFY, ADMIN_LOGIN]


def _wrong(otp: OTPCode) -> str:
    return "000000" if otp.code != "000000" else "111111"


def _verify_api(path: str, code: str, email: str = EMAIL, **extra):
    return APIClient().post(path, {"email": email, "code": code}, **extra)


def _verify_admin(code: str, email: str = EMAIL):
    return Client().post(ADMIN_LOGIN, {"step": "code", "email": email, "code": code})


def _submit(path: str, code: str) -> bool:
    """Send a code on one of the three login paths; return whether it worked."""
    if path == ADMIN_LOGIN:
        return _verify_admin(code).status_code == 302
    return _verify_api(path, code).status_code == 200


def _request_status(path: str, email: str = EMAIL, ip: str = "10.0.0.1") -> int:
    return APIClient().post(path, {"email": email}, REMOTE_ADDR=ip).status_code


@pytest.fixture
def staff():
    return AdminFactory(email=EMAIL, is_staff=True)


@pytest.fixture
def otp(staff):
    return OTPCode.generate(EMAIL)


class TestAttemptLimit:
    @pytest.mark.parametrize("path", ALL_PATHS)
    def test_five_wrong_codes_invalidate_the_active_code(self, otp, path) -> None:
        for _ in range(5):
            assert _submit(path, _wrong(otp)) is False
        otp.refresh_from_db()
        assert otp.attempts == 5
        assert otp.used_at is not None
        assert _submit(path, otp.code) is False

    @pytest.mark.parametrize("path", ALL_PATHS)
    def test_the_right_code_works_within_the_limit(self, otp, path) -> None:
        for _ in range(4):
            assert _submit(path, _wrong(otp)) is False
        assert _submit(path, otp.code) is True
        otp.refresh_from_db()
        assert otp.used_at is not None

    @pytest.mark.parametrize("path", ALL_PATHS)
    def test_a_code_works_only_once(self, otp, path) -> None:
        assert _submit(path, otp.code) is True
        assert _submit(path, otp.code) is False

    def test_attempts_are_shared_between_the_paths(self, otp) -> None:
        for path in ALL_PATHS:
            _submit(path, _wrong(otp))
        otp.refresh_from_db()
        assert otp.attempts == 3

    @pytest.mark.parametrize("path", [LOGIN_VERIFY, SIGNUP_VERIFY])
    def test_every_failure_looks_the_same(self, otp, path) -> None:
        wrong_code = _verify_api(path, _wrong(otp))
        no_code = _verify_api(path, "123456", email="nobody@example.com")
        for _ in range(4):
            _verify_api(path, _wrong(otp))
        spent = _verify_api(path, otp.code)
        assert wrong_code.status_code == no_code.status_code == spent.status_code == 401
        assert wrong_code.data == no_code.data == spent.data
        assert wrong_code.data["detail"] == INVALID

    def test_wrong_codes_for_an_email_without_a_code_store_nothing(self) -> None:
        assert _verify_api(LOGIN_VERIFY, "123456").status_code == 401
        assert not OTPCode.objects.exists()

    def test_an_expired_code_does_not_verify(self, otp, settings) -> None:
        settings.OTP_EXPIRY_SECONDS = -1
        assert _submit(LOGIN_VERIFY, otp.code) is False

    def test_a_new_code_starts_a_new_count(self, otp) -> None:
        for _ in range(5):
            _submit(LOGIN_VERIFY, _wrong(otp))
        fresh = OTPCode.generate(EMAIL)
        assert fresh.attempts == 0
        assert _submit(LOGIN_VERIFY, fresh.code) is True

    def test_only_the_latest_code_is_compared(self) -> None:
        older = OTPCode.objects.create(email=EMAIL, code="222222")
        latest = OTPCode.objects.create(email=EMAIL, code="333333")
        assert OTPCode.redeem(EMAIL, older.code) is None
        assert OTPCode.redeem(EMAIL, latest.code) == latest


@pytest.mark.django_db(transaction=True)
def test_parallel_guesses_cannot_exceed_the_limit() -> None:
    otp = OTPCode.objects.create(email=EMAIL, code="123456")
    barrier = threading.Barrier(12)

    def guess() -> None:
        try:
            barrier.wait(timeout=10)
            OTPCode.redeem(EMAIL, "000000")
        finally:
            connection.close()

    threads = [threading.Thread(target=guess) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    otp.refresh_from_db()
    assert otp.attempts == 5
    assert otp.used_at is not None


class TestThrottles:
    def test_requesting_codes_is_limited_per_email(self, staff) -> None:
        statuses = [
            _request_status(LOGIN_REQUEST, ip=f"10.0.0.{i}") for i in range(1, 7)
        ]
        assert statuses == [200] * 5 + [429]

    def test_the_email_limit_ignores_the_case(self, staff) -> None:
        for _ in range(5):
            assert _request_status(LOGIN_REQUEST, EMAIL.upper()) == 200
        assert _request_status(LOGIN_REQUEST, EMAIL) == 429

    def test_the_email_limit_is_shared_between_the_paths(self, staff) -> None:
        for path in [LOGIN_REQUEST, SIGNUP_REQUEST] * 2 + [LOGIN_REQUEST]:
            assert _request_status(path) == 200
        assert _request_status(SIGNUP_REQUEST) == 429
        response = Client(REMOTE_ADDR="10.9.9.9").post(
            ADMIN_LOGIN, {"step": "email", "email": EMAIL}
        )
        assert response.status_code == 429
        assert b"Too many attempts" in response.content

    def test_unknown_emails_are_limited_the_same_way(self) -> None:
        statuses = [_request_status(LOGIN_REQUEST) for _ in range(6)]
        assert statuses == [200] * 5 + [429]

    def test_throttled_requests_send_no_new_code(self, staff) -> None:
        for _ in range(5):
            _request_status(LOGIN_REQUEST)
        assert OTPCode.objects.filter(email=EMAIL).count() == 5
        assert _request_status(LOGIN_REQUEST) == 429
        assert OTPCode.objects.filter(email=EMAIL).count() == 5

    def test_requesting_codes_is_limited_per_ip(self) -> None:
        statuses = [
            _request_status(LOGIN_REQUEST, f"user{i}@example.com") for i in range(31)
        ]
        assert statuses == [200] * 30 + [429]

    def test_verifying_is_limited_per_email(self, staff) -> None:
        statuses = [
            _verify_api(LOGIN_VERIFY, "000000", REMOTE_ADDR=f"10.0.1.{i}").status_code
            for i in range(1, 12)
        ]
        assert statuses == [401] * 10 + [429]

    def test_verifying_is_limited_per_ip(self) -> None:
        statuses = [
            _verify_api(
                SIGNUP_VERIFY, "000000", email=f"user{i}@example.com"
            ).status_code
            for i in range(61)
        ]
        assert statuses == [401] * 60 + [429]

    def test_the_verify_limit_is_shared_with_the_admin_form(self, otp) -> None:
        for _ in range(10):
            _verify_api(LOGIN_VERIFY, _wrong(otp))
        response = _verify_admin(otp.code)
        assert response.status_code == 429
        assert b"Too many attempts" in response.content

    def test_a_non_object_body_is_refused_not_a_crash(self) -> None:
        response = APIClient().post(LOGIN_REQUEST, [1, 2], format="json")
        assert response.status_code == 400

    def test_setup_cannot_refresh_a_code_for_free(self) -> None:
        body = {"email": EMAIL, "first_name": "A"}
        statuses = [
            APIClient().post("/api/v1/setup/initialize/", body).status_code
            for _ in range(6)
        ]
        assert statuses == [201] * 5 + [429]


class TestAdminLogin:
    def test_a_wrong_code_is_a_form_error(self, otp) -> None:
        response = _verify_admin(_wrong(otp))
        assert response.status_code == 200
        assert INVALID.encode() in response.content

    def test_the_limit_is_a_form_error(self, otp) -> None:
        for _ in range(5):
            _verify_admin(_wrong(otp))
        response = _verify_admin(otp.code)
        assert response.status_code == 200
        assert INVALID.encode() in response.content

    def test_logging_in_proves_the_email(self, staff, otp) -> None:
        assert staff.is_verified is False
        assert _verify_admin(otp.code).status_code == 302
        staff.refresh_from_db()
        assert staff.is_verified is True

    @pytest.mark.parametrize(
        "target",
        [
            "https://evil.example/",
            "//evil.example/",
            "javascript:alert(1)",
            "admin:logout",
        ],
    )
    def test_next_cannot_leave_the_site(self, otp, target) -> None:
        response = Client().post(
            f"{ADMIN_LOGIN}?next={target}",
            {"step": "code", "email": EMAIL, "code": otp.code},
        )
        assert response.status_code == 302
        assert response["Location"] == "/admin/"

    def test_next_can_stay_on_the_site(self, otp) -> None:
        response = Client().post(
            f"{ADMIN_LOGIN}?next=/admin/organizations/user/",
            {"step": "code", "email": EMAIL, "code": otp.code},
        )
        assert response["Location"] == "/admin/organizations/user/"

    def test_a_non_staff_agent_cannot_use_it(self) -> None:
        UserFactory(email=EMAIL, is_staff=False)
        otp = OTPCode.generate(EMAIL)
        assert _submit(ADMIN_LOGIN, otp.code) is False

    def test_an_end_user_left_with_is_staff_cannot_use_it(self) -> None:
        EndUserFactory(email=EMAIL, is_staff=True)
        otp = OTPCode.generate(EMAIL)
        assert _submit(ADMIN_LOGIN, otp.code) is False


def test_throttle_counters_are_shared_between_worker_processes() -> None:
    # The configured value: tests themselves run on the in-memory cache below.
    assert (
        base_settings.CACHES["default"]["BACKEND"]
        == "django.core.cache.backends.redis.RedisCache"
    )


def test_tests_never_reach_a_real_cache_server() -> None:
    assert isinstance(caches["default"], LocMemCache)
