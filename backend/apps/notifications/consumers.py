"""WebSocket consumers for real-time notifications.

TicketConsumer — agent dashboard (JWT-authenticated).
WidgetConsumer — widget chat users (token + session-authenticated).
"""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class TicketConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for real-time ticket updates.

    Agents connect to this consumer to receive live notifications
    about new tickets, status changes, and new messages.
    """

    async def connect(self) -> None:
        """Handle WebSocket connection."""
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            logger.warning("TicketConsumer: rejecting anonymous connection")
            await self.close()
            return

        # Superusers may impersonate an org via ?org=<uuid>, matching the
        # X-Showdesk-Org header used on HTTP requests. Otherwise fall back
        # to the user's own organization.
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        requested_org = (parse_qs(query_string).get("org") or [None])[0]
        if requested_org and getattr(user, "is_superuser", False):
            org_id = requested_org
        else:
            org_id = await self._get_organization_id(user)

        if org_id:
            self.group_name = f"org_{org_id}"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            logger.info(
                "TicketConsumer connected: user=%s group=%s",
                getattr(user, "email", user.pk),
                self.group_name,
            )
        else:
            logger.warning(
                "TicketConsumer: rejecting user %s — no organization_id",
                getattr(user, "email", user.pk),
            )
            await self.close()

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection."""
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: dict) -> None:
        """Handle incoming WebSocket messages.

        Currently only handles app-level heartbeat: client sends {"type": "ping"},
        server replies with {"type": "pong"}. This keeps proxies (Cloudflare, Caddy)
        from closing the connection on idle and lets the client detect dead links.
        """
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def ticket_update(self, event: dict) -> None:
        """Send ticket update to the WebSocket client."""
        await self.send_json(event["data"])

    async def ticket_new(self, event: dict) -> None:
        """Send new ticket notification to the WebSocket client."""
        await self.send_json(event["data"])

    async def ticket_message(self, event: dict) -> None:
        """Send new message notification to the WebSocket client."""
        await self.send_json(event["data"])

    async def ticket_message_deleted(self, event: dict) -> None:
        """Send message deletion notification to the WebSocket client."""
        await self.send_json(event["data"])

    @database_sync_to_async
    def _get_organization_id(self, user) -> str | None:  # noqa: ANN001
        """Get the organization ID for a user."""
        if user.organization_id:
            return str(user.organization_id)
        return None


class WidgetConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for widget chat users.

    Widget users connect with their session_id and org token (via query params).
    They receive real-time agent replies on their tickets.
    """

    async def connect(self) -> None:
        """Handle WebSocket connection."""
        session = self.scope.get("widget_session")
        if not session:
            await self.close()
            return

        self.session_id = str(session.id)
        self.group_name = f"widget_session_{self.session_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection."""
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: dict) -> None:
        """Handle incoming messages.

        Supports app-level heartbeat: {"type": "ping"} → {"type": "pong"}.
        """
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def widget_message(self, event: dict) -> None:
        """Send a new message (agent reply) to the widget client."""
        await self.send_json(event["data"])

    async def ticket_status_update(self, event: dict) -> None:
        """Send ticket status change to the widget client."""
        await self.send_json(event["data"])
