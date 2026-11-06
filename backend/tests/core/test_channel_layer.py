"""The channel layer must outwait its own blocking pop.

channels_redis waits for a message with a BRPOP of ``brpop_timeout`` seconds. redis-py
8 gives every connection a 5 s socket timeout by default, the same: an idle consumer's
read then timed out on the client side, and its socket died with it.
"""

import asyncio
import time
from urllib.parse import urlsplit, urlunsplit

import pytest
import redis
from asgiref.sync import async_to_sync
from channels_redis.core import RedisChannelLayer
from decouple import config

from config.settings import base as base_settings

# Longer than redis-py's default socket timeout, which the layer used to get.
IDLE_SECONDS = 6.5


def _layer_config() -> dict:
    return base_settings.CHANNEL_LAYERS["default"]["CONFIG"]


def _host(address: str | None = None) -> dict:
    """The layer's host entry, as channels_redis reads it, at another address if given."""
    (entry,) = _layer_config()["hosts"]
    host = dict(entry) if isinstance(entry, dict) else {"address": entry}
    if address:
        host["address"] = address
    return host


def test_the_socket_timeout_outlasts_the_blocking_pop():
    host = _host()
    assert host["address"] == config("REDIS_URL", default="redis://localhost:6379/0")
    assert host["socket_timeout"] >= 2 * RedisChannelLayer.brpop_timeout


def test_the_layer_hands_it_to_its_connections():
    layer = RedisChannelLayer(**_layer_config())
    pool = layer.create_pool(0)
    assert pool.connection_kwargs["socket_timeout"] == _host()["socket_timeout"]


def _test_redis_url() -> str:
    """The Redis the settings point at, on a database of its own (6)."""
    parts = urlsplit(config("REDIS_URL", default="redis://localhost:6379/0"))
    return urlunsplit(parts._replace(path="/6"))


def _redis_is_there(url: str) -> bool:
    try:
        return redis.Redis.from_url(url, socket_connect_timeout=1).ping()
    except redis.RedisError:
        return False


def test_an_idle_receive_waits_past_the_default_socket_timeout():
    url = _test_redis_url()
    if not _redis_is_there(url):
        pytest.skip(f"no Redis at {url}")
    config_ = {**_layer_config(), "hosts": [_host(url)], "prefix": "test-idle"}

    async def run() -> tuple[dict, float]:
        receiver = RedisChannelLayer(**config_)
        sender = RedisChannelLayer(**config_)
        channel = await receiver.new_channel()
        started = time.monotonic()
        receiving = asyncio.ensure_future(receiver.receive(channel))
        await asyncio.sleep(IDLE_SECONDS)
        # Still waiting, rather than failed on a read timeout.
        assert not receiving.done()
        await sender.send(channel, {"type": "hello"})
        message = await asyncio.wait_for(receiving, timeout=5)
        elapsed = time.monotonic() - started
        await receiver.flush()
        await receiver.close_pools()
        await sender.close_pools()
        return message, elapsed

    message, elapsed = async_to_sync(run)()

    assert message == {"type": "hello"}
    assert elapsed >= IDLE_SECONDS
