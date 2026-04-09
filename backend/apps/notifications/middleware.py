"""Authentication middleware for Django Channels WebSocket connections.

JWTAuthMiddleware — agent dashboard (JWT via query param).
WidgetAuthMiddleware — widget chat (org token + session_id via query params).
"""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)


@database_sync_to_async
def get_user_from_token(token_str: str):
    """Validate a JWT access token and return the corresponding user."""
    from django.contrib.auth import get_user_model

    User = get_user_model()

    try:
        token = AccessToken(token_str)
        user_id = token["user_id"]
        return User.objects.get(id=user_id)
    except Exception:
        logger.debug("WebSocket JWT authentication failed.")
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """Authenticate WebSocket connections using JWT from query params.

    Usage in ASGI routing:
        JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
    """

    async def __call__(self, scope, receive, send):
        """Extract JWT from query string and set scope['user']."""
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)

        token_list = query_params.get("token", [])
        if token_list:
            scope["user"] = await get_user_from_token(token_list[0])
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


@database_sync_to_async
def get_widget_session(token_str: str, session_id: str):
    """Validate org token + session_id and return the WidgetSession."""
    from apps.organizations.models import Organization
    from apps.tickets.models import WidgetSession

    try:
        org = Organization.objects.get(api_token=token_str, is_active=True)
        return WidgetSession.objects.get(id=session_id, organization=org)
    except (Organization.DoesNotExist, WidgetSession.DoesNotExist, ValueError):
        logger.debug("WebSocket widget authentication failed.")
        return None


class WidgetAuthMiddleware(BaseMiddleware):
    """Authenticate widget WebSocket connections using org token + session_id.

    Query params: ws://host/ws/widget/?token=<api_token>&session=<session_id>
    Sets scope['widget_session'] on success.
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)

        token_list = query_params.get("token", [])
        session_list = query_params.get("session", [])

        if token_list and session_list:
            scope["widget_session"] = await get_widget_session(
                token_list[0], session_list[0]
            )
        else:
            scope["widget_session"] = None

        return await super().__call__(scope, receive, send)
