"""JWT authentication middleware for Django Channels WebSocket connections.

Since WebSocket connections cannot use HTTP headers for authentication,
the JWT token is passed as a query parameter: ws://host/ws/tickets/?token=<jwt>
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
