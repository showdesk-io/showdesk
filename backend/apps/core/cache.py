"""Cache backend that survives a Redis outage."""

import logging

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class FailOpenRedisCache(RedisCache):
    """Act as an empty cache when Redis fails, instead of failing the request.

    Throttles and the signup quota then let requests through, so an outage
    doesn't take login and the widget down. What must hold during one can't
    rely on this cache: OTPCode counts its attempts in the database.
    Operations the application doesn't use still raise.
    """

    def get(self, key, default=None, version=None):
        try:
            return super().get(key, default, version)
        except RedisError as exc:
            logger.error("Cache read failed, limits are not enforced: %s", exc)
            return default

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            super().set(key, value, timeout, version)
        except RedisError as exc:
            logger.error("Cache write failed, limits are not enforced: %s", exc)

    def delete(self, key, version=None):
        try:
            return super().delete(key, version)
        except RedisError as exc:
            logger.error("Cache delete failed: %s", exc)
            return False
