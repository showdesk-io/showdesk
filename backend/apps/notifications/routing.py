"""WebSocket URL routing for notifications."""

from django.urls import path

from .consumers import TicketConsumer, WidgetConsumer

websocket_urlpatterns = [
    path("ws/tickets/", TicketConsumer.as_asgi()),
    path("ws/widget/", WidgetConsumer.as_asgi()),
]
