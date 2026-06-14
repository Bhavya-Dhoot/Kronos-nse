"""Redis async cache client for Kronos NSE.

Handles prediction caching, DQG status, and Pub/Sub for live ticks and signals.
All values are JSON-serialised. Keys use a consistent namespace scheme.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── key scheme ───────────────────────────────────────────────────────────────
_PRED_KEY = "kronos:pred:{symbol}:{ts}"
_DQG_KEY = "kronos:dqg:{symbol}:{timeframe}"
_TICK_CH = "ticks:{symbol}"
_CANDLE_CH = "candles:{symbol}"
_SIGNAL_CH = "signals:{symbol}"
_DQG_CH = "dqg:{symbol}"
_MVE_KEY = "mve:{key}"


class RedisCache:
    """Async Redis client using redis-py v5 async interface."""

    def __init__(self, url: str = "redis://localhost:6379") -> None:
        self._url = url
        self._client: aioredis.Redis | None = None
        self._pubsubs: list[aioredis.client.PubSub] = []

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create the Redis connection pool."""
        self._client = aioredis.from_url(
            self._url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=5,
            socket_timeout=10,
            retry_on_timeout=True,
        )
        logger.info("Redis pool initialised: %s", self._url)

    async def close(self) -> None:
        """Close all PubSub subscriptions and the Redis connection pool."""
        for ps in self._pubsubs:
            try:
                await ps.aclose()
            except Exception:
                logger.debug("PubSub close ignored", exc_info=True)
        self._pubsubs.clear()
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── generic helpers ───────────────────────────────────────────────────────

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return deserialised JSON value or None if key does not exist."""
        assert self._client, "call initialize() first"
        raw = await self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(
        self, key: str, value: dict[str, Any], ttl: int | None = None
    ) -> None:
        """Serialise value as JSON and store with optional TTL (seconds)."""
        assert self._client, "call initialize() first"
        payload = json.dumps(value, default=str)
        if ttl:
            await self._client.setex(key, ttl, payload)
        else:
            await self._client.set(key, payload)

    async def delete(self, key: str) -> None:
        """Delete a key."""
        assert self._client, "call initialize() first"
        await self._client.delete(key)

    # ── predictions ───────────────────────────────────────────────────────────

    async def set_prediction(
        self,
        symbol: str,
        timestamp_str: str,
        result: dict[str, Any],
        ttl: int = 300,
    ) -> None:
        """Cache a prediction result. Default TTL = 300s (5 minutes)."""
        key = _PRED_KEY.format(symbol=symbol, ts=timestamp_str)
        await self.set(key, result, ttl=ttl)
        logger.debug("set_prediction: %s  ttl=%ds", key, ttl)

    async def get_prediction(
        self, symbol: str, timestamp_str: str
    ) -> dict[str, Any] | None:
        """Return a cached prediction or None on miss."""
        key = _PRED_KEY.format(symbol=symbol, ts=timestamp_str)
        result = await self.get(key)
        if result is None:
            logger.debug("prediction cache MISS: %s", key)
        else:
            logger.debug("prediction cache HIT: %s", key)
        return result

    # ── pub/sub ───────────────────────────────────────────────────────────────

    async def publish_tick(self, symbol: str, tick: dict[str, Any]) -> None:
        """Publish a tick event to the ticks:{symbol} channel."""
        assert self._client, "call initialize() first"
        await self._client.publish(
            _TICK_CH.format(symbol=symbol), json.dumps(tick, default=str)
        )

    async def publish_candle(self, symbol: str, candle: dict[str, Any]) -> None:
        """Publish a completed candle to the candles:{symbol} channel."""
        assert self._client, "call initialize() first"
        await self._client.publish(
            _CANDLE_CH.format(symbol=symbol), json.dumps(candle, default=str)
        )

    async def publish_signal(self, symbol: str, signal: dict[str, Any]) -> None:
        """Publish a trading signal to the signals:{symbol} channel."""
        assert self._client, "call initialize() first"
        await self._client.publish(
            _SIGNAL_CH.format(symbol=symbol), json.dumps(signal, default=str)
        )

    async def publish_prediction(self, symbol: str, prediction: dict[str, Any]) -> None:
        """Publish a prediction to the global predictions channel."""
        assert self._client, "call initialize() first"
        channel = "kronos:predictions"
        payload = {"symbol": symbol, **prediction}
        await self._client.publish(channel, json.dumps(payload, default=str))

    def pubsub(self) -> aioredis.client.PubSub:
        """Create a PubSub instance for channel subscriptions."""
        assert self._client, "call initialize() first"
        ps = self._client.pubsub()
        self._pubsubs.append(ps)
        return ps

    async def publish_dqg_status(self, symbol: str, report: dict[str, Any]) -> None:
        """Publish a DQG report to the dqg:{symbol} channel."""
        assert self._client, "call initialize() first"
        await self._client.publish(
            _DQG_CH.format(symbol=symbol), json.dumps(report, default=str)
        )

    # ── DQG report cache ──────────────────────────────────────────────────────

    async def set_dqg_report(
        self,
        symbol: str,
        timeframe: str,
        report: dict[str, Any],
        ttl: int = 60,
    ) -> None:
        """Cache a DQG report. Default TTL = 60s."""
        key = _DQG_KEY.format(symbol=symbol, timeframe=timeframe)
        await self.set(key, report, ttl=ttl)
        logger.debug("set_dqg_report: %s  ttl=%ds", key, ttl)

    async def get_dqg_report(
        self, symbol: str, timeframe: str
    ) -> dict[str, Any] | None:
        """Return a cached DQG report or None on miss."""
        key = _DQG_KEY.format(symbol=symbol, timeframe=timeframe)
        return await self.get(key)

    # ── MVE ────────────────────────────────────────────────────────────────────

    async def set_mve(
        self, key: str, data: dict[str, Any], ttl: int | None = None
    ) -> None:
        """Store MVE data at mve:{key}. Default TTL = 60s."""
        ttl = ttl or 60
        redis_key = _MVE_KEY.format(key=key)
        await self.set(redis_key, data, ttl=ttl)
        logger.debug("set_mve: %s  ttl=%ds", redis_key, ttl)

    async def get_mve(self, key: str) -> dict[str, Any] | None:
        """Retrieve MVE data from mve:{key}."""
        redis_key = _MVE_KEY.format(key=key)
        return await self.get(redis_key)

    async def publish_mvs(self, mvs: dict[str, Any]) -> None:
        """Publish an MVS update to the mve:mvs:updates channel."""
        assert self._client, "call initialize() first"
        await self._client.publish(
            "mve:mvs:updates",
            json.dumps(mvs, default=str),
        )

    # ── list operations (delegated) ──────────────────────────────────────────

    async def llen(self, key: str) -> int | None:
        """Return the length of a Redis list, or None on error."""
        assert self._client, "call initialize() first"
        try:
            return await self._client.llen(key)
        except Exception:
            logger.exception("LLEN %s failed", key)
            return None

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """Return a range of elements from a Redis list."""
        assert self._client, "call initialize() first"
        return await self._client.lrange(key, start, stop)

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        """Trim a Redis list to the specified range."""
        assert self._client, "call initialize() first"
        await self._client.ltrim(key, start, stop)

    async def rpush(self, key: str, value: str) -> None:
        """Append a value to a Redis list."""
        assert self._client, "call initialize() first"
        await self._client.rpush(key, value)

    async def expire(self, key: str, ttl: int) -> None:
        """Set a TTL on a Redis key."""
        assert self._client, "call initialize() first"
        await self._client.expire(key, ttl)

    # ── async context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> RedisCache:
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── health ────────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Return True if Redis responds to PING."""
        if not self._client:
            return False
        try:
            return await self._client.ping()
        except Exception:
            logger.exception("Redis health check failed")
            return False
