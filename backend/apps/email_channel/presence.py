"""Whether a widget session has the widget open right now (design §5.2).

The widget's socket marks its session on connect and on each ping, every 25 s, and
unmarks it on disconnect. A mark outlives a missed ping or two, not a closed tab
whose disconnect never came. With two tabs open, closing one unmarks the session
until the other's next ping.

The mark holds the socket's channel name: a socket only unmarks its own mark, so
the late disconnect of a socket a reconnect replaced leaves the new one's.
"""

from django.core.cache import cache
from redis.exceptions import RedisError

from apps.core.cache import cache_errors_raise

PRESENCE_TTL_SECONDS = 60


def _key(session_id) -> str:
    return f"widget_presence:{session_id}"


def mark_connected(session_id: str, channel_name: str) -> bool:
    """Note that ``session_id`` has the widget open, for the next minute.

    False if the cache couldn't take it: the caller reports it, once.
    """
    try:
        with cache_errors_raise():
            cache.set(_key(session_id), channel_name, PRESENCE_TTL_SECONDS)
    except RedisError:
        return False
    return True


def mark_disconnected(session_id: str, channel_name: str) -> bool:
    """Note that the socket ``channel_name`` of ``session_id`` closed.

    False if the cache couldn't be reached.
    """
    try:
        with cache_errors_raise():
            if cache.get(_key(session_id)) == channel_name:
                cache.delete(_key(session_id))
    except RedisError:
        return False
    return True


def is_connected(session_id) -> bool:
    """Tell if ``session_id`` has the widget open."""
    return session_id is not None and cache.get(_key(session_id)) is not None
