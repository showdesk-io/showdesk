"""Whether a widget session has the widget open right now (design §5.2).

The widget's socket marks its session on connect and on each ping, every 25 s, and
unmarks it on disconnect. A mark outlives a missed ping or two, not a closed tab
whose disconnect never came. With two tabs open, closing one unmarks the session
until the other's next ping.
"""

from django.core.cache import cache

PRESENCE_TTL_SECONDS = 60


def _key(session_id) -> str:
    return f"widget_presence:{session_id}"


def mark_connected(session_id: str) -> None:
    """Note that ``session_id`` has the widget open, for the next minute."""
    cache.set(_key(session_id), 1, PRESENCE_TTL_SECONDS)


def mark_disconnected(session_id: str) -> None:
    """Note that ``session_id`` closed the widget."""
    cache.delete(_key(session_id))


def is_connected(session_id) -> bool:
    """Tell if ``session_id`` has the widget open."""
    return session_id is not None and cache.get(_key(session_id)) is not None
