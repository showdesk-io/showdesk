"""WebSocket consumers for real-time notifications.

TicketConsumer — agent dashboard (JWT-authenticated).
WidgetConsumer — widget chat users (token + session-authenticated).
"""

import logging

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
            await self.close()
            return

        # Join organization-specific group
        org_id = await self._get_organization_id(user)
        if org_id:
            self.group_name = f"org_{org_id}"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection."""
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: dict) -> None:
        """Handle incoming WebSocket messages."""
        # Currently read-only, but extensible for future features
        pass

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
        """Handle incoming messages — currently unused."""
        pass

    async def widget_message(self, event: dict) -> None:
        """Send a new message (agent reply) to the widget client."""
        await self.send_json(event["data"])

    async def ticket_status_update(self, event: dict) -> None:
        """Send ticket status change to the widget client."""
        await self.send_json(event["data"])
