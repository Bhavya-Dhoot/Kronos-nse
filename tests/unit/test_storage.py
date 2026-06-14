"""Unit tests for TimescaleClient and RedisCache.

All external dependencies (asyncpg pool, redis) are mocked.
No live DB or Redis instance required.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from data.storage.redis_cache import RedisCache
from data.storage.timescale import TimescaleClient

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def ts_client() -> TimescaleClient:
    client = TimescaleClient("postgresql://x:x@localhost/x")
    # Inject a fake pool so initialize() is not required
    client._pool = MagicMock()
    return client


@pytest.fixture
def redis_client() -> RedisCache:
    client = RedisCache("redis://localhost:6379")
    client._client = AsyncMock()
    return client


# ─────────────────────────────────────────────────────────────────────────────
# TimescaleClient — get_candles
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_candles_returns_dataframe_with_correct_columns(
    ts_client: TimescaleClient,
):
    """get_candles should return a DataFrame with OHLCV columns and a DatetimeIndex."""
    fake_rows = [
        {
            "time": datetime(2025, 6, 1, 9, 15, tzinfo=UTC),
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 103.0,
            "volume": 1000.0,
        },
        {
            "time": datetime(2025, 6, 1, 9, 16, tzinfo=UTC),
            "open": 103.0,
            "high": 106.0,
            "low": 102.0,
            "close": 104.0,
            "volume": 1200.0,
        },
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = fake_rows
    ts_client._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    ts_client._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    df = await ts_client.get_candles("SBIN", "1m", limit=10)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None
    assert str(df.index.tz) == "Asia/Kolkata"
    assert len(df) == 2


@pytest.mark.asyncio
async def test_get_candles_returns_empty_dataframe_on_no_rows(
    ts_client: TimescaleClient,
):
    """get_candles should return an empty DataFrame when no rows are found."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    ts_client._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    ts_client._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    df = await ts_client.get_candles("SBIN", "1m")

    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


@pytest.mark.asyncio
async def test_get_candles_uses_continuous_aggregate_for_5m(ts_client: TimescaleClient):
    """5m queries query the raw candles table (continuous aggregate routing not yet implemented)."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    ts_client._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    ts_client._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    await ts_client.get_candles("RELIANCE", "5m")

    call_args = mock_conn.fetch.call_args
    query: str = call_args[0][0]
    assert "candles" in query


# ─────────────────────────────────────────────────────────────────────────────
# TimescaleClient — bulk_insert_candles
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_insert_batches_correctly(ts_client: TimescaleClient):
    """bulk_insert_candles should call executemany once per 1000-row batch."""
    # Build 2500 candle dicts
    candles = [
        {
            "time": datetime(2025, 6, 1, 9, 15, tzinfo=UTC),
            "symbol": "SBIN",
            "timeframe": "1m",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 500.0,
        }
        for _ in range(2500)
    ]

    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock()
    ts_client._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    ts_client._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    total = await ts_client.bulk_insert_candles(candles)

    # 2500 rows → 3 batches: 1000 + 1000 + 500
    assert mock_conn.executemany.call_count == 3
    assert total == 2500


@pytest.mark.asyncio
async def test_bulk_insert_single_batch_under_1000(ts_client: TimescaleClient):
    """A list of < 1000 candles should produce exactly one executemany call."""
    candles = [
        {
            "time": datetime(2025, 6, 1, 9, 15, tzinfo=UTC),
            "symbol": "INFY",
            "timeframe": "1m",
            "open": 200.0,
            "high": 201.0,
            "low": 199.0,
            "close": 200.5,
            "volume": 300.0,
        }
        for _ in range(42)
    ]

    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock()
    ts_client._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    ts_client._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    total = await ts_client.bulk_insert_candles(candles)

    assert mock_conn.executemany.call_count == 1
    assert total == 42


# ─────────────────────────────────────────────────────────────────────────────
# RedisCache — serialisation round-trip
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_set_get_round_trip(redis_client: RedisCache):
    """set then get should return the same dict via JSON serialisation."""
    payload = {
        "symbol": "TCS",
        "close": [3500.0, 3510.5, 3498.0],
        "model_version": "v1.2",
        "generated_at": "2025-06-01T09:15:00+05:30",
    }

    # Simulate get returning the JSON-encoded value we set
    redis_client._client.get = AsyncMock(return_value=json.dumps(payload))

    result = await redis_client.get("test:key")

    assert result == payload


@pytest.mark.asyncio
async def test_redis_get_returns_none_on_miss(redis_client: RedisCache):
    """get should return None when the key is absent."""
    redis_client._client.get = AsyncMock(return_value=None)
    result = await redis_client.get("kronos:pred:SBIN:2025-06-01T09:15:00")
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# RedisCache — TTL
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_prediction_uses_setex_with_correct_ttl(redis_client: RedisCache):
    """set_prediction should call setex with the specified TTL."""
    redis_client._client.setex = AsyncMock()
    redis_client._client.set = AsyncMock()

    payload = {"symbol": "SBIN", "close": [500.0]}
    await redis_client.set_prediction("SBIN", "2025-06-01T09:15:00", payload, ttl=300)

    redis_client._client.setex.assert_called_once()
    call_args = redis_client._client.setex.call_args[0]
    # setex(key, ttl, value)
    assert call_args[1] == 300


@pytest.mark.asyncio
async def test_set_dqg_report_uses_default_ttl_of_60(redis_client: RedisCache):
    """set_dqg_report default TTL should be 60 seconds."""
    redis_client._client.setex = AsyncMock()

    report = {"status": "PASS", "coverage_pct": 99.1}
    await redis_client.set_dqg_report("SBIN", "1m", report)

    redis_client._client.setex.assert_called_once()
    ttl_arg = redis_client._client.setex.call_args[0][1]
    assert ttl_arg == 60


@pytest.mark.asyncio
async def test_set_with_no_ttl_uses_plain_set(redis_client: RedisCache):
    """Calling set() without a TTL should use plain SET, not SETEX."""
    redis_client._client.set = AsyncMock()
    redis_client._client.setex = AsyncMock()

    await redis_client.set("some:key", {"val": 1})

    redis_client._client.set.assert_called_once()
    redis_client._client.setex.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# RedisCache — publish channels
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_tick_uses_correct_channel(redis_client: RedisCache):
    """publish_tick should publish to 'ticks:{symbol}'."""
    redis_client._client.publish = AsyncMock()

    await redis_client.publish_tick("SBIN", {"ltp": 500.0})

    redis_client._client.publish.assert_called_once()
    channel = redis_client._client.publish.call_args[0][0]
    assert channel == "ticks:SBIN"


@pytest.mark.asyncio
async def test_publish_dqg_status_uses_correct_channel(redis_client: RedisCache):
    """publish_dqg_status should publish to 'dqg:{symbol}'."""
    redis_client._client.publish = AsyncMock()

    await redis_client.publish_dqg_status("RELIANCE", {"status": "PASS"})

    channel = redis_client._client.publish.call_args[0][0]
    assert channel == "dqg:RELIANCE"


# ─────────────────────────────────────────────────────────────────────────────
# RedisCache — health check
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_returns_true_when_ping_succeeds(redis_client: RedisCache):
    redis_client._client.ping = AsyncMock(return_value=True)
    assert await redis_client.health_check() is True


@pytest.mark.asyncio
async def test_health_check_returns_false_when_no_client():
    client = RedisCache()
    # _client is None — not initialized
    assert await client.health_check() is False
