"""Custom throttle classes for Showdesk.

Widget endpoints are public (AllowAny) and need rate limiting
to prevent abuse. These throttles are applied per-IP.
"""

import hashlib

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class WidgetSubmitThrottle(AnonRateThrottle):
    """Rate limit for widget ticket submissions: 10/minute per IP."""

    rate = "10/minute"


class WidgetUploadThrottle(AnonRateThrottle):
    """Rate limit for widget video uploads: 20/minute per IP."""

    rate = "20/minute"


class WidgetMessageThrottle(AnonRateThrottle):
    """Rate limit for widget chat messages: 30/minute per IP."""

    rate = "30/minute"


class WidgetSessionThrottle(AnonRateThrottle):
    """Rate limit for widget session creation: 10/minute per IP."""

    rate = "10/minute"


class SignupCheckThrottle(AnonRateThrottle):
    """Rate limit for signup pre-flight checks (slug / domain): 30/minute per IP.

    These endpoints are called live as the user types in the signup form,
    so the limit is loose; the goal is only to deflect scripted abuse.
    """

    rate = "30/minute"


# Signup wizard endpoints (create-org, request-join) are *not* throttled by
# DRF: validation errors (400/409) would count against the limit and lock out
# a user who just typoed their slug. Instead, signup_views counts successful
# org-creations / join-requests manually via the cache.


def _submitted_email(request) -> str | None:
    """Return the normalized email of a DRF or plain Django POST, if any."""
    data = request.data if hasattr(request, "data") else request.POST
    email = data.get("email") if hasattr(data, "get") else None
    if not isinstance(email, str) or not email.strip():
        return None
    return email.strip().lower()


class _OTPIPThrottle(SimpleRateThrottle):
    """Count OTP traffic per client IP. Rates: DEFAULT_THROTTLE_RATES."""

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class _OTPEmailThrottle(SimpleRateThrottle):
    """Count OTP traffic per email, known to us or not, whatever the IP.

    A body with no usable email isn't counted here: validation refuses it.
    """

    def get_cache_key(self, request, view) -> str | None:
        email = _submitted_email(request)
        if email is None:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": hashlib.sha256(email.encode()).hexdigest(),
        }


class OTPRequestIPThrottle(_OTPIPThrottle):
    scope = "otp_request_ip"


class OTPRequestEmailThrottle(_OTPEmailThrottle):
    scope = "otp_request_email"


class OTPVerifyIPThrottle(_OTPIPThrottle):
    scope = "otp_verify_ip"


class OTPVerifyEmailThrottle(_OTPEmailThrottle):
    scope = "otp_verify_email"


# Every path that sends or checks a code shares these, so the counters can't be
# multiplied by switching between login, signup and the Django admin.
OTP_REQUEST_THROTTLES = [OTPRequestIPThrottle, OTPRequestEmailThrottle]
OTP_VERIFY_THROTTLES = [OTPVerifyIPThrottle, OTPVerifyEmailThrottle]
