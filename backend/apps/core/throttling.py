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
