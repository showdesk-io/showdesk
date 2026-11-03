"""Cache backend that survives a Redis outage."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_raising = ContextVar("cache_errors_raise", default=False)


@contextmanager
def cache_errors_raise() -> Iterator[None]:
    """Let cache errors raise here, for a caller that reports them its own way.

    A frequent caller, such as every ping of every widget, would otherwise log an
    error each time during an outage.
    """
    token = _raising.set(True)
    try:
        yield
    finally:
        _raising.reset(token)


class FailOpenRedisCache(RedisCache):
    """Act as an empty cache when Redis fails, instead of failing the request.

    Throttles and the signup quota then let requests through, so an outage
    doesn't take login and the widget down. What must hold during one can't
    rely on this cache: OTPCode counts its attempts in the database.
    Operations the application doesn't use still raise, and every one does
    within ``cache_errors_raise``.
    """

    def get(self, key, default=None, version=None):
        try:
            return super().get(key, default, version)
        except RedisError as exc:
            if _raising.get():
                raise
            logger.error("Cache read failed, limits are not enforced: %s", exc)
            return default

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            super().set(key, value, timeout, version)
        except RedisError as exc:
            if _raising.get():
                raise
            logger.error("Cache write failed, limits are not enforced: %s", exc)

    def delete(self, key, version=None):
        try:
            return super().delete(key, version)
        except RedisError as exc:
            if _raising.get():
                raise
            logger.error("Cache delete failed: %s", exc)
            return False
