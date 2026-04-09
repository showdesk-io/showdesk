"""ASGI config for Showdesk."""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from django.urls import path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

django_asgi_app = get_asgi_application()

from apps.notifications.consumers import TicketConsumer, WidgetConsumer  # noqa: E402
from apps.notifications.middleware import (  # noqa: E402
    JWTAuthMiddleware,
    WidgetAuthMiddleware,
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(
            [
                path(
                    "ws/tickets/",
                    JWTAuthMiddleware(TicketConsumer.as_asgi()),
                ),
                path(
                    "ws/widget/",
                    WidgetAuthMiddleware(WidgetConsumer.as_asgi()),
                ),
            ]
        ),
    }
)
