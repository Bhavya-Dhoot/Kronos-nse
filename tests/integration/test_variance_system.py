"""Async integration tests for MVE lifecycle (DQG-05).

These tests use direct engine control per D-25 — create MarketVarianceEngine
with mocked collectors, inject dimension updates manually via
_on_dimension_update(). All collectors are MagicMock-based, no live APIs.

Async integration tests (not TestClient) per D-23.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from data.quality.checks import check_mve_health
from variance.engine import MarketVarianceEngine, ScoreEntry
from variance.modifier import PredictionModifier
from variance.schemas import DimensionScore


# ── Mock helpers ──────────────────────────────────────────────────────────────


def _make_mock_collector(
    name: str,
    poll_interval: int = 1,
    score: float = 0.0,
    available: bool = True,
    poll_result: dict | None = None,
) -> MagicMock:
    """Create a mock BaseVarianceCollector with controlled behavior.

    Parameters
    ----------
    name : str
        Collector name (vix, options, etc.)
    poll_interval : int
        poll_interval property value (seconds).
    score : float
        Normalized score returned in poll() result.
    available : bool
        is_available property value.
    poll_result : dict | None
        Full poll() return value. If None, builds a default from score.
    """
    collector = MagicMock()
    collector.name = name
    collector.poll_interval = poll_interval
    collector.is_available = available

    if poll_result is None:
        poll_result = {
            "normalized": score,
            "raw_value": None if name != "vix" else 15.0,
            "detail": {},
        }

    collector.poll = AsyncMock(return_value=poll_result)
    return collector


class MockRedis:
    """Minimal mock RedisCache for engine tests.

    Provides just enough interface for the engine to work without
    a real Redis connection.  Tracks publish_mvs calls for test assertions.
    """

    def __init__(self) -> None:
        self.publish_calls: list[dict] = []
        self._client = AsyncMock()
        self._client.lrange = AsyncMock(return_value=[])
        self._client.rpush = AsyncMock()
        self._client.ltrim = AsyncMock()
        self._client.expire = AsyncMock()
        self._client.llen = AsyncMock(return_value=0)

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def set_mve(self, key: str, value: dict, ttl: int = 60) -> None:
        pass

    async def publish_mvs(self, mvs_dict: dict) -> None:
        self.publish_calls.append(mvs_dict)


class MockTimescale:
    """Minimal mock TimescaleClient for engine tests.

    Records inserts for later assertion.
    """

    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def insert_mve_history(self, mvs_dict: dict) -> None:
        self.entries.append(mvs_dict)

    async def get_mve_history(self, limit: int = 1000) -> list[dict]:
        return []


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_collectors() -> dict[str, MagicMock]:
    """Create a full set of 7 mocked collectors, all healthy."""
    return {
        "vix": _make_mock_collector("vix", poll_interval=1, score=-0.15, poll_result={
            "normalized": -0.15, "raw_value": 15.0, "detail": {},
        }),
        "options": _make_mock_collector("options", poll_interval=1, score=0.42),
        "fii_dii": _make_mock_collector("fii_dii", poll_interval=1, score=0.55),
        "oi": _make_mock_collector("oi", poll_interval=1, score=-0.22),
        "gift_nifty": _make_mock_collector("gift_nifty", poll_interval=1, score=0.18),
        "global_markets": _make_mock_collector("global_markets", poll_interval=1, score=0.30),
        "macro": _make_mock_collector("macro", poll_interval=1, score=-0.10),
    }


@pytest.fixture
def mock_redis() -> MockRedis:
    return MockRedis()


@pytest.fixture
def mock_timescale() -> MockTimescale:
    return MockTimescale()


@pytest.fixture
def base_config() -> dict:
    """Minimal config matching config/base.yaml §variance structure."""
    return {
        "weights": {
            "vix": 0.25,
            "options": 0.20,
            "institutional": 0.25,
            "gift_nifty": 0.15,
            "global_macro": 0.15,
        },
        "modification": {
            "temperature_base": 0.015,
            "vix_baseline": 15,
            "temperature_cap": 0.3,
            "band_width_per_vix_point": 0.008,
            "signal_base_threshold": 0.005,
            "signal_threshold_per_vix_point": 0.0002,
        },
        "engine": {
            "global_combined_weight": 0.30,
        },
        "mve_history": {
            "retention_days": 30,
        },
    }


@pytest.fixture
def sample_prediction() -> dict:
    """A minimal prediction result dict for modifier tests."""
    return {
        "symbol": "NIFTY",
        "pred_open": [19500.0],
        "pred_high": [19600.0],
        "pred_low": [19400.0],
        "pred_close": [19550.0],
        "pred_volume": [100000.0],
        "pred_timestamps": [datetime.now(timezone.utc).isoformat()],
        "temperature": 0.7,
        "confidence": "MEDIUM",
    }


# ── Lifecycle Tests (DQG-05 / D-24) ──────────────────────────────────────────


@pytest.mark.asyncio
class TestMVELifecycle:
    """Full MVE lifecycle integration tests.

    Each test creates a MarketVarianceEngine with mocked collectors,
    exercises specific lifecycle scenarios, and verifies outcomes.
    Per D-25: direct engine control with mocked collectors.
    """
