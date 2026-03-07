"""WebSocket URL routing for notifications."""

from django.urls import path

from .consumers import TicketConsumer

websocket_urlpatterns = [
    path("ws/tickets/", TicketConsumer.as_asgi()),
]
