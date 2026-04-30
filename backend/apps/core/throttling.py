"""Custom throttle classes for Showdesk.

Widget endpoints are public (AllowAny) and need rate limiting
to prevent abuse. These throttles are applied per-IP.
"""

from rest_framework.throttling import AnonRateThrottle


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


class SignupThrottle(AnonRateThrottle):
    """Rate limit for self-service signup: 5/hour per IP.

    Tight enough to prevent org-spam from a single source, generous
    enough that a small team signing up together from the same office
    network does not get blocked.
    """

    rate = "5/hour"


class SignupCheckThrottle(AnonRateThrottle):
    """Rate limit for signup pre-flight checks (slug / domain): 30/minute per IP.

    These endpoints are called live as the user types in the signup form,
    so the limit is loose; the goal is only to deflect scripted abuse.
    """

    rate = "30/minute"
